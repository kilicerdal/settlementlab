"""Financial workflow orchestration over an injected transaction store."""
from .ports import Store
import json
from datetime import date, datetime, timezone
from ..core.validation import DomainError, cents, positive_int, next_business_day

class SettlementService:

    def __init__(self, store: "Store", clock, calendar):
        self.store = store
        self.clock = clock
        self.calendar = calendar

    def event(self, repository, trade, actor, action, detail):
        repository.append_audit((trade, datetime.now(timezone.utc).isoformat(), actor, action, detail))

    def get(self, repository, trade_id):
        row = repository.find_trade((trade_id,))
        if row is None:
            raise DomainError('Trade not found', 404)
        trade = dict(row)
        history = [dict(r) for r in repository.list_manager_revisions((trade_id,))]
        trade['manager_submission'] = json.loads(history[-1]['payload']) if history else None
        trade['submission_history'] = [dict(revision=r['revision'], timestamp=r['timestamp'], terms=json.loads(r['payload'])) for r in history]
        trade['matching'] = json.loads(trade['matching_result'])
        approvals = [dict(r) for r in repository.list_approvals((trade_id,))]
        for request in approvals:
            request.pop('fingerprint')
        trade['approval_history'] = approvals
        trade['pending_approval'] = next((r for r in approvals if r['status'] == 'PENDING'), None)
        trade['settlement_journal'] = None
        if trade['settlement_model'] == 'shared-ledger':
            
            trade['cash_cents'] = repository.balance(trade['buyer_id'], 'CASH:USD')
            trade['securities'] = repository.balance(trade['seller_id'], 'SEC:' + trade['symbol'])
            batch = repository.find_settlement_batch((trade_id,))
            trade['settlement_journal'] = batch['id'] if batch else None
        from ..core.calendar import readiness
        trade['settlement_readiness']=readiness(trade,self.clock)
        return trade

    def create(self, data, key, actor='broker', principal=None):
        if not isinstance(key, str) or not 1 <= len(key) <= 120:
            raise DomainError('An Idempotency-Key of 1–120 characters is required')
        from ..core.matching import normalize_terms
        mode = data.get('matching_mode', 'allocation-only')
        if mode not in ('allocation-only', 'two-sided'):
            raise DomainError('matching_mode must be allocation-only or two-sided')
        settlement_model = data.get('settlement_model', 'trade-scoped')
        if settlement_model not in ('trade-scoped', 'shared-ledger'):
            raise DomainError('Unknown settlement model')
        if settlement_model == 'shared-ledger':
            from ..core.identity import require
            require(principal, 'maker')
            if mode != 'two-sided':
                raise DomainError('Shared-ledger trades require independent two-sided matching')
            actor = principal.id
        terms = normalize_terms(data, complete=mode == 'two-sided')
        if terms['currency'] != 'USD':
            raise DomainError('Broker trades support USD only; no FX conversion is simulated')
        if settlement_model == 'shared-ledger':
            from ..core.postings import LIMIT
            if terms['quantity'] * terms['price_cents'] > LIMIT:
                raise DomainError('Shared-ledger notional exceeds the exact browser-safe limit')
        (symbol, quantity, price) = (terms['symbol'], terms['quantity'], terms['price_cents'])
        (trade_date, settlement_date) = (terms['trade_date'], terms['settlement_date'])
        fingerprint = json.dumps(dict(terms, matching_mode=mode), sort_keys=True)
        with self.store.transaction() as repository:
            buyer = seller = None
            if settlement_model == 'shared-ledger':
                manager = repository.participant(data.get('manager_id', 'SYN-ALPHA'))
                broker = repository.participant(data.get('broker_id', 'SYN-BROKER'))
                if manager == broker:
                    raise DomainError('Buyer and seller must be different participants')
                (buyer, seller) = (manager, broker) if terms['side'] == 'BUY' else (broker, manager)
                fingerprint = json.dumps(dict(terms, matching_mode=mode, settlement_model=settlement_model, manager_id=manager, broker_id=broker), sort_keys=True)
            existing = repository.find_trade_by_key((key,))
            if existing:
                legacy_fingerprint = json.dumps([symbol, quantity, price, trade_date])
                legacy_replay = settlement_model == 'trade-scoped' and mode == 'allocation-only' and (terms['side'] == 'BUY') and (existing['fingerprint'] == legacy_fingerprint)
                if existing['fingerprint'] != fingerprint and (not legacy_replay):
                    raise DomainError('Idempotency key already used for a different submission', 409)
                return self.get(repository, existing['id'])
            if settlement_model=='shared-ledger':
                if not self.calendar.is_open(date.fromisoformat(trade_date)):
                    raise DomainError('Trade date is closed under the configured simulation calendar')
                if settlement_date!=self.calendar.next_day(trade_date):
                    raise DomainError('Shared trades require next-business-day settlement under the configured calendar')
            number = repository.count_trades() + 1
            trade_id = 'SL-%06d' % number
            repository.insert_trade((trade_id, key, fingerprint, symbol.upper(), quantity, price, trade_date, settlement_date, 'RECEIVED'))
            repository.set_trade_terms((terms['side'], terms['currency'], mode, trade_id))
            repository.set_settlement_parties((settlement_model, buyer, seller, trade_id))
            repository.pin_calendar((json.dumps(self.calendar.to_dict()),trade_id))
            self.event(repository, trade_id, actor, 'TRADE_RECEIVED', 'Broker submission accepted')
            return self.get(repository, trade_id)

    def command(self, trade_id, action, data, actor='operator', principal=None):
        if action == 'manager':
            return self.submit_manager(trade_id, data, principal)
        with self.store.transaction() as repository:
            trade = self.get(repository, trade_id)
            if trade['settlement_model'] == 'shared-ledger':
                from ..core.identity import require
                if action in ('request-affirmation', 'approve', 'reject'):
                    return self.approval_command(repository, trade, action, data, principal)
                if action in ('affirm', 'fund'):
                    raise DomainError('Shared-ledger trades require checker approval and participant treasury funding', 403)
                require(principal, 'checker' if action == 'settle' else 'maker')
                actor = principal.id
            elif action in ('request-affirmation', 'approve', 'reject'):
                raise DomainError('Approval commands require a shared-ledger trade', 409)
            version = data.get('version')
            if isinstance(version, bool) or not isinstance(version, int) or version != trade['version']:
                raise DomainError('Stale or missing version; refresh before updating', 409)
            state = trade['state']
            if action == 'allocate':
                if trade['matching_mode'] == 'two-sided':
                    raise DomainError('Two-sided trades require an independent manager submission', 409)
                if state not in ('RECEIVED', 'EXCEPTION', 'MATCHED'):
                    raise DomainError('Allocations cannot change after affirmation', 409)
                allocations = data.get('allocations')
                if not isinstance(allocations, list) or not 1 <= len(allocations) <= 100:
                    raise DomainError('Provide 1–100 allocations')
                accounts = set()
                for allocation in allocations:
                    if not isinstance(allocation, dict):
                        raise DomainError('Invalid allocation')
                    account = allocation.get('account')
                    if not isinstance(account, str) or not account.strip() or len(account) > 80 or (account in accounts):
                        raise DomainError('Allocation accounts must be unique nonempty strings')
                    accounts.add(account)
                    positive_int(allocation.get('quantity'))
                total = sum((a['quantity'] for a in allocations))
                state = 'MATCHED' if total == trade['quantity'] else 'EXCEPTION'
                reason = None if state == 'MATCHED' else 'Allocation quantity %s differs from broker quantity %s' % (total, trade['quantity'])
                repository.set_legacy_allocation((json.dumps(allocations), state, reason, trade_id))
            elif action == 'affirm':
                if state != 'MATCHED':
                    raise DomainError('Only matched trades can be affirmed', 409)
                instruction = data.get('instruction', '')
                if not isinstance(instruction, str) or not instruction.startswith('SYN-') or len(instruction) > 80:
                    raise DomainError('Provide a synthetic settlement instruction beginning SYN-')
                repository.affirm_trade((instruction, trade_id))
            elif action == 'fund':
                if state not in ('AFFIRMED', 'FAILED'):
                    raise DomainError('Funding is available for affirmed or failed trades', 409)
                cash = data.get('cash_cents')
                securities = data.get('securities')
                if any((isinstance(v, bool) or not isinstance(v, int) or v < 0 or (v > 10 ** 18) for v in (cash, securities))):
                    raise DomainError('Balances must be nonnegative bounded integers')
                repository.set_legacy_balances((cash, securities, trade_id))
            elif action == 'settle':
                if state not in ('AFFIRMED', 'FAILED'):
                    raise DomainError('Only affirmed or failed trades can attempt settlement', 409)
                if trade['settlement_model'] == 'shared-ledger':
                    
                    date_blocks=[b for b in trade['settlement_readiness']['blockers'] if b['code'] in ('NOT_DUE','CALENDAR_CLOSED','INVALID_SETTLEMENT_DAY')]
                    if date_blocks:
                        raise DomainError('Settlement calendar blocked: '+', '.join(b['code'] for b in date_blocks),409)
                    batch = repository.settle(trade, actor)
                    if batch:
                        repository.insert_settlement((trade_id, trade['quantity'], trade['quantity'] * trade['price_cents']))
                        repository.complete_shared_settlement((trade_id,))
                    else:
                        repository.fail_settlement(('Insufficient shared buyer cash or seller securities', trade_id))
                else:
                    amount = trade['quantity'] * trade['price_cents']
                    ready = trade['cash_cents'] >= amount and trade['securities'] >= trade['quantity']
                    if ready:
                        repository.insert_settlement((trade_id, trade['quantity'], amount))
                        repository.complete_legacy_settlement((amount, trade['quantity'], trade_id))
                    else:
                        repository.fail_settlement(('Insufficient simulated cash or securities', trade_id))
            else:
                raise DomainError('Unknown action', 404)
            repository.advance_version((trade_id,))
            updated = self.get(repository, trade_id)
            detail = 'Demo balances provisioned; cash cents: %s, securities: %s' % (data['cash_cents'], data['securities']) if action == 'fund' else updated['reason'] or 'State: ' + updated['state']
            self.event(repository, trade_id, actor, action.upper(), detail)
            return updated

    def snapshot(self):
        with self.store.transaction() as repository:
            trades = [self.get(repository, r['id']) for r in repository.list_trade_ids()]
            audit = [dict(r) for r in repository.list_audit()]
            
            return {'trades': trades, 'audit': audit, 'treasury': repository.treasury_snapshot(), 'business_time':self.clock.describe(), 'calendar':self.calendar.to_dict()}

    def reconcile(self, rows):
        if not isinstance(rows, list) or len(rows) > 10000:
            raise DomainError('Provide a statement array of at most 10,000 rows')
        external = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('trade_id'), str):
                raise DomainError('Each statement row needs a trade_id')
            if row['trade_id'] in external:
                raise DomainError('Duplicate statement trade_id')
            for field in ('quantity', 'amount_cents'):
                if isinstance(row.get(field), bool) or not isinstance(row.get(field), int) or row[field] < 0:
                    raise DomainError('Statement quantities and amounts must be nonnegative integers')
            external[row['trade_id']] = row
        with self.store.transaction() as repository:
            internal = {r['trade_id']: dict(r) for r in repository.list_settlements()}
        breaks = []
        for key in sorted(internal.keys() | external.keys()):
            if key not in external:
                breaks.append({'trade_id': key, 'reason': 'MISSING_EXTERNAL'})
            elif key not in internal:
                breaks.append({'trade_id': key, 'reason': 'MISSING_INTERNAL'})
            elif any((internal[key][f] != external[key][f] for f in ('quantity', 'amount_cents'))):
                breaks.append({'trade_id': key, 'reason': 'VALUE_MISMATCH'})
        return {'status': 'BREAKS' if breaks else 'BALANCED', 'breaks': breaks, 'internal_count': len(internal), 'external_count': len(external)}

    def evidence(self, trade_id, version):
        from ..core.evidence import build_evidence
        with self.store.transaction() as repository:
            trade = self.get(repository, trade_id)
            if isinstance(version, bool) or not isinstance(version, int) or version != trade['version']:
                raise DomainError('Stale or missing version; refresh before analysis', 409)
            events = [dict(r) for r in repository.list_trade_audit((trade_id,))]
            return build_evidence(trade, events)

    def submit_manager(self, trade_id, data, principal=None):
        from ..core.matching import normalize_terms, normalize_allocations, compare
        key = data.get('submission_key')
        if not isinstance(key, str) or not 1 <= len(key) <= 120:
            raise DomainError('Manager submissions require an Idempotency-Key of 1–120 characters')
        manager = normalize_terms(data)
        manager['allocations'] = normalize_allocations(data.get('allocations'))
        fingerprint = json.dumps(manager, sort_keys=True)
        with self.store.transaction() as repository:
            trade = self.get(repository, trade_id)
            actor = 'investment-manager'
            if trade['settlement_model'] == 'shared-ledger':
                from ..core.identity import require
                require(principal, 'maker')
                actor = principal.id
            if trade['matching_mode'] != 'two-sided':
                raise DomainError('Manager submissions require a two-sided trade', 409)
            previous = repository.find_manager_replay((trade_id, key))
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise DomainError('Manager key already used for different terms', 409)
                return json.loads(previous['result'])
            version = data.get('version')
            if isinstance(version, bool) or not isinstance(version, int) or version != trade['version']:
                raise DomainError('Stale or missing version; refresh before submitting', 409)
            if trade['state'] not in ('RECEIVED', 'EXCEPTION', 'MATCHED'):
                raise DomainError('Manager terms are locked after affirmation', 409)
            pending = trade['pending_approval']
            if pending:
                repository.cancel_approval((datetime.now(timezone.utc).isoformat(), 'Manager terms revised; prior approval context invalidated', pending['id']))
                self.event(repository, trade_id, actor, 'APPROVAL_CANCELLED', 'Manager terms changed; a new instruction approval is required')
            report = compare(trade, manager)
            reason = '; '.join((f['message'] for f in report['findings'])) or None
            revision = len(trade['submission_history']) + 1
            timestamp = datetime.now(timezone.utc).isoformat()
            repository.apply_manager_revision((json.dumps(manager['allocations']), json.dumps(report), report['status'], reason, trade_id))
            repository.insert_manager_revision((trade_id, revision, key, fingerprint, json.dumps(manager), timestamp, '{}'))
            self.event(repository, trade_id, actor, 'MANAGER_SUBMITTED', 'Revision %s · %s · %s discrepancy(s) · %s' % (revision, report['status'], len(report['findings']), report['policy']))
            result = self.get(repository, trade_id)
            repository.store_manager_response((json.dumps(result), trade_id, key))
            return result

    def approval_command(self, repository, trade, action, data, principal):
        from ..core.identity import require
        from uuid import uuid4
        trade_id = trade['id']
        if action == 'request-affirmation':
            require(principal, 'maker')
            instruction = data.get('instruction', '')
            if not isinstance(instruction, str) or not instruction.startswith('SYN-') or len(instruction) > 80:
                raise DomainError('Provide a synthetic instruction beginning SYN-')
            key = data.get('request_key')
            if not isinstance(key, str) or not 1 <= len(key) <= 120:
                raise DomainError('Approval request requires an Idempotency-Key')
            fingerprint = json.dumps([instruction, principal.id])
            previous = repository.find_approval_replay((trade_id, key))
            if previous:
                if previous['fingerprint'] != fingerprint:
                    raise DomainError('Approval key conflicts with an earlier request', 409)
                return self.get(repository, trade_id)
        else:
            pending = trade['pending_approval']
            if not pending or data.get('approval_id') != pending['id']:
                raise DomainError('No matching pending approval request', 409)
            if principal is not None and principal.id == pending['maker_id']:
                raise DomainError('A maker cannot approve or reject their own request', 403)
            require(principal, 'checker')
        version = data.get('version')
        if isinstance(version, bool) or not isinstance(version, int) or version != trade['version']:
            raise DomainError('Stale or missing version; refresh the approval context', 409)
        now = datetime.now(timezone.utc).isoformat()
        if action == 'request-affirmation':
            if trade['state'] != 'MATCHED' or trade['pending_approval']:
                raise DomainError('Request requires a matched trade without another pending approval', 409)
            request_id = 'A-' + uuid4().hex[:16].upper()
            repository.insert_approval((request_id, trade_id, principal.id, instruction, 'PENDING', trade['version'] + 1, key, fingerprint, now, None, None, None))
            detail = 'Instruction review requested for matched terms; ' + request_id
            event = 'AFFIRMATION_REQUESTED'
        else:
            if pending['trade_version'] != trade['version'] or trade['state'] != 'MATCHED':
                raise DomainError('Approval no longer refers to current matched terms', 409)
            reason = data.get('reason', '')
            if action == 'reject' and (not isinstance(reason, str) or not 5 <= len(reason.strip()) <= 300):
                raise DomainError('Rejection requires a reason of 5–300 characters')
            if action == 'approve':
                repository.affirm_trade((pending['instruction'], trade_id))
            repository.decide_approval(('APPROVED' if action == 'approve' else 'REJECTED', principal.id, now, reason if action == 'reject' else None, pending['id']))
            detail = 'Instruction request ' + pending['id'] + ' ' + ('approved' if action == 'approve' else 'rejected: ' + reason)
            event = 'AFFIRMATION_APPROVED' if action == 'approve' else 'AFFIRMATION_REJECTED'
        repository.advance_version((trade_id,))
        self.event(repository, trade_id, principal.id, event, detail)
        return self.get(repository, trade_id)

    def fund_participant(self, data, key, principal):
        from ..core.identity import require
        
        require(principal, 'checker')
        with self.store.transaction() as repository:
            result = repository.provision(data, key, principal.id)
            if not result['replayed']:
                self.event(repository, 'TREASURY', principal.id, 'DEMO_FUNDED', data['participant_id'] + ' / ' + data['asset'] + ' / ' + str(data['amount']))
            return result

    def settlement_readiness(self,trade_id):
        with self.store.transaction() as repository:
            return self.get(repository,trade_id)['settlement_readiness']

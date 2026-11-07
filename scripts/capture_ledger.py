"""Record the governed shared-ledger workflow using synthetic data only."""
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime,timezone
from pathlib import Path
from settlementlab.domain import Ledger,DomainError
from settlementlab.identity import Principal
from settlementlab.core.calendar import FixedClock

maker=Principal('maker-alex','maker');checker=Principal('checker-sam','checker')
terms=dict(symbol='NOVA',side='BUY',currency='USD',quantity=100,price='42.75',trade_date='2026-11-06',settlement_date='2026-11-09')
with tempfile.TemporaryDirectory() as temporary:
    ledger=Ledger(Path(temporary)/'capture.db',clock=FixedClock('2026-11-09'))
    def ready(key):
        t=ledger.create(dict(terms,matching_mode='two-sided',settlement_model='shared-ledger'),key,principal=maker)
        t=ledger.command(t['id'],'manager',dict(terms,version=t['version'],submission_key='manager',allocations=[dict(account='SYN-FUND',quantity=100)]),principal=maker)
        return ledger.command(t['id'],'request-affirmation',dict(version=t['version'],request_key='review',instruction='SYN-CUSTODY'),principal=maker)
    pending=ready('first')
    before=ledger.snapshot()
    try:
        ledger.command(pending['id'],'approve',dict(version=pending['version'],approval_id=pending['pending_approval']['id']),principal=maker)
        raise AssertionError('Self-approval was unexpectedly allowed')
    except DomainError as error:
        assert error.status==403
    assert ledger.snapshot()==before
    approved=ledger.command(pending['id'],'approve',dict(version=pending['version'],approval_id=pending['pending_approval']['id']),principal=checker)
    treasury_before=ledger.snapshot()['treasury']
    failed=ledger.command(approved['id'],'settle',dict(version=approved['version']),principal=checker)
    assert failed['state']=='FAILED' and ledger.snapshot()['treasury']==treasury_before
    ledger.fund_participant(dict(participant_id='SYN-ALPHA',asset='CASH:USD',amount=427500),'cash',checker)
    ledger.fund_participant(dict(participant_id='SYN-BROKER',asset='SEC:NOVA',amount=100),'stock',checker)
    settled=ledger.command(failed['id'],'settle',dict(version=failed['version']),principal=checker)
    second=ready('competing')
    second=ledger.command(second['id'],'approve',dict(version=second['version'],approval_id=second['pending_approval']['id']),principal=checker)
    second=ledger.command(second['id'],'settle',dict(version=second['version']),principal=checker)
    assert settled['state']=='SETTLED' and second['state']=='FAILED'
    result=ledger.snapshot()
    batches=[b for b in result['treasury']['batches'] if b['kind']=='DVP_SETTLEMENT']
    assert len(batches)==1 and len(batches[0]['lines'])==4
    assert result['treasury']['controls']['status']=='BALANCED'
    record=dict(version='2.2.0',generated_at=datetime.now(timezone.utc).isoformat(),origin='recorded-local-execution',
                source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),source_state='working-tree',
                source_hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('src/settlementlab').glob('*.py')},
                model_calls=0,identity_scope='Freely switchable demo personas; not production authentication',
                pending=pending,approved=approved,failed=failed,settled=settled,competing_trade=second,
                treasury=result['treasury'],audit=result['audit'],
                checks=dict(self_approval_rejected=True,failed_settlement_left_balances_unchanged=True,
                            four_balanced_settlement_lines=True,shared_cash_not_spent_twice=True,
                            journal_projection_consistent=True))
    path=Path('docs/evidence/shared-ledger-v22.json');path.write_text(json.dumps(record,indent=2)+'\n')
    print(path);print(json.dumps(record['checks']))

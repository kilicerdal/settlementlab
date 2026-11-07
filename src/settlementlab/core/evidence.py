"""Bounded, transport-independent investigation facts."""
import json

def build_evidence(trade, events):
    # Deliberately exclude free-form accounts, instructions, request keys and actor names.
    facts = {
        "state": trade["state"],
        "broker_quantity": trade["quantity"],
        "allocation_total": sum(a["quantity"] for a in json.loads(trade["allocations"])),
        "required_cash_cents": trade["quantity"] * trade["price_cents"],
        "available_cash_cents": trade["cash_cents"],
        "required_securities": trade["quantity"],
        "available_securities": trade["securities"],
    }
    if trade["state"] in ("RECEIVED", "EXCEPTION", "MATCHED"):
        facts = {name: facts[name] for name in ("state", "broker_quantity", "allocation_total")}
    if trade.get('settlement_model')=='shared-ledger':
        facts['balance_source']='Shared participant ledger; buyer cash and seller securities'
        facts['approval_status']='PENDING' if trade.get('pending_approval') else ('APPROVED' if trade['state'] in ('AFFIRMED','FAILED','SETTLED') else 'NOT_APPROVED')
    matching = trade.get('matching', {})
    if trade.get('matching_mode') == 'two-sided':
        from .matching import policy_description
        policy = policy_description()
        if trade['state'] in ('RECEIVED','EXCEPTION','MATCHED'):
            facts = {'state': trade['state']}
        active_rules = {finding['rule_id'] for finding in matching.get('findings', [])}
        facts['matching_policy'] = dict(id=policy['id'],
            rules=[rule for rule in policy['rules'] if rule['id'] in active_rules])
    evidence_facts = [{"id": "fact:"+name, "name": name, "value": value} for name,value in facts.items()]
    for finding in matching.get('findings', []):
        evidence_facts.append(dict(id='break:'+finding['field'], name=finding['code'],
                                   value={key:finding[key] for key in ('expected','observed','rule_id')}))
    return {
        "trade_id": trade["id"], "trade_version": trade["version"],
        "facts": evidence_facts,
        "events": [{"id": "event:"+str(e["seq"]), "action": e["action"]} for e in events[-20:]],
    }


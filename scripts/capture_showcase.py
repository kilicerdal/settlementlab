"""Capture genuine deterministic execution, without model calls or credentials."""
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from settlementlab.domain import Ledger

stages=[]
with tempfile.TemporaryDirectory() as temporary:
    ledger=Ledger(Path(temporary)/'capture.db')
    t=ledger.create(dict(symbol='NOVA',quantity=10000,price='42.75',trade_date='2026-11-06'),'recorded-showcase')
    def record(label):
        stages.append(dict(label=label,state=t['state'],version=t['version'],quantity=t['quantity'],
            allocation_total=sum(a['quantity'] for a in json.loads(t['allocations'])),
            cash_cents=t['cash_cents'],securities=t['securities'],reason=t['reason']))
    record('Broker submission')
    for label,action,data in [
        ('Allocation break','allocate',dict(allocations=[dict(account='SYN-ALPHA',quantity=9900)])),
        ('Allocation corrected','allocate',dict(allocations=[dict(account='SYN-ALPHA',quantity=10000)])),
        ('Instruction affirmed','affirm',dict(instruction='SYN-CUSTODY-USD')),
        ('Settlement failed','settle',{}),
        ('Balances provisioned','fund',dict(cash_cents=42750000,securities=10000)),
        ('Settlement completed','settle',{}),
    ]:
        t=ledger.command(t['id'],action,dict(version=t['version'],**data));record(label)
    result=ledger.reconcile([dict(trade_id=t['id'],quantity=10000,amount_cents=42750000)])
    assert result['status']=='BALANCED'
    assert [s['state'] for s in stages]==['RECEIVED','EXCEPTION','MATCHED','AFFIRMED','FAILED','FAILED','SETTLED']
    evidence=dict(generated_at=datetime.now(timezone.utc).isoformat(),
        source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        origin='recorded-local-domain-execution',model_calls=0,
        symbol='NOVA',price_cents=4275,notional_cents=42750000,stages=stages,
        reconciliation=result,audit=ledger.snapshot()['audit'])
    destination=Path('docs/evidence/settlement-journey.json')
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(evidence,indent=2)+'\n')
    print('Recorded seven lifecycle stages and balanced reconciliation:',destination)

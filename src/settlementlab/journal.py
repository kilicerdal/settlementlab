"""Balanced multi-asset journals and shared participant balance projections."""
import json
from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4
from .validation import DomainError

LIMIT = 10**15
RESERVE = 'SYN-RESERVE'
PARTICIPANTS = [('SYN-ALPHA','Alpha Investment Manager'), ('SYN-BROKER','Synthetic Broker'),
                ('SYN-BETA','Beta Investment Manager'), (RESERVE,'Synthetic funding reserve')]


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS participants(id TEXT PRIMARY KEY, name TEXT NOT NULL)')
    db.executemany('INSERT OR IGNORE INTO participants VALUES (?,?)', PARTICIPANTS)
    db.execute('''CREATE TABLE IF NOT EXISTS balances (
      participant_id TEXT NOT NULL REFERENCES participants(id),asset TEXT NOT NULL,balance INTEGER NOT NULL,
      PRIMARY KEY(participant_id,asset),CHECK(balance BETWEEN -1000000000000000 AND 1000000000000000),
      CHECK(balance>=0 OR participant_id='SYN-RESERVE'))''')
    db.execute('''CREATE TABLE IF NOT EXISTS journal_batches (
      id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,fingerprint TEXT NOT NULL,
      kind TEXT NOT NULL,trade_id TEXT UNIQUE REFERENCES trades(id),actor TEXT NOT NULL,timestamp TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS journal_lines (
      batch_id TEXT NOT NULL REFERENCES journal_batches(id),line INTEGER NOT NULL,
      participant_id TEXT NOT NULL REFERENCES participants(id),asset TEXT NOT NULL,delta INTEGER NOT NULL,
      PRIMARY KEY(batch_id,line))''')


def balance(db, participant, asset):
    row = db.execute('SELECT balance FROM balances WHERE participant_id=? AND asset=?',(participant,asset)).fetchone()
    return row['balance'] if row else 0


def participant(db, value):
    if not isinstance(value,str) or value == RESERVE or not db.execute('SELECT 1 FROM participants WHERE id=?',(value,)).fetchone():
        raise DomainError('Choose a known synthetic trading participant')
    return value


def asset(value):
    if value == 'CASH:USD':
        return value
    if isinstance(value,str) and value.startswith('SEC:'):
        symbol=value[4:]
        if symbol.isascii() and symbol.isalnum() and symbol.upper()==symbol and 1 <= len(symbol) <= 12:
            return value
    raise DomainError('Asset must be CASH:USD or SEC:<uppercase symbol>')


def post(db, key, kind, lines, actor, trade_id=None):
    """Caller owns the write transaction; validate entire batch before writes."""
    if snapshot(db)['controls']['status']!='BALANCED':
        raise DomainError('Ledger integrity check failed; investigate before posting',409)
    if len(lines) < 2:
        raise DomainError('Journal requires balanced posting lines')
    totals=defaultdict(int)
    changes=defaultdict(int)
    for party,unit,delta in lines:
        if not isinstance(delta,int) or isinstance(delta,bool) or not -LIMIT <= delta <= LIMIT or delta == 0:
            raise DomainError('Journal deltas must be nonzero bounded integers')
        asset(unit)
        if not db.execute('SELECT 1 FROM participants WHERE id=?',(party,)).fetchone():
            raise DomainError('Unknown posting participant')
        totals[unit]+=delta
        changes[(party,unit)]+=delta
    if any(totals.values()):
        raise DomainError('Journal must balance independently for every asset')
    projected={pair:balance(db,*pair)+delta for pair,delta in changes.items()}
    if any(abs(value)>LIMIT or (pair[0]!=RESERVE and value<0) for pair,value in projected.items()):
        raise DomainError('Insufficient balance or balance limit exceeded',409)
    fingerprint=json.dumps([kind,trade_id,lines],separators=(',',':'))
    existing=db.execute('SELECT id,fingerprint FROM journal_batches WHERE request_key=?',(key,)).fetchone()
    if existing:
        if existing['fingerprint'] != fingerprint:
            raise DomainError('Funding key already used for a different transfer',409)
        return existing['id']
    batch='J-'+uuid4().hex[:16].upper()
    db.execute('INSERT INTO journal_batches VALUES (?,?,?,?,?,?,?)',
               (batch,key,fingerprint,kind,trade_id,actor,datetime.now(timezone.utc).isoformat()))
    for pair,value in projected.items():
        db.execute('INSERT INTO balances VALUES (?,?,?) ON CONFLICT(participant_id,asset) DO UPDATE SET balance=excluded.balance',(*pair,value))
    db.executemany('INSERT INTO journal_lines VALUES (?,?,?,?,?)',
                   [(batch,index,party,unit,delta) for index,(party,unit,delta) in enumerate(lines,1)])
    return batch


def provision(db, data, key, actor):
    if not isinstance(key,str) or not 1 <= len(key) <= 120:
        raise DomainError('Funding requires an Idempotency-Key')
    party=participant(db,data.get('participant_id'))
    unit=asset(data.get('asset'))
    amount=data.get('amount')
    if isinstance(amount,bool) or not isinstance(amount,int) or not 0 < amount <= LIMIT:
        raise DomainError('Funding amount must be a positive bounded integer')
    # Replay is checked before balance limits so a successful replay never fails
    # merely because later transfers changed available funds.
    request='funding:'+key
    lines=[(RESERVE,unit,-amount),(party,unit,amount)]
    fingerprint=json.dumps(['DEMO_FUNDING',None,lines],separators=(',',':'))
    previous=db.execute('SELECT id,fingerprint FROM journal_batches WHERE request_key=?',(request,)).fetchone()
    if previous:
        if previous['fingerprint']!=fingerprint:
            raise DomainError('Funding key already used for a different transfer',409)
        return dict(batch_id=previous['id'],replayed=True)
    return dict(batch_id=post(db,request,'DEMO_FUNDING',lines,actor),replayed=False)


def settle(db, trade, actor):
    amount=trade['quantity']*trade['price_cents']
    buyer,seller=trade['buyer_id'],trade['seller_id']
    unit='SEC:'+trade['symbol']
    if balance(db,buyer,'CASH:USD')<amount or balance(db,seller,unit)<trade['quantity']:
        return None
    return post(db,'settlement:'+trade['id'],'DVP_SETTLEMENT',[
        (buyer,'CASH:USD',-amount),(seller,'CASH:USD',amount),
        (seller,unit,-trade['quantity']),(buyer,unit,trade['quantity']),
    ],actor,trade['id'])


def snapshot(db):
    parties=[dict(row) for row in db.execute('SELECT * FROM participants ORDER BY id')]
    accounts=[dict(row) for row in db.execute('SELECT * FROM balances ORDER BY participant_id,asset')]
    batches=[]
    # Python integers intentionally avoid SQLite SUM overflow on long histories.
    all_lines=[dict(row) for row in db.execute('SELECT * FROM journal_lines')]
    projected=defaultdict(int)
    per_batch=defaultdict(lambda:defaultdict(int))
    for line in all_lines:
        projected[(line['participant_id'],line['asset'])]+=line['delta']
        per_batch[line['batch_id']][line['asset']]+=line['delta']
    actual={(row['participant_id'],row['asset']):row['balance'] for row in accounts}
    balanced=all(not any(totals.values()) for totals in per_batch.values())
    consistent=all(projected.get(pair,0)==actual.get(pair,0) for pair in projected.keys()|actual.keys())
    for row in db.execute('SELECT * FROM journal_batches ORDER BY timestamp DESC LIMIT 50'):
        item=dict(row)
        item.pop('fingerprint')
        item['lines']=[line for line in all_lines if line['batch_id']==row['id']]
        batches.append(item)
    return dict(participants=parties,balances=accounts,batches=batches,
                controls=dict(balanced_batches=balanced,projection_consistent=consistent,
                              status='BALANCED' if balanced and consistent else 'BREAKS'))

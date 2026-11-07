'use strict';
const $ = id => document.getElementById(id);
const money = cents => new Intl.NumberFormat('en-US', {style:'currency',currency:'USD'}).format(cents / 100);
let snapshot = {trades:[],audit:[]}, selected;
function node(tag, text, cls) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; }
async function api(path, body, key) {
  const response=await fetch(path, body===undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json',...(key?{'Idempotency-Key':key}:{})},body:JSON.stringify(body)});
  const data=await response.json(); if(!response.ok)throw Error(data.error || 'Request failed'); return data;
}
function announce(text) { $('message').textContent=text; }
async function refresh(){ snapshot=await api('/api/snapshot'); render(); }
function render(){
  $('total').textContent=snapshot.trades.length;
  $('exceptions').textContent=snapshot.trades.filter(t=>['EXCEPTION','FAILED'].includes(t.state)).length;
  $('notional').textContent=money(snapshot.trades.filter(t=>t.state==='SETTLED').reduce((n,t)=>n+t.quantity*t.price_cents,0));
  $('trades').replaceChildren();
  if(!snapshot.trades.length){const row=node('tr');const cell=node('td','Your ledger is ready. Run the showcase scenario to begin.');cell.colSpan=6;row.append(cell);$('trades').append(row);}
  for(const t of snapshot.trades){ const row=node('tr');const id=node('td',t.id);id.append(node('small',t.symbol+' · USD'));row.append(id,node('td',t.quantity.toLocaleString()),node('td',money(t.quantity*t.price_cents)),node('td',t.settlement_date));const state=node('td');state.append(node('span',t.state,'badge '+t.state));row.append(state);const action=node('td');const b=node('button','Inspect ↗','secondary');b.onclick=()=>{selected=t.id;renderDetail();};action.append(b);row.append(action);$('trades').append(row); }
  $('audit').replaceChildren();for(const e of snapshot.audit.slice(0,8)){const el=node('div',undefined,'event');el.append(node('strong',e.trade_id+' / '+e.action.replaceAll('_',' ')),node('p',e.detail),node('small',new Date(e.timestamp).toLocaleString()+' · '+e.actor));$('audit').append(el);}
  if(!snapshot.audit.length)$('audit').append(node('p','Lifecycle events will appear here.'));
  renderDetail();
}
function renderDetail(){
  const t=snapshot.trades.find(t=>t.id===selected);if(!t)return;
  const box=$('detail');box.replaceChildren(node('div','TRADE INSPECTOR','eyebrow'),node('h2',t.id+' · '+t.symbol),node('span',t.state,'badge '+t.state));
  box.append(node('p',t.reason || 'Version '+t.version+' · '+t.quantity.toLocaleString()+' shares at '+money(t.price_cents)));
  box.append(node('pre','Allocation: '+JSON.parse(t.allocations).map(a=>a.account+' / '+a.quantity).join(', ')+'\nInstruction: '+(t.instruction||'Pending')+'\nAvailable cash: '+money(t.cash_cents)+'\nAvailable securities: '+t.securities));
  const actions=node('div',undefined,'actions');
  function add(label,action,data){const b=node('button',label,'secondary');b.onclick=async()=>{b.disabled=true;try{await api('/api/trades/'+t.id+'/'+action,{version:t.version,...data});await refresh();announce('Trade updated: '+action);}catch(e){announce(e.message);b.disabled=false;}};actions.append(b);}
  if(['RECEIVED','EXCEPTION','MATCHED'].includes(t.state))add('Match full allocation','allocate',{allocations:[{account:'SYN-FUND-ALPHA',quantity:t.quantity}]});
  if(t.state==='MATCHED')add('Affirm instructions','affirm',{instruction:'SYN-CUSTODY-USD-001'});
  if(['AFFIRMED','FAILED'].includes(t.state)){add('Provision demo balances','fund',{cash_cents:t.quantity*t.price_cents,securities:t.quantity});add('Attempt settlement','settle',{});}
  if(t.state==='SETTLED'){const b=node('button','Reconcile statement','secondary');b.onclick=async()=>{try{const statement=snapshot.trades.filter(x=>x.state==='SETTLED').map(x=>({trade_id:x.id,quantity:x.quantity,amount_cents:x.quantity*x.price_cents}));const r=await api('/api/reconcile',{statement});announce('Reconciliation: '+r.status+' · '+r.internal_count+' settled trades checked against a synthetic matching statement.');}catch(e){announce(e.message);}};actions.append(b);}
  box.append(actions);
}
$('refresh').onclick=()=>refresh().catch(e=>announce(e.message));
$('demo').onclick=async()=>{
  $('demo').disabled=true;
  try{
    const key='showcase-'+Date.now();let t=await api('/api/trades',{symbol:'NOVA',quantity:10000,price:'42.75',trade_date:new Date().toISOString().slice(0,10)},key);
    t=await api('/api/trades/'+t.id+'/allocate',{version:t.version,allocations:[{account:'SYN-FUND-ALPHA',quantity:9900}]});
    selected=t.id;await refresh();announce('Quantity mismatch detected. Inspect the trade to correct it, affirm, and simulate settlement.');
  }catch(e){announce(e.message);}finally{$('demo').disabled=false;}
};
refresh().catch(e=>announce(e.message));

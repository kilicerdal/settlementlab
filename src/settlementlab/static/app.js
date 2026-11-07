'use strict';
const $ = id => document.getElementById(id);
const money = cents => {
  if(typeof cents==='number'&&!Number.isSafeInteger(cents))return 'Outside browser precision range';
  const value=BigInt(cents),negative=value<0n,absolute=negative?-value:value;
  return (negative?'-':'')+'$'+new Intl.NumberFormat('en-US').format(absolute/100n)+'.'+String(absolute%100n).padStart(2,'0');
};
const fields=[['symbol','Security'],['side','Economic side'],['quantity','Quantity'],['price_cents','Price'],['currency','Currency'],['trade_date','Trade date'],['settlement_date','Settlement date']];
let snapshot={trades:[],audit:[],treasury:{}}, selected, formContext, principal, fundingKey;
const can=role=>principal?.role===role;
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
async function api(path,body,key){
  const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json',...(key?{'Idempotency-Key':key}:{})},body:JSON.stringify(body)});
  const data=await response.json();if(!response.ok){const error=Error(data.error||'Request failed');error.status=response.status;throw error;}return data;
}
function announce(text){$('message').textContent=text;}
async function refresh(){snapshot=await api('/api/snapshot');render();}
function selectedTrade(){return snapshot.trades.find(t=>t.id===selected);}
function display(field,value,currency='USD'){if(value===undefined||value===null)return 'Not submitted';return field==='price_cents'?new Intl.NumberFormat('en-US',{style:'currency',currency}).format(value/100):typeof value==='number'?value.toLocaleString():value;}
function render(){
  $('total').textContent=snapshot.trades.length;
  $('exceptions').textContent=snapshot.trades.filter(t=>['EXCEPTION','FAILED'].includes(t.state)).length;
  $('notional').textContent=money(snapshot.trades.filter(t=>t.state==='SETTLED').reduce((n,t)=>n+BigInt(t.quantity)*BigInt(t.price_cents),0n));
  $('pending').textContent=snapshot.trades.filter(t=>t.matching_mode==='two-sided'&&!t.manager_submission).length;
  $('new-trade').disabled=!can('maker');$('demo').disabled=!can('maker');
  $('open-funding').disabled=!can('checker');
  $('open-funding').title=can('checker')?'Post a synthetic reserve transfer':'Switch to the checker demo identity';
  renderTreasury();renderTrades();renderDetail();renderAudit();
}
function renderTreasury(){
  const treasury=snapshot.treasury;if(!treasury?.participants)return;
  $('ledger-status').textContent=treasury.controls.status;
  $('participant-balances').replaceChildren();
  for(const party of treasury.participants.filter(p=>p.id!=='SYN-RESERVE')){
    const card=node('article',undefined,'participant-card');card.append(node('small',party.id),node('h3',party.name));
    const balances=treasury.balances.filter(b=>b.participant_id===party.id);
    const cash=balances.find(b=>b.asset==='CASH:USD')?.balance||0;card.append(node('strong',money(cash)),node('small','Shared USD cash'));
    for(const b of balances.filter(b=>b.asset.startsWith('SEC:')))card.append(node('p',b.asset.slice(4)+' · '+b.balance.toLocaleString()+' shares'));
    if(!balances.some(b=>b.asset.startsWith('SEC:')))card.append(node('p','No securities inventory'));
    $('participant-balances').append(card);
  }
  $('journal-entries').replaceChildren();
  for(const batch of treasury.batches){
    const detail=node('details',undefined,'journal-batch');detail.append(node('summary',batch.kind.replaceAll('_',' ')+' · '+(batch.trade_id||'Reserve transfer')+' · '+batch.id),node('p',batch.actor+' · '+new Date(batch.timestamp).toLocaleString()));
    const pre=node('pre',batch.lines.map(line=>line.participant_id+' / '+line.asset+' / '+(line.delta>0?'+':'')+(line.asset==='CASH:USD'?money(line.delta):line.delta.toLocaleString()+' shares')).join('\n'));detail.append(pre);$('journal-entries').append(detail);
  }
  if(!treasury.batches.length)$('journal-entries').append(node('p','Balanced reserve and settlement postings will appear here.'));
}
function renderTrades(){
  const search=$('search').value.trim().toUpperCase(),state=$('state-filter').value;
  const trades=snapshot.trades.filter(t=>(!state||t.state===state)&&(!search||(t.id+' '+t.symbol).includes(search)));
  $('result-count').textContent=trades.length+' of '+snapshot.trades.length+' trades';$('trades').replaceChildren();
  if(!trades.length){const row=node('tr'),cell=node('td',snapshot.trades.length?'No trades match your filters.':'Your ledger is ready. Submit a broker trade or run the showcase.');cell.colSpan=6;row.append(cell);$('trades').append(row);}
  for(const t of trades){
    const row=node('tr',undefined,t.id===selected?'selected-row':'');const id=node('td',t.id);id.append(node('small',t.symbol+' · '+t.side+' · '+t.currency));
    row.append(id,node('td',t.quantity.toLocaleString()),node('td',money(t.quantity*t.price_cents)),node('td',t.settlement_date));
    const stateCell=node('td');stateCell.append(node('span',t.state,'badge '+t.state));
    if(t.matching?.findings?.length)stateCell.append(node('small',t.matching.findings.length+' field break(s)'));
    const action=node('td'),b=node('button','Inspect ↗','secondary');b.setAttribute('aria-label','Inspect '+t.id);
    b.onclick=()=>{selected=t.id;render();$('detail').scrollIntoView({behavior:'smooth',block:'start'});};action.append(b);row.append(stateCell,action);$('trades').append(row);
  }
}
function renderAudit(){
  const t=selectedTrade();$('audit-scope').textContent=t?'Events for '+t.id:'Most recent workspace events';
  $('audit').replaceChildren();for(const e of snapshot.audit.filter(e=>!t||e.trade_id===t.id).slice(0,15)){
    const el=node('div',undefined,'event');el.append(node('strong',e.action.replaceAll('_',' ')),node('p',e.detail),node('small','#'+e.seq+' · '+new Date(e.timestamp).toLocaleString()+' · '+e.actor));$('audit').append(el);
  }
  if(!$('audit').children.length)$('audit').append(node('p','Lifecycle events will appear here.'));
}
function renderComparison(box,t){
  const report=t.matching||{},manager=t.manager_submission;
  const header=node('div',undefined,'comparison-heading');header.append(node('h3','Independent trade terms'),node('small',report.policy||'Awaiting manager submission'));box.append(header);
  const wrap=node('div',undefined,'table-wrap'),table=node('table',undefined,'comparison-table'),head=node('thead'),hr=node('tr');
  for(const label of ['FIELD','BROKER','MANAGER','RESULT'])hr.append(node('th',label));head.append(hr);table.append(head);const body=node('tbody');
  for(const [field,label] of fields){const finding=report.findings?.find(f=>f.field===field);const row=node('tr',undefined,finding?'field-break':'');row.append(node('td',label),node('td',display(field,t[field])),node('td',display(field,manager?.[field],manager?.currency)),node('td',!manager?'Pending':finding?'Mismatch':'Agreed',finding?'break-label':'agree-label'));body.append(row);}
  if(manager){const total=manager.allocations.reduce((n,a)=>n+a.quantity,0),finding=report.findings?.find(f=>f.field==='allocation_total'),row=node('tr',undefined,finding?'field-break':'');row.append(node('td','Allocation total'),node('td',display('quantity',manager.quantity)+' expected'),node('td',display('quantity',total)),node('td',finding?'Mismatch':'Agreed',finding?'break-label':'agree-label'));body.append(row);}
  table.append(body);wrap.append(table);box.append(wrap);
  if(report.findings?.length){const findings=node('div',undefined,'findings');for(const f of report.findings){const card=node('div',undefined,'finding');card.append(node('strong',f.code.replaceAll('_',' ')),node('p',f.message),node('small',f.rule_id));findings.append(card);}box.append(findings);}
  if(t.submission_history.length){const history=node('details',undefined,'revision-history');history.append(node('summary','Manager submission history · '+t.submission_history.length+' revision(s)'));for(const revision of t.submission_history){const r=node('p','Revision '+revision.revision+' · '+new Date(revision.timestamp).toLocaleString()+' · '+display('price_cents',revision.terms.price_cents,revision.terms.currency)+' · '+revision.terms.quantity.toLocaleString()+' shares');history.append(r);}box.append(history);}
}
function renderDetail(){
  const t=selectedTrade();if(!t)return;
  const box=$('detail');box.replaceChildren(node('div','MATCHING WORKSPACE / '+(t.matching_mode==='two-sided'?'INDEPENDENT TERMS':'LEGACY ALLOCATION MODE'),'eyebrow'));
  const heading=node('div',undefined,'section-title');heading.append(node('h2',t.id+' · '+t.symbol),node('span',t.state,'badge '+t.state));box.append(heading);
  const stages=node('div',undefined,'lifecycle-rail');const stage=['EXCEPTION','MATCHED'].includes(t.state)?'MATCHING':t.state==='FAILED'?'SETTLEMENT':t.state==='SETTLED'?'SETTLEMENT':t.state;for(const label of ['RECEIVED','MATCHING','AFFIRMED','SETTLEMENT'])stages.append(node('span',label,stage===label?'current':''));box.append(stages);
  box.append(node('p',t.reason||'Version '+t.version+' · '+t.quantity.toLocaleString()+' shares at '+money(t.price_cents)));
  if(t.matching_mode==='two-sided')renderComparison(box,t);
  const shared=t.settlement_model==='shared-ledger';
  if(shared){
    box.append(node('p','Shared settlement · Buyer '+t.buyer_id+' / Seller '+t.seller_id,'participant-pair'));
    const approval=node('div',undefined,'approval-card');
    if(t.pending_approval){approval.append(node('strong','CHECKER REVIEW PENDING'),node('p','Requested by '+t.pending_approval.maker_id+' · '+t.pending_approval.instruction),node('small','Terms version '+t.pending_approval.trade_version+' · '+t.pending_approval.id));}
    else approval.append(node('strong',t.state==='AFFIRMED'||t.state==='FAILED'||t.state==='SETTLED'?'INSTRUCTIONS APPROVED':'INSTRUCTIONS NOT YET APPROVED'),node('p','Maker requests review; a different checker identity approves the current matched terms.'));
    box.append(approval);
    if(t.approval_history.length){const history=node('details',undefined,'revision-history');history.append(node('summary','Instruction approval history · '+t.approval_history.length));for(const a of t.approval_history)history.append(node('p',a.status+' · Maker '+a.maker_id+' · '+(a.decided_by||'Awaiting checker')+(a.reason?' · '+a.reason:'')));box.append(history);}
  }
  box.append(node('pre','Instruction: '+(t.instruction||'Pending')+'\n'+(shared?'Buyer shared cash: ':'Available cash: ')+money(t.cash_cents)+'\n'+(shared?'Seller shared securities: ':'Available securities: ')+t.securities+(t.settlement_journal?'\nSettlement journal: '+t.settlement_journal:'')));
  const actions=node('div',undefined,'actions');
  function add(label,action,data,role,key){const b=node('button',label,'secondary');b.disabled=!!role&&!can(role);if(b.disabled)b.title='Switch to the '+role+' demo identity';b.onclick=async()=>{b.disabled=true;try{await api('/api/trades/'+t.id+'/'+action,{version:t.version,...data},key);await refresh();announce('Trade updated: '+action);}catch(e){announce(e.message);b.disabled=false;}};actions.append(b);}
  if(['RECEIVED','EXCEPTION','MATCHED'].includes(t.state)){
    if(t.matching_mode==='two-sided'){const b=node('button',t.manager_submission?'Revise manager submission':'Submit manager terms');b.disabled=shared&&!can('maker');b.onclick=()=>openSubmission(t);actions.append(b);}
    else add('Match full allocation','allocate',{allocations:[{account:'SYN-FUND-ALPHA',quantity:t.quantity}]});
  }
  if(t.state==='MATCHED'){
    if(shared){
      if(!t.pending_approval)add('Request instruction approval','request-affirmation',{instruction:'SYN-CUSTODY-USD-001'},'maker',crypto.randomUUID());
      else{
        add('Approve instructions','approve',{approval_id:t.pending_approval.id},'checker');
        if(can('checker')){const label=node('label','Rejection reason','rejection-label'),input=node('input');input.placeholder='Why should the instructions be revised?';label.append(input);box.append(label);const reject=node('button','Reject instructions','secondary');reject.onclick=async()=>{try{await api('/api/trades/'+t.id+'/reject',{version:t.version,approval_id:t.pending_approval.id,reason:input.value});await refresh();announce('Instruction request rejected with reason.');}catch(e){announce(e.message);}};actions.append(reject);}
      }
    }else add('Affirm instructions','affirm',{instruction:'SYN-CUSTODY-USD-001'});
  }
  if(['AFFIRMED','FAILED'].includes(t.state)){
    if(shared){
      const plan=[{participant_id:t.buyer_id,asset:'CASH:USD',amount:Math.max(0,t.quantity*t.price_cents-t.cash_cents),key:crypto.randomUUID()},
                  {participant_id:t.seller_id,asset:'SEC:'+t.symbol,amount:Math.max(0,t.quantity-t.securities),key:crypto.randomUUID()}].filter(x=>x.amount>0);
      const fund=node('button','Fund shared shortfalls','secondary');fund.disabled=!can('checker')||!plan.length;
      fund.onclick=async()=>{fund.disabled=true;try{for(const transfer of plan)await api('/api/treasury/fund',transfer,transfer.key);await refresh();announce('Synthetic reserve transfers posted to shared participants.');}catch(e){announce(e.message+' Any completed transfer remains recorded; retry uses the same keys.');fund.disabled=false;}};actions.append(fund);
    }else if(Number.isSafeInteger(t.quantity*t.price_cents))add('Provision demo balances','fund',{cash_cents:t.quantity*t.price_cents,securities:t.quantity});
    add('Attempt settlement','settle',{},shared?'checker':null);
  }
  if(t.state==='SETTLED'){const b=node('button','Reconcile statement','secondary');b.onclick=async()=>{try{const statement=snapshot.trades.filter(x=>x.state==='SETTLED').map(x=>({trade_id:x.id,quantity:x.quantity,amount_cents:x.quantity*x.price_cents}));const r=await api('/api/reconcile',{statement});announce('Reconciliation: '+r.status+' · '+r.internal_count+' settled trades checked against a synthetic matching statement.');}catch(e){announce(e.message);}};actions.append(b);}
  if(['EXCEPTION','FAILED'].includes(t.state)){
    const b=node('button','Analyze exception with AI','secondary');b.onclick=()=>analyze(t,box,b);actions.append(b);
  }
  box.append(actions,node('p','Local simulation. AI is advisory. Demo personas are freely switchable and do not authenticate human operators.','ai-note'));
}
async function analyze(t,box,button){
  button.disabled=true;button.textContent='Analyzing evidence…';box.querySelector('.ai-report')?.remove();
  const report=node('div',undefined,'ai-report');report.setAttribute('role','status');box.append(report);
  try{
    const r=await api('/api/trades/'+t.id+'/analyze',{version:t.version});
    report.append(node('h3','AI analysis · advisory only'),node('small',r.provider+' / '+r.model+' · '+r.prompt_version+' · trade version '+r.trade_version));
    for(const [label,key] of [['Summary','summary'],['Likely cause','likely_cause'],['Next investigation','next_step'],['Uncertainty','uncertainty']])report.append(node('h4',label),node('p',r.analysis[key]));
    report.append(node('small','Evidence: '+r.analysis.evidence_ids.join(', ')));
  }catch(e){report.append(node('p',e.message));}finally{button.disabled=false;button.textContent='Analyze exception with AI';}
}
function setFormTerms(terms){const form=$('submission-form');for(const [field]of fields){const input=field==='price_cents'?'price':field;form.elements[input].value=field==='price_cents'?(terms.price_cents/100).toFixed(2):(terms[field]??'');}}
function openSubmission(trade){
  formContext={trade,key:crypto.randomUUID()};const form=$('submission-form');form.reset();$('form-error').textContent='';
  $('form-title').textContent=trade?'Submit manager terms':'Submit broker trade';$('form-kicker').textContent=trade?'INVESTMENT MANAGER / '+trade.id:'BROKER / NEW TRADE';
  $('party-fields').hidden=!!trade;
  $('allocation-fields').hidden=!trade;$('copy-broker').hidden=!trade;form.elements.allocation_lines.required=!!trade;
  $('form-note').textContent=trade?'Supply the manager’s complete terms. Submitting a correction preserves earlier revisions and reruns the exact-match policy.':'Create the broker record. It remains pending until independently submitted manager terms arrive. V2.1 supports USD broker trades.';
  if(trade?.manager_submission){setFormTerms(trade.manager_submission);form.elements.allocation_lines.value=trade.manager_submission.allocations.map(a=>a.account+','+a.quantity).join('\n');}
  $('submission-dialog').showModal();
}
$('copy-broker').onclick=()=>{const t=formContext.trade;setFormTerms(t);$('submission-form').elements.allocation_lines.value='SYN-FUND-ALPHA,'+t.quantity; $('form-note').textContent='Broker terms copied for review. Confirm the manager agreement before submitting; no trade has been changed.';};
$('new-trade').onclick=()=>openSubmission(null);$('close-dialog').onclick=()=>$('submission-dialog').close();
$('submission-form').onsubmit=async event=>{
  event.preventDefault();const form=event.currentTarget,values=new FormData(form),trade=formContext.trade;
  const data=Object.fromEntries(fields.map(([f])=>{const name=f==='price_cents'?'price':f;return[name,values.get(name)];}));data.quantity=Number(data.quantity);
  const b=$('submit-form');b.disabled=true;$('form-error').textContent='';
  try{
    let result;
    if(trade){data.version=trade.version;data.allocations=String(values.get('allocation_lines')).trim().split('\n').map(line=>{const parts=line.split(',');if(parts.length!==2||!/^\d+$/.test(parts[1].trim()))throw Error('Each allocation needs an account and integer quantity, separated by one comma.');return{account:parts[0].trim(),quantity:Number(parts[1])};});result=await api('/api/trades/'+trade.id+'/manager',data,formContext.key);}
    else result=await api('/api/trades',{...data,matching_mode:'two-sided',settlement_model:'shared-ledger',manager_id:values.get('manager_id'),broker_id:values.get('broker_id')},formContext.key);
    selected=result.id;await refresh();$('submission-dialog').close();announce(trade?'Manager submission recorded; status: '+result.state:'Broker trade recorded. Awaiting independent manager terms.');
  }catch(e){$('form-error').textContent=e.message;}finally{b.disabled=false;}
};
$('search').oninput=renderTrades;$('state-filter').onchange=renderTrades;$('refresh').onclick=()=>refresh().catch(e=>announce(e.message));
$('demo').onclick=async()=>{
  $('demo').disabled=true;
  try{
    const terms={symbol:'NOVA',side:'BUY',quantity:10000,price:'42.75',currency:'USD',trade_date:'2026-11-06',settlement_date:'2026-11-09'};
    let t=await api('/api/trades',{...terms,matching_mode:'two-sided',settlement_model:'shared-ledger'},crypto.randomUUID());
    t=await api('/api/trades/'+t.id+'/manager',{...terms,price:'42.80',version:t.version,allocations:[{account:'SYN-FUND-ALPHA',quantity:6000},{account:'SYN-FUND-BETA',quantity:3900}]},crypto.randomUUID());
    selected=t.id;await refresh();announce('Two independent submissions recorded. Investigate the price and allocation breaks, then revise the manager submission.');
  }catch(e){announce(e.message);}finally{$('demo').disabled=false;}
};
async function initializeSession(){
  let session=await api('/api/session');
  if(!session.principal)session=await api('/api/session',{persona:'maker-alex'});
  principal=session.principal;$('persona-select').value=principal.id;await refresh();
}
$('persona-select').onchange=async event=>{try{const session=await api('/api/session',{persona:event.target.value});principal=session.principal;await refresh();announce('Demo identity: '+principal.id+' / '+principal.role);}catch(e){announce(e.message);}};
$('open-funding').onclick=()=>{fundingKey=crypto.randomUUID();$('funding-form').reset();$('funding-error').textContent='';$('funding-dialog').showModal();};
$('close-funding').onclick=()=>$('funding-dialog').close();
$('funding-form').onsubmit=async event=>{
  event.preventDefault();const data=Object.fromEntries(new FormData(event.currentTarget));data.amount=Number(data.amount);const button=$('submit-funding');button.disabled=true;
  try{if(!Number.isSafeInteger(data.amount))throw Error('Amount exceeds exact browser precision');await api('/api/treasury/fund',data,fundingKey);await refresh();$('funding-dialog').close();announce('Balanced synthetic reserve transfer posted.');}catch(e){$('funding-error').textContent=e.message;}finally{button.disabled=false;}
};
initializeSession().catch(e=>announce(e.message));

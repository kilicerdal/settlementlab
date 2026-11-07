"""Small allowlisted acceptance DSL executed against an isolated real API."""
import json
import time
from importlib.resources import files
from .fixtures import LocalEnvironment
from .data import TradeFactory
from .client import APIError

ACTIONS={'identity','create','manager','request','approve','fund','settle','snapshot'}


def catalog():
    return [json.loads(path.read_text()) for path in sorted(files('settlementlab.assurance').joinpath('catalog').iterdir(),key=str) if path.name.endswith('.json')]


def lookup(value,path):
    for part in path.split('.'):
        value=value[int(part)] if isinstance(value,list) else value[part]
    return value


def run_scenario(spec):
    if not isinstance(spec.get('steps'),list) or not spec['steps']:
        raise ValueError('Scenario needs nonempty steps')
    if any(step.get('action') not in ACTIONS for step in spec['steps']):
        raise ValueError('Unknown scenario action')
    result=dict(id=spec['id'],suite='scenarios',name=spec['title'],status='passed',steps=[],duration=0.0)
    start=time.perf_counter()
    try:
        with LocalEnvironment(business_date=spec.get('business_date','2026-11-09'),closed_dates=spec.get('closed_dates',())) as environment:
            result['environment']=environment.client.request('/api/health')['business_time']
            client=environment.client;factory=TradeFactory();trade=None
            for index,step in enumerate(spec['steps'],1):
                item=dict(index=index,action=step['action'],status='passed');tick=time.perf_counter()
                try:
                    action=step['action'];data=step.get('data',{});view=None
                    try:
                        if action=='identity':view=client.use_persona(data['persona'])
                        elif action=='create':view=client.create(factory.broker(**data),factory.key('broker'));trade=view
                        elif action=='manager':view=client.submit_manager(trade,factory.manager(**data),factory.key('manager'));trade=view
                        elif action=='request':view=client.request_affirmation(trade,'SYN-CUSTODY',factory.key('review'));trade=view
                        elif action=='approve':view=client.approve(trade);trade=view
                        elif action=='fund':view=client.fund(data['participant_id'],data['asset'],data['amount'],factory.key('fund'))
                        elif action=='settle':view=client.command(trade,'settle');trade=view
                        elif action=='snapshot':view=client.request('/api/snapshot')
                    except APIError as error:
                        if error.status!=step.get('expect_status'):raise
                        view={'http_status':error.status};item['expected_http_status']=error.status
                    else:
                        if 'expect_status' in step:raise AssertionError('Expected HTTP failure '+str(step['expect_status']))
                    for path,expected in step.get('assert',{}).items():
                        actual=lookup(view,path)
                        if actual!=expected:raise AssertionError('%s: expected %r, observed %r'%(path,expected,actual))
                    item['assertions']=len(step.get('assert',{}))
                except Exception as error:
                    item.update(status='failed',detail=str(error));result.update(status='failed',detail='Step %s: %s'%(index,error))
                finally:
                    item['duration']=time.perf_counter()-tick;result['steps'].append(item)
                if result['status']=='failed':break
    except Exception as error:
        result.update(status='failed',detail=str(error))
    result['duration']=time.perf_counter()-start
    return result

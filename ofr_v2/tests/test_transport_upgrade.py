"""Analytical overnight/cost counterexamples, independent audit mutations."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from validate_optimizer import fixture, solve, public_metrics
from validation.audit import audit
from backend.optimization import InputValidationError
from backend.road_planner import build_ui_logistics, COMMON


def long_case():
    u=fixture((10,0,0,0)); n=u['logistics']['road_network']
    n['nodes'].append(dict(id='mid',label='Synthetic assumed rest',rest_allowed=True))
    e=n['edges'][0]
    n['edges']=[dict(e,id=str(k),from_node=a,to_node=b,travel_minutes=150,distance_km=20,toll_cost=1)
                for k,(a,b) in enumerate([('depot','mid'),('mid','site'),('site','mid'),('mid','depot')])]
    n['departure_hours']=[9]
    t=n['trucks'][0]
    t.update(allow_overnight_return=True,cost_per_hour=2,minimum_trip_cost=120,overnight_cost=7)
    t['availability']=[dict(start_hour=d+8.5,end_hour=d+21.5,max_driving_minutes=540) for d in (0,24)]
    return u


def test_overnight_analytical_timing_cost_and_service():
    u=long_case(); before=deepcopy(u); r=solve(u)
    assert u==before
    assert public_metrics(u,r)['fulfillment_pct']==pytest.approx(100)
    assert len(r['truck_plan'])==1
    p=r['truck_plan'][0]
    assert p['overnight_return'] and p['driving_minutes']==600
    assert p['billable_hours']==12.5
    assert p['cost_breakdown']==dict(fixed=40,distance=40,time=25,minimum_adjustment=15,overnight=7,toll=4)
    assert p['transport_cost']==131
    a=audit(u,r); assert a['passed'],a['failures']
    assert not r['model_info']['operational_ready']


@pytest.mark.parametrize('condition',['no_permission','no_destination_rest','no_mid_rest','missing_next_duty','weekend_gap','first_duty_cap','second_duty_cap','deadline'])
def test_overnight_cannot_bypass_constraints(condition):
    u=long_case(); n=u['logistics']['road_network']; t=n['trucks'][0]
    if condition=='no_permission': t['allow_overnight_return']=False
    if condition=='no_destination_rest': n['nodes'][1]['rest_allowed']=False
    if condition=='no_mid_rest': n['nodes'][2]['rest_allowed']=False
    if condition=='missing_next_duty': t['availability']=t['availability'][:1]
    if condition=='weekend_gap': t['availability'][1].update(start_hour=80.5,end_hour=93.5)
    if condition=='first_duty_cap': t['availability'][0]['max_driving_minutes']=290
    if condition=='second_duty_cap': t['availability'][1]['max_driving_minutes']=290
    if condition=='deadline': n['delivery_deadline_hours'][1]=14
    r=solve(u); a=audit(u,r)
    assert a['passed'],a['failures']
    if condition=='deadline': assert all(p['arrival_week']!=1 for p in r['truck_plan'])
    else: assert not r['truck_plan']


def test_single_duty_stays_preferred_without_night_charge():
    u=long_case()
    for e in u['logistics']['road_network']['edges']: e['travel_minutes']=30
    p=solve(u)['truck_plan'][0]
    assert not p['overnight_return'] and p['cost_breakdown']['overnight']==0
    assert not any(e['kind']=='daily_rest' for e in p['timeline'])


def test_vehicle_cannot_be_dispatched_again_during_overnight_return():
    u=long_case(); n=u['logistics']['road_network']; t=n['trucks'][0]
    t['availability'].append(dict(start_hour=56.5,end_hour=69.5,max_driving_minutes=540))
    n['departure_hours']=[9,33]; t['payload_kg']=100
    r=solve(u)
    assert len(r['truck_plan'])==1
    assert audit(u,r)['passed']
    assert public_metrics(u,r)['fulfillment_pct']<100


def test_daily_rest_does_not_reset_weekly_driving_or_budget():
    u=long_case(); u['logistics']['road_network']['trucks'][0]['max_weekly_driving_minutes']=590
    assert not solve(u)['truck_plan']
    u=long_case(); u['total_budget']=130
    assert not solve(u)['truck_plan']


@pytest.mark.parametrize('mutation',['remove_rest','wrong_node','short_rest','return_outside_duty','wrong_price','wrong_billable','wrong_flag'])
def test_independent_audit_rejects_corrupt_overnight_results(mutation):
    u=long_case(); r=solve(u); p=r['truck_plan'][0]
    rest=next(e for e in p['timeline'] if e['kind']=='daily_rest')
    if mutation=='remove_rest': p['timeline'].remove(rest)
    if mutation=='wrong_node': rest['node']='mid'
    if mutation=='short_rest': rest['end_at']=rest['start_at']
    if mutation=='return_outside_duty':
        next(e for e in p['timeline'] if e.get('phase')=='return' and e['kind']=='drive')['start_at']=rest['start_at']
    if mutation=='wrong_price': p['cost_breakdown']['overnight']+=1
    if mutation=='wrong_billable': p['billable_hours']+=1
    if mutation=='wrong_flag': p['overnight_return']=False
    assert not audit(u,r)['passed']


@pytest.mark.parametrize('key,value',[('overnight_cost',-1),('cost_per_hour',float('inf')),('minimum_trip_cost',True),('allow_overnight_return',1)])
def test_invalid_cost_or_permission_fails(key,value):
    u=long_case(); u['logistics']['road_network']['trucks'][0][key]=value
    with pytest.raises(InputValidationError): solve(u)


def test_ui_transport_controls_do_not_mutate_cached_geometry():
    u=fixture(); common={k:u['logistics'][k] for k in COMMON}
    planning=dict(warehouse_id='przemysl-lwowska-36',truck_count=1,reference_date='2026-01-26')
    a,info=build_ui_logistics(common,dict(planning,transport_controls=dict(speed_kph=30,assumed_intermediate_rest=True,cost_per_hour=2)), 'Medyka')
    b,_=build_ui_logistics(common,dict(planning,transport_controls=dict(speed_kph=60,assumed_intermediate_rest=False)), 'Medyka')
    assert a['road_network']['edges'][0]['travel_minutes']==2*b['road_network']['edges'][0]['travel_minutes']
    assert info['assumed_rest_nodes']
    assert all(not p['rest_allowed'] for p in b['road_network']['nodes'] if p['id'] in info['assumed_rest_nodes'])
    assert b['road_network']['trucks'][0]['cost_per_hour']==0

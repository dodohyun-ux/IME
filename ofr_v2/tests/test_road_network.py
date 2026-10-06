"""Synthetic analytical counterexamples for joint path/cargo/truck optimization."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from backend.optimization import example_inputs, optimize_relief_plan, InputValidationError
from backend.road_network import example_road_logistics


def case():
    f,u,v = example_inputs()
    f = {'Medyka':{1:50,2:0,3:0,4:0}}
    u.update(utilization_rate=.2,stay_days=1,total_budget=100000)
    u['initial_inventory']['Medyka'] = {i:0 for i in v}
    u['weekly_supply'] = {i:{w:10 if i=='food' and w==1 else 0 for w in range(1,5)} for i in v}
    u['warehouse_capacity_m3']['Medyka'] = 1000
    l = example_road_logistics()
    l['initial_lots'] = []
    l['shelf_life_days'] = {i:None for i in v}
    n = l['road_network']
    n['trucks'] = n['trucks'][:1]
    n['departure_hours'] = [9]
    return f,u,v,l


def run(f,u,v,l):
    return optimize_relief_plan(f,u,v,logistics=l)


def food(result,week=1):
    return next(p['served'] for p in result['plan'] if p['item']=='food' and p['week']==week)


def edge(l,key):
    return next(e for e in l['road_network']['edges'] if e['id']==key)


def test_joint_shortest_path_cargo_and_named_truck():
    f,u,v,l = case(); untouched=deepcopy(l)
    r = run(f,u,v,l)
    assert food(r)==10
    assert len(r['truck_plan'])==1
    p = r['truck_plan'][0]
    assert p['truck_id']=='truck-01' and p['cargo']['food']==10
    assert p['outbound_edges']==['depot-north','north-site']
    assert p['return_edges']==['site-north','north-depot']
    assert datetime.fromisoformat(p['arrival_at'])>datetime.fromisoformat(p['departure_at'])
    assert p['round_trip_distance_km']==80
    assert p['transport_cost']==180
    assert r['summary']['transport_cost']==180
    assert l==untouched
    assert r['model_info']['road_network_enabled']


def test_closure_requires_detour_on_outbound_and_return():
    f,u,v,l=case()
    edge(l,'depot-north')['open_windows']=[]
    edge(l,'site-north')['open_windows']=[]
    r=run(f,u,v,l)
    assert food(r)==10
    p=r['truck_plan'][0]
    assert p['outbound_edges']==['depot-south','south-site']
    assert p['return_edges']==['site-south','south-depot']
    assert any(x['kind']=='break' for x in p['timeline'])


@pytest.mark.parametrize('restriction',['height','width','gross','type','item'])
def test_restricted_road_is_not_used_by_loaded_truck(restriction):
    f,u,v,l=case(); e=edge(l,'depot-north')
    if restriction=='height': e['max_height_m']=3
    if restriction=='width': e['max_width_m']=2
    if restriction=='gross': e['max_gross_weight_kg']=5001
    if restriction=='type': e['allowed_vehicle_types']=[]
    if restriction=='item': e['allowed_items']=['water']
    r=run(f,u,v,l)
    assert food(r)==10
    assert 'depot-north' not in r['truck_plan'][0]['outbound_edges']


def test_gross_limit_binds_cargo_instead_of_using_tare_as_payload():
    f,u,v,l=case()
    edge(l,'depot-north')['max_gross_weight_kg']=5003
    edge(l,'depot-south')['open_windows']=[]
    r=run(f,u,v,l)
    assert food(r)==5 # 3 kg / .6 kg per ration
    assert r['truck_plan'][0]['weight_kg']==pytest.approx(3)


def test_deadline_can_force_more_expensive_fast_path():
    f,u,v,l=case()
    for k in ('depot-north','north-site'): edge(l,k)['toll_cost']=100
    l['road_network']['delivery_deadline_hours'][1]=12
    r=run(f,u,v,l)
    assert food(r)==10
    assert r['truck_plan'][0]['outbound_edges']==['depot-north','north-site']


def test_cheaper_path_is_selected_when_deadline_permits():
    f,u,v,l=case()
    for k in ('depot-north','north-site'): edge(l,k)['toll_cost']=100
    r=run(f,u,v,l)
    assert food(r)==10
    assert r['truck_plan'][0]['outbound_edges']==['depot-south','south-site']


def test_no_return_path_means_no_loaded_dispatch():
    f,u,v,l=case()
    for k in ('site-north','site-south'): edge(l,k)['open_windows']=[]
    r=run(f,u,v,l)
    assert food(r)==0 and r['truck_plan']==[]


def test_each_truck_load_is_integral_and_feasible_not_aggregate_packing():
    f,u,v,l=case()
    n=l['road_network']; n['trucks'].append(dict(deepcopy(n['trucks'][0]),id='truck-02'))
    for t in n['trucks']: t['payload_kg']=1
    r=run(f,u,v,l)
    assert food(r)==2 # 2 aggregate kg cannot fit three indivisible .6 kg rations
    assert len(r['truck_plan'])==2
    for p in r['truck_plan']:
        assert p['cargo']['food']==1 and p['weight_kg']==pytest.approx(.6)


def test_truck_not_reused_before_return_and_turnaround():
    f,u,v,l=case(); n=l['road_network']
    n['departure_hours']=[9,10]; n['trucks'][0]['payload_kg']=3
    r=run(f,u,v,l)
    assert food(r)==5 and len(r['truck_plan'])==1


def test_truck_can_run_second_tour_after_return_with_driver_window_limit():
    f,u,v,l=case(); n=l['road_network']
    n['departure_hours']=[9,15.5]; n['trucks'][0]['payload_kg']=3
    r=run(f,u,v,l)
    assert food(r)==10 and len(r['truck_plan'])==2
    assert datetime.fromisoformat(r['truck_plan'][0]['available_again_at'])<=datetime.fromisoformat(r['truck_plan'][1]['load_start_at'])


def test_shared_capacity_includes_empty_return_entries():
    f,u,v,l=case(); n=l['road_network']
    n['trucks'].append(dict(deepcopy(n['trucks'][0]),id='truck-02'))
    for t in n['trucks']: t['payload_kg']=3
    for k in ('site-north','site-south'): edge(l,k)['capacity_resource']='bridge'
    n['capacity_resources']={'bridge':[dict(start_hour=0,end_hour=672,max_entries=1)]}
    # Close south outbound/return to prevent an alternate return entry time.
    edge(l,'depot-south')['open_windows']=[]; edge(l,'site-south')['open_windows']=[]
    r=run(f,u,v,l)
    assert food(r)==5
    assert all(x['entries']<=1 for x in r['road_capacity_usage'])


def test_capacity_applies_at_edge_entry_not_depot_departure():
    f,u,v,l=case(); n=l['road_network']
    edge(l,'north-site')['capacity_resource']='border'
    edge(l,'depot-south')['open_windows']=[]
    n['capacity_resources']={'border':[dict(start_hour=9,end_hour=10,max_entries=1)]}
    assert food(run(f,u,v,l))==0 # reach border at 10, so departure slot quota is irrelevant


def test_open_window_must_cover_whole_edge_traversal():
    f,u,v,l=case()
    edge(l,'depot-north')['open_windows']=[dict(start_hour=9,end_hour=9.5)]
    edge(l,'depot-south')['open_windows']=[]
    assert food(run(f,u,v,l))==0


def test_procurement_ready_before_loading_exact_days_not_week_ceiling():
    f,u,v,l=case(); n=l['road_network']
    l['procurement_lead_days']['food']=2
    n['departure_hours']=[9,57]
    n['trucks'][0]['availability'].append(dict(start_hour=56,end_hour=69,max_driving_minutes=540))
    n['delivery_deadline_hours'][1]=72
    r=run(f,u,v,l)
    assert food(r)==10
    assert r['truck_plan'][0]['departure_at']=='2026-10-07T07:00:00+00:00'
    n['departure_hours']=[48] # loading begins 47.5h, earlier than 48h readiness
    assert food(run(f,u,v,l))==0


def test_shelf_life_at_delivery_deadline_blocks_expired_cargo():
    f,u,v,l=case()
    l['shelf_life_days']['food']=.1
    assert food(run(f,u,v,l))==0
    l['shelf_life_days']['food']=1
    assert food(run(f,u,v,l))==10


def test_unloading_after_deadline_rolls_delivery_to_next_week():
    f,u,v,l=case(); f['Medyka'][2]=50
    l['road_network']['delivery_deadline_hours'][1]=11
    r=run(f,u,v,l)
    assert food(r,1)==0 and food(r,2)==10
    assert r['truck_plan'][0]['arrival_week']==2


def test_transport_cost_binds_same_budget_as_procurement():
    f,u,v,l=case(); u['total_budget']=230
    r=run(f,u,v,l)
    assert food(r)==5 # 180 transport + 5*10 food
    assert r['summary']['total_cost']==pytest.approx(230)


def test_driver_window_sum_limits_multiple_short_tours():
    f,u,v,l=case(); n=l['road_network']
    n['departure_hours']=[9,15.5]; n['trucks'][0]['payload_kg']=3
    n['trucks'][0]['availability'][0]['max_driving_minutes']=300
    assert food(run(f,u,v,l))==5 # each tour drives 240min; both exceed window budget


def test_mandatory_break_requires_approved_rest_node():
    f,u,v,l=case()
    edge(l,'depot-north')['open_windows']=[]
    for node in l['road_network']['nodes']: node['rest_allowed']=False
    assert food(run(f,u,v,l))==0 # 6h driving return cycle requires a break


def test_break_lookahead_can_rest_before_delivery_for_the_return_leg():
    f,u,v,l=case(); n=l['road_network']
    for e in n['edges']:
        if 'south' in e['id']: e['open_windows']=[]
        else: e['travel_minutes']=120
    for node in n['nodes']: node['rest_allowed']=node['id'] in ('depot','north')
    r=run(f,u,v,l)
    assert food(r)==10
    p=r['truck_plan'][0]
    breaks=[e for e in p['timeline'] if e['kind']=='break' and e.get('phase')!='depot_rest']
    assert [e['node'] for e in breaks]==['north','north']
    assert [e['phase'] for e in breaks]==['outbound','return']
    assert (datetime.fromisoformat(p['arrival_at'])-datetime.fromisoformat(p['departure_at'])).total_seconds()==300*60
    # Removing the only reachable rest point must still block the tour.
    next(node for node in n['nodes'] if node['id']=='north')['rest_allowed']=False
    assert food(run(f,u,v,l))==0


def test_break_before_earlier_rest_stop_when_next_junction_has_no_rest():
    f,u,v,l=case(); n=l['road_network']
    for e in n['edges']:
        if 'south' in e['id']: e['open_windows']=[]
    edge(l,'depot-north')['travel_minutes']=90
    edge(l,'north-site').update(to_node='junction',travel_minutes=90)
    n['nodes'].append(dict(id='junction',label='Synthetic non-rest junction',rest_allowed=False))
    n['edges'].append(dict(deepcopy(edge(l,'north-site')),id='junction-site',from_node='junction',to_node='site',travel_minutes=120))
    r=run(f,u,v,l)
    assert food(r)==10
    p=r['truck_plan'][0]
    assert p['outbound_edges']==['depot-north','north-site','junction-site']
    assert any(e['kind']=='break' and e.get('phase')=='outbound' and e['node']=='north' for e in p['timeline'])
    assert all(e.get('node')!='junction' for e in p['timeline'] if e['kind']=='break')


def test_supplier_supply_not_duplicated_across_truck_paths():
    f,u,v,l=case(); n=l['road_network']
    n['departure_hours']=[9,15.5]
    n['trucks'].append(dict(deepcopy(n['trucks'][0]),id='truck-02'))
    u['weekly_supply']['food'][1]=3
    r=run(f,u,v,l)
    assert food(r)==3
    assert sum(p['cargo']['food'] for p in r['truck_plan'])==3


@pytest.mark.parametrize('bad',['unknown_node','naive_time','negative_time','non_grid','bad_window',
                                'driver_limit','unknown_source','operational_no_source','mixed_modes', 'bad_expiry'])
def test_invalid_graph_rejected_before_solving(bad):
    f,u,v,l=case(); n=l['road_network']
    if bad=='unknown_node': n['edges'][0]['to_node']='unknown'
    if bad=='naive_time': n['planning_start']='2026-10-05T00:00:00'
    if bad=='negative_time': n['edges'][0]['travel_minutes']=-1
    if bad=='non_grid': n['departure_hours']=[9.1]
    if bad=='bad_window': n['trucks'][0]['availability'][1]['start_hour']=22
    if bad=='driver_limit': n['trucks'][0]['max_continuous_driving_minutes']=300
    if bad=='unknown_source': n['edges'][0]['source_id']='none'
    if bad=='operational_no_source': n['data_kind']='operational'
    if bad=='mixed_modes': l['routes']=[]
    if bad=='bad_expiry': l['shelf_life_days']['food']=True
    with pytest.raises(InputValidationError): run(f,u,v,l)


def test_search_limit_fails_instead_of_silently_dropping_routes(monkeypatch):
    import backend.road_network as road
    f,u,v,l=case(); monkeypatch.setattr(road,'MAX_PATHS',1)
    with pytest.raises(InputValidationError,match='no paths truncated'): run(f,u,v,l)


def test_reverse_week_mapping_order_does_not_change_arrival_week():
    f,u,v,l=case(); n=l['road_network']
    n['delivery_deadline_hours']=dict(reversed(list(n['delivery_deadline_hours'].items())))
    r=run(f,u,v,l)
    assert food(r)==10 and r['truck_plan'][0]['arrival_week']==1


def test_depot_break_is_explicit_before_second_trip():
    f,u,v,l=case(); n=l['road_network']
    n['departure_hours']=[9,15.5]; n['trucks'][0]['payload_kg']=3
    r=run(f,u,v,l)
    assert len(r['truck_plan'])==2
    for p in r['truck_plan']:
        rest=next(e for e in p['timeline'] if e.get('phase')=='depot_rest')
        assert (datetime.fromisoformat(rest['end_at'])-datetime.fromisoformat(rest['start_at'])).total_seconds()>=2700


def test_no_depot_rest_area_allows_only_one_tour_per_driver_window():
    f,u,v,l=case(); n=l['road_network']
    n['departure_hours']=[9,15.5]; n['trucks'][0]['payload_kg']=3
    next(x for x in n['nodes'] if x['id']=='depot')['rest_allowed']=False
    assert food(run(f,u,v,l))==5


def test_adjacent_open_windows_are_continuous():
    f,u,v,l=case()
    edge(l,'depot-north')['open_windows']=[dict(start_hour=0,end_hour=9.5),dict(start_hour=9.5,end_hour=672)]
    assert run(f,u,v,l)['truck_plan'][0]['outbound_edges']==['depot-north','north-site']


def test_expiry_exactly_at_distribution_deadline_is_unusable():
    f,u,v,l=case()
    l['shelf_life_days']['food']=11/24
    assert food(run(f,u,v,l))==0
    l['shelf_life_days']['food']=12/24
    assert food(run(f,u,v,l))==10


def test_initial_fefo_stock_is_used_before_new_truck_cargo():
    f,u,v,l=case()
    u['initial_inventory']['Medyka']['food']=3
    l['initial_lots']=[dict(id='old-food',item='food',quantity=3,expiry_week=2)]
    r=run(f,u,v,l)
    assert food(r)==10
    assert r['truck_plan'][0]['cargo']['food']==7
    assert next(p for p in r['lot_plan'] if p['lot_id']=='old-food' and p['week']==1)['served']==3


def test_prepaid_pipeline_does_not_create_fake_named_truck():
    f,u,v,l=case()
    l['pipeline_lots']=[dict(id='booked',item='food',quantity=10,arrival_week=1,expiry_week=None)]
    r=run(f,u,v,l)
    assert food(r)==10 and r['truck_plan']==[]
    assert r['summary']['total_cost']==0


@pytest.mark.parametrize('cap_kind',['weekly','two_week'])
def test_driver_aggregate_week_limits(cap_kind):
    f,u,v,l=case(); n=l['road_network']; t=n['trucks'][0]
    n['departure_hours']=[9,15.5]; t['payload_kg']=3
    if cap_kind=='weekly': t['max_weekly_driving_minutes']=300
    else: t['max_two_week_driving_minutes']=300
    assert food(run(f,u,v,l))==5


def test_candidate_limit_fails_before_solving(monkeypatch):
    import backend.road_network as road
    f,u,v,l=case(); monkeypatch.setattr(road,'MAX_CANDIDATES',1)
    with pytest.raises(InputValidationError,match='no candidates truncated'): run(f,u,v,l)


def test_empty_return_can_use_road_limit_equal_to_tare():
    f,u,v,l=case()
    edge(l,'site-north')['max_gross_weight_kg']=5000
    edge(l,'site-south')['open_windows']=[]
    r=run(f,u,v,l)
    assert food(r)==10 and r['truck_plan'][0]['return_edges']==['site-north','north-depot']


@pytest.mark.parametrize('priority',['fairness','efficiency'])
def test_road_plan_reconciles_orders_arrivals_and_cost_for_both_priorities(priority):
    f,u,v,l=case(); u['priority']=priority
    r=run(f,u,v,l)
    shipped=sum(p['recommended_shipment'] for p in r['plan'] if p['item']=='food')
    ordered=sum(p['quantity'] for p in r['order_plan'] if p['item']=='food')
    loaded=sum(p['cargo']['food'] for p in r['truck_plan'])
    assert shipped==ordered==loaded==10
    s=r['summary']
    assert s['total_cost']==pytest.approx(s['total_procurement_cost']+s['transport_cost']+s['disposal_cost'])


def test_road_inventory_expansion_limits_fail_before_memory_growth(monkeypatch):
    import backend.road_network as road
    f,u,v,l=case(); monkeypatch.setattr(road,'MAX_ORDER_LOTS',1)
    with pytest.raises(InputValidationError,match='no lots truncated'): run(f,u,v,l)


def test_road_fefo_size_limit_preserves_constraints_instead_of_skipping_them(monkeypatch):
    import backend.road_network as road
    f,u,v,l=case()
    u['initial_inventory']['Medyka']['food']=3
    l['initial_lots']=[dict(id='old-food',item='food',quantity=3,expiry_week=2)]
    monkeypatch.setattr(road,'MAX_FEFO_TERMS',1)
    with pytest.raises(InputValidationError,match='FEFO model exceeds'): run(f,u,v,l)

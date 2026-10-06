from copy import deepcopy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from backend.optimization import example_inputs, optimize_relief_plan, InputValidationError, OptimizationError
from backend.logistics import example_logistics


def case():
    f, u, v = example_inputs()
    f = {'Medyka': {w: 100 for w in range(1, 5)}}
    u['total_budget'] = 1e7
    u['warehouse_capacity_m3']['Medyka'] = 10000
    u['initial_inventory']['Medyka'] = {i: 0 for i in v}
    u['weekly_supply'] = {i: {w: 100000 for w in range(1, 5)} for i in v}
    l = example_logistics()
    l['initial_lots'] = []
    l['vehicles']['truck']['available'] = {w: 10 for w in range(1, 5)}
    l['vehicles']['truck']['payload_kg'] = 1e6
    l['vehicles']['truck']['volume_m3'] = 1e6
    r = l['routes'][0]
    r['max_trips'] = {w: 10 for w in range(1, 5)}
    r['max_weight_kg'] = {w: 1e9 for w in range(1, 5)}
    r['max_volume_m3'] = {w: 1e9 for w in range(1, 5)}
    r['trip_cost'] = 0
    l['corridors']['local-access'] = {w: 10 for w in range(1, 5)}
    return f, u, v, l


def run(f, u, v, l):
    return optimize_relief_plan(f, u, v, logistics=l)


def test_legacy_equivalence_without_binding_logistics():
    f, u, v, l = case()
    old = optimize_relief_plan(f, u, v)
    new = run(f, u, v, l)
    for name in ('max_unmet_rate', 'overall_weighted_fulfillment_rate', 'total_procurement_cost'):
        assert new['summary'][name] == pytest.approx(old['summary'][name], abs=1e-4)


@pytest.mark.parametrize('procurement,transit,first', [(0, 1, 2), (1, 0, 2), (7, 7, 3), (8, 0, 3), (21, 7, 5)])
def test_orders_cannot_serve_before_both_leads(procurement, transit, first):
    f, u, v, l = case()
    l['procurement_lead_days'] = {i: procurement for i in v}
    l['routes'][0].update(transit_days=transit, round_trip_days=transit)
    result = run(f, u, v, l)
    assert all(p['served'] == 0 for p in result['plan'] if p['week'] < first)
    assert all(o['dispatch_week'] == o['order_week'] + ((procurement+6)//7) for o in result['order_plan'])
    assert all(o['arrival_week'] == o['dispatch_week'] + ((transit+6)//7) <= 4 for o in result['order_plan'])


@pytest.mark.parametrize('binding', ['weight', 'volume', 'route_weight', 'route_volume'])
def test_vehicle_and_route_caps(binding):
    f, u, v, l = case()
    truck, route = l['vehicles']['truck'], l['routes'][0]
    truck['available'] = {w: 1 for w in range(1,5)}
    if binding == 'weight': truck['payload_kg'] = 100
    if binding == 'volume': truck['volume_m3'] = .1
    if binding == 'route_weight': route['max_weight_kg'] = {w: 100 for w in range(1,5)}
    if binding == 'route_volume': route['max_volume_m3'] = {w: .1 for w in range(1,5)}
    result = run(f, u, v, l)
    for row in result['transport_plan']:
        assert row['trips'] == int(row['trips']) <= 1
        assert row['weight_kg'] <= min(truck['payload_kg']*row['trips'], route['max_weight_kg'][row['week']]) + 1e-5
        assert row['volume_m3'] <= min(truck['volume_m3']*row['trips'], route['max_volume_m3'][row['week']]) + 1e-5
    assert result['summary']['overall_weighted_fulfillment_rate'] < 1


def test_shared_corridor_and_fleet_not_duplicated_across_alternatives():
    f, u, v, l = case()
    l['routes'].append(dict(deepcopy(l['routes'][0]), id='alternative'))
    l['corridors']['local-access'] = {w: 1 for w in range(1,5)}
    l['vehicles']['truck']['available'] = {w: 1 for w in range(1,5)}
    l['vehicles']['truck']['payload_kg'] = 100
    l['routes'][0]['max_trips'][1] = 0
    result = run(f, u, v, l)
    for w in range(1,5):
        assert sum(r['trips'] for r in result['transport_plan'] if r['week'] == w) <= 1
    assert next(r for r in result['transport_plan'] if r['route'] == 'domestic-direct' and r['week'] == 1)['trips'] == 0


def test_vehicle_is_busy_until_return():
    f, u, v, l = case()
    l['vehicles']['truck']['available'] = {w: 1 for w in range(1,5)}
    l['vehicles']['truck']['payload_kg'] = 100
    l['routes'][0]['round_trip_days'] = 14
    result = run(f, u, v, l)
    trips = {r['week']: r['trips'] for r in result['transport_plan']}
    assert all(trips[w] + trips.get(w-1,0) <= 1 for w in trips)


def test_corridor_slots_apply_to_crossing_week_not_departure_week():
    f,u,v,l=case()
    l['routes'][0].update(transit_days=7,round_trip_days=7,corridor_delay_days=7)
    l['corridors']['local-access'][2]=0
    result=run(f,u,v,l)
    assert next(r for r in result['transport_plan'] if r['week']==1)['trips']==0
    assert all(r['trips']==0 for r in result['transport_plan'] if r['crossing_week']==2)


def test_transport_cost_is_in_budget():
    f, u, v, l = case()
    u['total_budget'] = 499
    l['routes'][0]['trip_cost'] = 500
    result = run(f, u, v, l)
    assert sum(p['recommended_shipment'] for p in result['plan']) == 0
    assert result['summary']['total_cost'] <= 499


def test_shelf_life_that_expires_in_transit_cannot_be_ordered():
    f, u, v, l = case()
    l['shelf_life_days'] = {i: 7 for i in v}
    l['routes'][0].update(transit_days=7, round_trip_days=7)
    result = run(f, u, v, l)
    assert not result['order_plan']
    assert sum(p['served'] for p in result['plan']) == 0


def test_fefo_expiry_and_quarantine_disposal_balance():
    f, u, v, l = case()
    u['initial_inventory']['Medyka']['food'] = 200
    l['initial_lots'] = [dict(id='older', item='food', quantity=100, expiry_week=2),
                         dict(id='later', item='food', quantity=100, expiry_week=4)]
    u['weekly_supply']['food'] = {w:0 for w in range(1,5)}
    l['disposal_capacity']['food'] = {w:10 for w in range(1,5)}
    l['disposal_cost']['food'] = .5
    result = run(f, u, v, l)
    older = next(r for r in result['lot_plan'] if r['lot_id']=='older' and r['week']==1)
    later = next(r for r in result['lot_plan'] if r['lot_id']=='later' and r['week']==1)
    assert older['served'] == 30
    assert later['served'] == 0
    food = [p for p in result['plan'] if p['item']=='food']
    assert food[1]['expired_quantity'] == 70
    assert food[-1]['expired_quantity'] == 40
    quarantine = 0
    for p in food:
        quarantine += p['expired_quantity'] - p['disposed_quantity']
        assert p['quarantined_inventory'] == pytest.approx(quarantine)
    assert all(r['served']==0 for r in result['lot_plan'] if r['expiry_week'] is not None and r['week']>=r['expiry_week'])
    assert result['summary']['disposal_cost'] == pytest.approx(sum(p['disposed_quantity']*.5 for p in food))


def test_expired_pipeline_is_quarantined_not_served():
    f, u, v, l = case()
    for i in v: u['weekly_supply'][i] = {w:0 for w in range(1,5)}
    l['pipeline_lots'] = [dict(id='late', item='food', quantity=100, expiry_week=2, arrival_week=2)]
    l['disposal_capacity']['food'] = {w:0 for w in range(1,5)}
    result = run(f, u, v, l)
    assert sum(p['served'] for p in result['plan']) == 0
    assert next(p for p in result['plan'] if p['item']=='food' and p['week']==2)['quarantined_inventory'] == 100


def test_quarantined_stock_still_occupies_warehouse():
    f, u, v, l = case()
    u['warehouse_capacity_m3']['Medyka'] = .1
    l['pipeline_lots'] = [dict(id='late', item='food', quantity=100, expiry_week=1, arrival_week=1)]
    l['disposal_capacity']['food'] = {w:0 for w in range(1,5)}
    with pytest.raises(OptimizationError): run(f, u, v, l)


def test_prepaid_pipeline_neither_reorders_nor_recharges():
    f, u, v, l = case()
    u['total_budget'] = 0
    for i in v: u['weekly_supply'][i] = {w:0 for w in range(1,5)}
    l['pipeline_lots'] = [dict(id='booked', item='water', quantity=100, expiry_week=10, arrival_week=1)]
    result = run(f, u, v, l)
    assert sum(p['served'] for p in result['plan']) == pytest.approx(100)
    assert result['summary']['total_cost'] == 0
    assert sum(t['trips'] for t in result['transport_plan']) == 0


@pytest.mark.parametrize('key,value', [('procurement_lead_days',-1), ('item_weight_kg',True),
                                      ('shelf_life_days',0), ('disposal_cost',float('nan'))])
def test_invalid_item_parameters_rejected(key,value):
    f, u, v, l = case(); l[key]['water'] = value
    with pytest.raises(InputValidationError): run(f, u, v, l)


def test_initial_lots_must_reconcile_with_stock():
    f, u, v, l = case(); u['initial_inventory']['Medyka']['food']=1
    with pytest.raises(InputValidationError, match='sum'): run(f, u, v, l)


def test_initial_expired_goods_never_used_and_inputs_not_mutated():
    f, u, v, l = case()
    u['initial_inventory']['Medyka']['food']=10
    l['initial_lots']=[dict(id='expired',item='food',quantity=10,expiry_week=0)]
    before=deepcopy((f,u,v,l))
    result=run(f,u,v,l)
    assert (f,u,v,l)==before
    assert next(p for p in result['plan'] if p['item']=='food' and p['week']==1)['expired_quantity']==10


@pytest.mark.parametrize('priority',['fairness','efficiency'])
def test_result_flow_integrality_cost_and_peak_storage(priority):
    f,u,v,l=case(); u['priority']=priority
    result=run(f,u,v,l)
    s=result['summary']
    assert s['total_cost']==pytest.approx(s['total_procurement_cost']+s['transport_cost']+s['disposal_cost'])
    for p in result['plan']:
        assert p['served']+p['unmet_demand']==pytest.approx(p['demand'])
        if p['item']!='water':
            assert all(p[k]==round(p[k]) for k in ['served','ending_inventory','unmet_demand','disposed_quantity'])
    assert all(w['warehouse_utilization_rate']<=1+1e-6 for w in result['warehouse_summary'])


def test_fractional_water_can_use_one_vehicle():
    f,u,v,l=case()
    f={'Medyka':{w:0 for w in range(1,5)}}
    f['Medyka'][1]=1
    u['weekly_supply']['water']={w:.1 for w in range(1,5)}
    for i in ('food','hygiene_kit','blanket'): u['weekly_supply'][i]={w:0 for w in range(1,5)}
    u['priority']='efficiency'
    result=run(f,u,v,l)
    assert sum(p['served'] for p in result['plan'])==pytest.approx(.1,abs=1e-4)

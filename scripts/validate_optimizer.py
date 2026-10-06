"""Reproducible optimization-only evidence; no prediction training or inference.

Run: python scripts/validate_optimizer.py [--quick] [--skip-official]
Synthetic experiments test declared-model behavior, not observed field savings.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import argparse
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ofr_v2/app'))
sys.path.insert(0,str(ROOT/'ofr_v2'))
from backend.optimization import optimize_relief_plan, OptimizationError
from backend.road_network import example_road_logistics
from backend.road_planner import build_ui_logistics, COMMON
from validation.audit import audit, demand, ITEMS

OUTPUT=ROOT/'ofr_v2/results/optimization_validation_20261003'
SEED=20261003


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frozen_assets():
    paths=[ROOT/'ofr_v2/app/backend'/name for name in ('optimization.py','logistics.py','road_network.py','road_paths.py','poland_roads.py','road_planner.py','main.py','weekly_forecast.py')]
    for folder in ('ofr_v2/app/models','ofr_v2/app/data','ofr_v2/pipeline'):
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    paths.extend(ROOT/'ofr_v2/results'/name for name in ('model_selection.md','holdout_metrics.txt','validation_metrics.txt','ablation_metrics.txt'))
    return {p.relative_to(ROOT).as_posix():sha(p) for p in paths if p.exists()}


def fixture(people=(30,30,30,30),site='Medyka',fleet=1):
    preset=json.loads((ROOT/'ofr_v2/data/roads/ui_preset.json').read_text(encoding='utf-8'))
    l=example_road_logistics(site)
    l['initial_lots']=[]
    l['shelf_life_days']={i:None for i in ITEMS}
    n=l['road_network']
    n['slot_minutes']=15
    n['nodes']=[dict(id=x,label='Synthetic '+x,rest_allowed=True) for x in ('depot','site')]
    template=deepcopy(n['edges'][0])
    n['edges']=[dict(template,id=a+'-'+b,from_node=a,to_node=b,distance_km=20,travel_minutes=30,
                     max_gross_weight_kg=100000,max_height_m=10,max_width_m=10,
                     allowed_vehicle_types=[preset['vehicle']['vehicle_type']]) for a,b in (('depot','site'),('site','depot'))]
    truck=deepcopy(n['trucks'][0]); truck.update(preset['vehicle'])
    truck['fixed_trip_cost']=40; truck['cost_per_km']=.5
    truck['availability']=[dict(start_hour=w*168+d+8.5,end_hour=w*168+d+21.5,max_driving_minutes=540) for w in range(4) for d in (0,72)]
    n['trucks']=[dict(deepcopy(truck),id=f'truck-{k+1:02d}') for k in range(fleet)]
    n['departure_hours']=[w*168+d+9 for w in range(4) for d in (0,72)]
    n['delivery_deadline_hours']={w:w*168 for w in range(1,5)}
    u=dict(selected_site=site,utilization_rate=.2,stay_days=1,
           ml_forecast={site:{w:5*p for w,p in enumerate(people,1)}},
           initial_inventory={site:{i:0 for i in ITEMS}},
           weekly_supply={i:{w:100000 for w in range(1,5)} for i in ITEMS},
           unit_cost=dict(water=1,food=10,hygiene_kit=25,blanket=30),
           total_budget=100000,warehouse_capacity_m3={site:100},
           item_volume_m3=dict(water=.001,food=.002,hygiene_kit=.010,blanket=.020),
           priority='fairness',logistics=l)
    return u


def solve(u):
    user={k:v for k,v in u.items() if k not in ('ml_forecast','logistics','item_volume_m3')}
    return optimize_relief_plan(u['ml_forecast'],user,u['item_volume_m3'],logistics=u['logistics'])


def score(u,r):
    totals={i:sum(p['demand'] for p in r['plan'] if p['item']==i) for i in ITEMS}
    worst=max((p['unmet_demand']/p['demand'] for p in r['plan'] if p['demand']),default=0)
    normalized=sum(p['unmet_demand']/totals[p['item']] for p in r['plan'] if totals[p['item']])
    return (worst,normalized,r['summary']['total_cost']) if u['priority']=='fairness' else (normalized,r['summary']['total_cost'])


def public_metrics(u,r):
    totals={i:sum(p['demand'] for p in r['plan'] if p['item']==i) for i in ITEMS}
    active=sum(v>0 for v in totals.values())
    weighted=sum(p['unmet_demand']/totals[p['item']] for p in r['plan'] if totals[p['item']])
    return dict(fulfillment_pct=100*(1-weighted/active) if active else 100,
                worst_shortage_pct=100*max((p['unmet_demand']/p['demand'] for p in r['plan'] if p['demand']),default=0),
                cost=r['summary']['total_cost'],trips=len(r['truck_plan']),
                distance_km=sum(p['round_trip_distance_km'] for p in r['truck_plan']),
                max_gap=max((p['mip_gap'] or 0 for p in r['model_info']['solver_stages']),default=0))


def enumerated_truth(u):
    """Independent exhaustive cargo/path/truck enumeration for a tiny two-item slice.

    Water and food are satisfied from opening inventory. No continuous purchase,
    expiry, rest or binding warehouse term in this deliberately bounded oracle.
    Every simple outward/return path is enumerated without engine helpers.
    """
    n=u['logistics']['road_network']; l=u['logistics']
    edges={e['id']:e for e in n['edges']}; adj=defaultdict(list)
    for e in edges.values():
        adj[e['from_node']].append(e)
    def paths(node,target,seen):
        if node==target:
            yield []
        else:
            for e in adj[node]:
                if e['to_node'] not in seen:
                    for tail in paths(e['to_node'],target,seen|{e['to_node']}):
                        yield [e]+tail
    outbound=list(paths(n['depot_node'],n['destination_node'],{n['depot_node']}))
    returning=list(paths(n['destination_node'],n['depot_node'],{n['destination_node']}))
    population=demand(u['ml_forecast'][u['selected_site']],.2,1)[1]['hygiene_kit']
    supplies={i:u['weekly_supply'][i][1] for i in ('hygiene_kit','blanket')}
    options=[]
    for t in n['trucks']:
        choices=[(0,0,0.)]
        for a,b in itertools.product(outbound,returning):
            cap=min(t['payload_kg'],t['max_gross_weight_kg']-t['tare_kg'],*(e['max_gross_weight_kg']-t['tare_kg'] for e in a))
            cost=t['fixed_trip_cost']+sum(e['distance_km']*t['cost_per_km']+e['toll_cost'] for e in a+b)
            for kit in range(min(population,supplies['hygiene_kit'])+1):
                for blanket in range(min(population,supplies['blanket'])+1):
                    if not kit+blanket:
                        continue
                    weight=kit*l['item_weight_kg']['hygiene_kit']+blanket*l['item_weight_kg']['blanket']
                    volume=kit*u['item_volume_m3']['hygiene_kit']+blanket*u['item_volume_m3']['blanket']
                    if weight<=cap+1e-8 and volume<=t['volume_m3']+1e-8:
                        choices.append((kit,blanket,cost+kit*u['unit_cost']['hygiene_kit']+blanket*u['unit_cost']['blanket']))
        options.append(choices)
    best=None; examined=0
    for assignment in itertools.product(*options):
        examined+=1
        kit=sum(a[0] for a in assignment); blanket=sum(a[1] for a in assignment); cost=sum(a[2] for a in assignment)
        if kit>min(population,supplies['hygiene_kit']) or blanket>min(population,supplies['blanket']) or cost>u['total_budget']+1e-8:
            continue
        worst=max(1-kit/population,1-blanket/population)
        weighted=(population-kit)/population+(population-blanket)/population
        s=(worst,weighted,cost) if u['priority']=='fairness' else (weighted,cost)
        if best is None or s<best:
            best=s
    return best,examined


def oracle_cases(count=48):
    rng=random.Random(SEED)
    for k in range(count):
        p=rng.randint(1,6)
        u=fixture((p,0,0,0),fleet=1+k%2)
        u['priority']='fairness' if k%3 else 'efficiency'
        u['total_budget']=rng.randint(0,100)
        u['unit_cost'].update(hygiene_kit=4,blanket=6)
        u['initial_inventory']['Medyka'].update(water=p*15,food=p)
        u['logistics']['initial_lots']=[dict(id=i,item=i,quantity=q,expiry_week=None) for i,q in u['initial_inventory']['Medyka'].items() if q]
        for i in ITEMS:
            u['weekly_supply'][i]={w:rng.randint(0,6) if w==1 and i in ('hygiene_kit','blanket') else 0 for w in range(1,5)}
        u['logistics']['item_weight_kg'].update(hygiene_kit=2,blanket=3)
        u['item_volume_m3'].update(hygiene_kit=1,blanket=2)
        n=u['logistics']['road_network']; n['departure_hours']=[9]
        # Two routes, independently enumerated four outward/return combinations.
        n['nodes'].append(dict(id='via',label='Synthetic detour',rest_allowed=True))
        e=deepcopy(n['edges'][0])
        for a,b in (('depot','via'),('via','site'),('site','via'),('via','depot')):
            n['edges'].append(dict(e,id=a+'-'+b,from_node=a,to_node=b,distance_km=4,travel_minutes=5))
        for e in n['edges']:
            if 'via' not in e['id']:
                e.update(distance_km=3,travel_minutes=5,toll_cost=rng.randint(0,4))
        for t in n['trucks']:
            t.update(payload_kg=rng.randint(2,9),volume_m3=rng.randint(1,7),fixed_trip_cost=5,cost_per_km=1)
        yield f'oracle-{k:02d}',u


def mutation_checks(u,r):
    changes={
        'overweight':lambda x:x['truck_plan'][0]['cargo'].__setitem__('water',100000),
        'broken-route':lambda x:x['truck_plan'][0]['outbound_edges'].append(x['truck_plan'][0]['outbound_edges'][0]),
        'wrong-cost':lambda x:x['summary'].__setitem__('total_cost',0),
        'stock-creation':lambda x:x['lot_plan'][0].__setitem__('ending_usable_inventory',999),
        'demand-creation':lambda x:x['plan'][0].__setitem__('served',99999),
        'wrong-departure':lambda x:x['truck_plan'][0].__setitem__('departure_at','2026-10-05T01:00:00+00:00'),
        'duplicate-trip':lambda x:x['truck_plan'].append(deepcopy(x['truck_plan'][0])),
        'order-creation':lambda x:x['order_plan'][0].__setitem__('quantity',99999),
    }
    rows=[]
    for name,modify in changes.items():
        bad=deepcopy(r);modify(bad)
        finding=audit(u,bad)
        rows.append(dict(case=name,detected=not finding['passed'],failures=finding['failures'][:4]))
    return rows


def greedy(u):
    """Independent current-week shortage heuristic for the direct synthetic graph.

    Buys only current-order-week supply; balances normalized item shortages by
    one-unit increments. No MILP or shared optimizer scheduling helpers.
    One site, deterministic weekly demand; no guessed future field demand.
    """
    l=u['logistics']; n=l['road_network']; site=u['selected_site']
    assert len(n['edges'])==2 and not l['pipeline_lots'] and not n['capacity_resources']
    start=datetime.fromisoformat(n['planning_start']).astimezone(timezone.utc)
    iso=lambda h:(start+timedelta(hours=h)).isoformat()
    slot=n['slot_minutes']; roundup=lambda v:math.ceil(v/slot-1e-9)*slot
    D=demand(u['ml_forecast'][site],u['utilization_rate'],u['stay_days'])
    stock=[dict(b,arrival_week=1,remaining=float(b['quantity'])) for b in l['initial_lots']]
    inventory={i:0. for i in ITEMS}; quarantine={i:0. for i in ITEMS}
    trips=[]; orders=[]; lot_plan=[]; plan=[]; warehouse=[]
    spent=0.; trip_cost=0.; disposed_cost=0.; used_until=defaultdict(float)
    for w in range(1,5):
        expired=Counter(); disposal=Counter()
        for b in stock:
            if b['expiry_week'] is not None and w>=b['expiry_week'] and b['remaining']:
                expired[b['item']]+=b['remaining'];quarantine[b['item']]+=b['remaining'];b['remaining']=0.
        for i in ITEMS:
            cap=l['disposal_capacity'][i][w]
            q=min(quarantine[i],cap)
            if l['disposal_cost'][i]:
                q=min(q,(u['total_budget']-spent)/l['disposal_cost'][i])
            if i!='water': q=math.floor(q+1e-9)
            quarantine[i]-=q; disposal[i]=q
            spent+=q*l['disposal_cost'][i];disposed_cost+=q*l['disposal_cost'][i]
        inventory={i:sum(b['remaining'] for b in stock if b['item']==i) for i in ITEMS}
        bought=Counter(); arrived=Counter()
        for departure in n['departure_hours']:
            if not (w-1)*168<=departure<w*168:
                continue
            for t in n['trucks']:
                outbound,back=n['edges']
                loading=roundup(t['loading_minutes'])/60;unloading=roundup(t['unloading_minutes'])/60
                a=departure-loading;arrival=departure+roundup(outbound['travel_minutes'])/60
                delivered=arrival+unloading;returned=delivered+roundup(back['travel_minutes'])/60
                rest_end=returned+roundup(t['break_minutes'])/60
                release=rest_end+roundup(t['turnaround_minutes'])/60
                if a<used_until[t['id']]-1e-8 or delivered>n['delivery_deadline_hours'][w]+1e-8:
                    continue
                if not any(win['start_hour']<=a and release<=win['end_hour'] for win in t['availability']):
                    continue
                if not all(any(win['start_hour']<=st and en<=win['end_hour'] for win in e['open_windows']) for e,st,en in ((outbound,departure,arrival),(back,delivered,returned))):
                    continue
                fixed=t['fixed_trip_cost']+sum(e['distance_km']*t['cost_per_km']+e['toll_cost'] for e in n['edges'])
                if spent+fixed>u['total_budget']+1e-8:
                    continue
                cargo={i:0 for i in ITEMS};kg=vol=0.;price=0.
                current_vol=sum(inventory[i]*u['item_volume_m3'][i]+quarantine[i]*u['item_volume_m3'][i] for i in ITEMS)
                allowed=[]
                for i in ITEMS:
                    life=l['shelf_life_days'][i]
                    if a+1e-9<(w-1)*168+roundup(l['procurement_lead_days'][i]*1440)/60:
                        continue
                    if life is not None and n['delivery_deadline_hours'][w]>=departure+math.floor(life*1440/slot)*slot/60:
                        continue
                    allowed.append(i)
                while True:
                    feasible=[]
                    for i in allowed:
                        if inventory[i]+cargo[i]+1>D[w][i]+1e-8 or bought[i]+cargo[i]+1>u['weekly_supply'][i][w]+1e-8:
                            continue
                        wk=l['item_weight_kg'][i];vk=u['item_volume_m3'][i];ck=u['unit_cost'][i]
                        if kg+wk>min(t['payload_kg'],t['max_gross_weight_kg']-t['tare_kg'],outbound['max_gross_weight_kg']-t['tare_kg'])+1e-8 or vol+vk>t['volume_m3']+1e-8:
                            continue
                        if current_vol+vol+vk>u['warehouse_capacity_m3'][site]+1e-8 or spent+fixed+price+ck>u['total_budget']+1e-8:
                            continue
                        feasible.append(i)
                    if not feasible:
                        break
                    i=min(feasible,key=lambda i:((inventory[i]+cargo[i])/D[w][i],ITEMS.index(i)))
                    cargo[i]+=1;kg+=l['item_weight_kg'][i];vol+=u['item_volume_m3'][i];price+=u['unit_cost'][i]
                if not sum(cargo.values()):
                    continue
                key=f'greedy-{w}-{len(trips)}'; cargo_lots=[]
                for i,q in cargo.items():
                    if not q:continue
                    life=l['shelf_life_days'][i]
                    exp_hour=None if life is None else departure+math.floor(life*1440/slot)*slot/60
                    exp_week=None if exp_hour is None else next((ww for ww,d in n['delivery_deadline_hours'].items() if d>=exp_hour),5)
                    lid=f'order:{i}:{w}:{key}'
                    stock.append(dict(id=lid,item=i,quantity=q,remaining=q,arrival_week=w,expiry_week=exp_week))
                    cargo_lots.append(dict(lot_id=lid,item=i,quantity=q,order_week=w,expiry_week=exp_week,expires_at=None if exp_hour is None else iso(exp_hour)))
                    orders.append(dict(item=i,quantity=q,order_week=w,dispatch_week=w,arrival_week=w,expiry_week=exp_week,route=key,trip_id=key))
                    bought[i]+=q;arrived[i]+=q;inventory[i]+=q
                trips.append(dict(trip_id=key,truck_id=t['id'],cargo=cargo,cargo_lots=cargo_lots,
                                  load_start_at=iso(a),departure_at=iso(departure),arrival_at=iso(arrival),delivery_complete_at=iso(delivered),return_at=iso(returned),available_again_at=iso(release),
                                  departure_week=w,arrival_week=w,weight_kg=kg,volume_m3=vol,
                                  outbound_edges=[outbound['id']],return_edges=[back['id']],round_trip_distance_km=sum(e['distance_km'] for e in n['edges']),transport_cost=fixed,
                                  driving_minutes=roundup(outbound['travel_minutes'])+roundup(back['travel_minutes']),
                                  timeline=[dict(kind='load',node=n['depot_node'],start_at=iso(a),end_at=iso(departure)),dict(kind='drive',phase='outbound',edge=outbound['id'],start_at=iso(departure),end_at=iso(arrival)),dict(kind='unload',node=n['destination_node'],start_at=iso(arrival),end_at=iso(delivered)),dict(kind='drive',phase='return',edge=back['id'],start_at=iso(delivered),end_at=iso(returned)),dict(kind='break',phase='depot_rest',node=n['depot_node'],start_at=iso(returned),end_at=iso(rest_end)),dict(kind='turnaround',node=n['depot_node'],start_at=iso(rest_end),end_at=iso(release))]))
                used_until[t['id']]=release;spent+=fixed+price;trip_cost+=fixed
        peak=sum((inventory[i]+quarantine[i])*u['item_volume_m3'][i] for i in ITEMS)
        warehouse.append(dict(week=w,peak_inventory_volume_m3=peak))
        used=Counter()
        for i in ITEMS:
            need=D[w][i]
            candidates=sorted((b for b in stock if b['item']==i and b['arrival_week']<=w),key=lambda b:(b['expiry_week'] or math.inf,b['id']))
            for b in candidates:
                take=min(need,b['remaining']);b['remaining']-=take;need-=take;used[i]+=take
        for b in stock:
            if b['arrival_week']>w:continue
            previous=next((p['ending_usable_inventory'] for p in reversed(lot_plan) if p['lot_id']==b['id']),0.)
            available=b['quantity'] if b['arrival_week']==w else previous
            exp=available if b['expiry_week'] is not None and w>=b['expiry_week'] else 0.
            lot_plan.append(dict(lot_id=b['id'],item=b['item'],week=w,arrival_week=b['arrival_week'],expiry_week=b['expiry_week'],quantity=b['quantity'],served=available-b['remaining']-exp,ending_usable_inventory=b['remaining'],expired_quantity=exp))
        for i in ITEMS:
            plan.append(dict(item=i,week=w,demand=D[w][i],served=used[i],unmet_demand=D[w][i]-used[i],ending_inventory=sum(b['remaining'] for b in stock if b['item']==i),expired_quantity=expired[i],disposed_quantity=disposal[i],quarantined_inventory=quarantine[i],recommended_order=bought[i],dispatched=bought[i],recommended_shipment=arrived[i]))
    procurement=sum(b['quantity']*u['unit_cost'][b['item']] for b in orders)
    return dict(plan=plan,lot_plan=lot_plan,order_plan=orders,truck_plan=trips,warehouse_summary=warehouse,
                summary=dict(total_procurement_cost=procurement,transport_cost=trip_cost,disposal_cost=disposed_cost,total_cost=procurement+trip_cost+disposed_cost),model_info=dict(solver_stages=[]))


def scenarios():
    base=fixture()
    yield 'unconstrained',base
    for budget in (0,1000,4000,8000,16000):
        u=deepcopy(base);u['total_budget']=budget;yield f'budget-{budget}',u
    for fleet in (1,2,3):
        u=fixture((100,100,100,100),fleet=fleet);yield f'fleet-{fleet}',u
    for fleet in (1,2,3):
        u=fixture((180,180,180,180),fleet=fleet);yield f'binding-fleet-{fleet}',u
    for factor in (.5,1.,2.):
        u=fixture(tuple(int(40*factor) for _ in range(4)));yield f'demand-{factor}',u
    for lead in (0,2,7,14):
        u=deepcopy(base);u['logistics']['procurement_lead_days']={i:lead for i in ITEMS};yield f'lead-{lead}',u
    for factor in (1,4,10):
        u=deepcopy(base)
        for e in u['logistics']['road_network']['edges']:e['travel_minutes']*=factor
        yield f'travel-time-factor-{factor}',u
    for life in (1,7,14,30):
        u=deepcopy(base);u['logistics']['shelf_life_days']['food']=life;yield f'food-life-{life}',u
    u=deepcopy(base)
    for e in u['logistics']['road_network']['edges']:e['open_windows']=[]
    yield 'all-roads-closed',u
    u=deepcopy(base);u['logistics']['road_network']['edges'][1]['open_windows']=[]
    yield 'return-closed',u
    u=deepcopy(base);u['logistics']['road_network']['trucks'][0]['availability']=[]
    # Empty availability is invalid input; model requires a declared window.
    u['logistics']['road_network']['trucks'][0]['availability']=[dict(start_hour=0,end_hour=1,max_driving_minutes=60)]
    yield 'truck-unavailable',u
    for capacity in (.1,1,4):
        u=deepcopy(base);u['warehouse_capacity_m3']['Medyka']=capacity;yield f'warehouse-{capacity}',u
    u=deepcopy(base)
    u['initial_inventory']['Medyka']['food']=100
    u['logistics']['shelf_life_days']['food']=30
    u['logistics']['initial_lots']=[dict(id='old-food',item='food',quantity=40,expiry_week=1),dict(id='near-food',item='food',quantity=30,expiry_week=2),dict(id='new-food',item='food',quantity=30,expiry_week=5)]
    u['logistics']['disposal_capacity']['food']={w:10 for w in range(1,5)}
    yield 'FEFO-and-quarantine',u
    u=deepcopy(base)
    for e in u['logistics']['road_network']['edges']:e['capacity_resource']='shared'
    u['logistics']['road_network']['capacity_resources']={'shared':[dict(start_hour=0,end_hour=672,max_entries=1)]}
    yield 'shared-capacity',u
    rng=random.Random(SEED+1)
    for k in range(24):
        u=fixture(tuple(rng.randint(5,70) for _ in range(4)),fleet=1+k%3)
        u['total_budget']=rng.choice((1500,4000,10000,25000))
        for i in ITEMS:
            u['weekly_supply'][i]={w:rng.randint(30,1500) if i=='water' else rng.randint(0,100) for w in range(1,5)}
        u['logistics']['procurement_lead_days']={i:rng.choice((0,2,7)) for i in ITEMS}
        u['logistics']['shelf_life_days']['food']=rng.choice((7,14,30,None))
        yield f'seeded-{k:02d}',u


def benchmarks():
    yield 'easy-same-result',fixture((10,10,10,10))
    u=fixture((100,100,100,100))
    u['logistics']['road_network']['departure_hours']=[w*168+9 for w in range(4)]
    yield 'capacity-limited',u
    u=fixture((20,20,20,20))
    for i in ITEMS:u['weekly_supply'][i]={w:100000 if w==1 else 0 for w in range(1,5)}
    yield 'one-early-supply',u
    u=fixture((10,10,60,10))
    for i in ITEMS:u['weekly_supply'][i][3]=0
    yield 'known-week3-supply-outage',u
    u=fixture((30,30,30,30));u['total_budget']=7000
    yield 'budget-limited',u
    u=fixture((30,30,30,30));u['logistics']['procurement_lead_days']={i:7 for i in ITEMS}
    yield 'seven-day-procurement',u


def write_csv(path,rows):
    if not rows:return
    keys=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader();writer.writerows(rows)


def behavior_checks(rows):
    """Check testable comparative statics on the primary objective, not average alone."""
    index={r['case']:r for r in rows if r['status']=='pass'}
    results=[]
    for group,names,direction in (
        ('budget',[f'budget-{b}' for b in (0,1000,4000,8000,16000)],-1),
        ('binding-fleet',[f'binding-fleet-{b}' for b in (1,2,3)],-1),
        ('procurement-delay',[f'lead-{b}' for b in (0,2,7,14)],1),
        ('food-shelf-life',[f'food-life-{b}' for b in (1,7,14,30)],-1),
        ('warehouse',[f'warehouse-{b}' for b in (.1,1,4)],-1)):
        if not all(name in index for name in names):continue
        values=[index[name]['worst_shortage_pct'] for name in names]
        ok=all(direction*(b-a)>=-3e-3 for a,b in zip(values,values[1:]))
        results.append(dict(group=group,passed=ok,values=values))
    for name in ('all-roads-closed','return-closed','truck-unavailable','travel-time-factor-10'):
        if name in index:
            results.append(dict(group=name,passed=index[name]['trips']==0,values=[index[name]['trips']]))
    return results


def render_report(evidence,rows):
    comparisons=evidence['comparison'];official=[r for r in rows if r['kind']=='official-geometry']
    checks=Counter()
    for a in evidence['audits']:checks.update(a['checks'])
    before_path=ROOT/'ofr_v2/results/optimization_validation_20261003/before_fix/evidence.json'
    before=json.loads(before_path.read_text(encoding='utf-8')) if before_path.exists() else None
    preserved=None if not before else all(evidence['frozen_assets'].get(k)==value for k,value in before['frozen_assets'].items() if k!='ofr_v2/app/backend/logistics.py')
    forecast_keys=lambda k: any(part in k for part in ('/app/models/','/app/data/','/pipeline/')) or k.endswith('weekly_forecast.py') or k.endswith(('model_selection.md','holdout_metrics.txt','validation_metrics.txt','ablation_metrics.txt'))
    forecast_preserved=None if not before else all(evidence['frozen_assets'].get(k)==v for k,v in before['frozen_assets'].items() if forecast_keys(k))
    changed=[] if not before else [k for k,v in before['frozen_assets'].items() if evidence['frozen_assets'].get(k)!=v]
    evidence['pre_fix_forecast_and_other_assets_unchanged']=preserved
    evidence['pre_fix_forecast_artifacts_data_pipeline_unchanged']=forecast_preserved
    evidence['pre_fix_changed_asset_paths']=changed
    verdict = ('선언된 입력·후보 범위 안의 수학적 일관성과 계획 설명 가능성을 확인했다.'
               if not evidence['failures'] else '검증 실패가 있어 일관성 확인을 완료하지 못했다. 아래 실패 기록을 검토해야 한다.')
    lines=[f"# 최적화 모델 검증 보고서 — {evidence['generated_at'][:10]}",'',
           f'**판정: {verdict} 실제 기관 운영 효과 또는 현장 배차 적합성까지 입증한 것은 아니다.**','',
           '예측 모델은 불러오거나 학습하지 않았다. 입력 유입량은 고정된 합성 시나리오다. 최초 ZIP과 기존 예측 산출물은 유지한다. 업그레이드 채택·배포·main 병합은 수행하지 않았다.','',
           '## 검증 범위와 결과','',
           f"- 계산/기준선 사례 {len(rows)}개 중 {evidence['passed']}개 통과, 실패 {len(evidence['failures'])}개.",
           f"- 독립 전수 열거 {len(evidence['enumeration'])}개 문제, 총 {sum(x['assignments'] for x in evidence['enumeration']):,}개 조합을 조사; 해당 모드의 목적값 일치 {sum(x['matched'] for x in evidence['enumeration'])}/{len(evidence['enumeration'])}개. 공정성 모드는 최대 부족률/정규화 부족/비용, 효율 모드는 정규화 부족/비용을 비교.",
           f"- 최적화 모듈 내부 함수를 사용하지 않는 공개 출력 재계산: {sum(checks.values()):,}개 스칼라 검사. 이 검사 수는 독립 표본 수나 정확도 퍼센트가 아니다.",
           f"- 정상 계획의 화물·도로·비용·재고·수요·출발·중복배차·구매량을 손상시킨 변조 탐지 {sum(x['detected'] for x in evidence['mutations'])}/{len(evidence['mutations'])}개.",
           f"- 공식 도로 선형 {len(official)}개 창고–구호소 조합의 왕복 계획과 지오데식 길이 재계산을 확인.",
           f"- 실행 중 고정 자산 해시 유지: {evidence['frozen_assets_unchanged']}. 과거 수정 전 대비 예측 모델·데이터·학습 파이프라인 및 weekly_forecast 파일 유지: {forecast_preserved}.",
           f"- 과거 수정 전 대비 최적화/API 코드까지 포함한 전체 비교(logistics.py 제외): {preserved}. 변경 경로: {', '.join(changed) or '없음 또는 기준 기록 미확보'}. 이는 의도한 최적화/API 수정과 예측 자산 변화를 구분한 기록이다.",
           '', '별도 검사 항목: 수요 변환/보존, 배치 물질수지, 재고·입고 연결, FEFO, 만료 후 지급 차단, 격리·폐기, 공급 한도, 총비용·예산, 창고 피크, 트럭 중량/부피/총중량, 연결된 왕복 도로, 조달 완료 전 상차 금지, 주간 납기, 시간표·차량 점유, 휴식·운전 한도, 폐쇄창/공유 진입 용량, 솔버 상태와 이전 목적값 잠금. 검사와 엔진이 같은 잘못된 업무 정의를 공유할 가능성까지 제거한 외부 감사는 아니다.',
           '', '## 발견한 결함과 수정','',
           f"수정 전 동일 기본 실험은 {before['optimizer_cases'] if before else '기록 없음'}개 중 {len(before['failures']) if before else '?'}개에서 실패했다. 차량 2~3대, 14일 조달 및 혼합 조건에서 후속 목적 단계가 infeasible로 종료됐다.",
           'HiGHS가 정수 변수를 2.9999996처럼 반환할 수 있는데 원시 목적값으로 다음 단계를 잠그면 정수 3을 배제했다. 모든 단계에서 정수 좌표를 반올림한 뒤 목적값을 다시 계산해 잠그도록 수정했다. 물리 제약, 목표 순서, objective_tolerance=1e-7, MIP 상대 gap=1e-6은 유지했다. 원시/정수 반영 목적값 차이를 solver_stages에 기록하고 마지막 물리 제약 검사를 유지한다. 시간 제한 incumbent을 최적해로 받아들이지 않는 회귀 검사도 추가했다.',
           '수정 전 실패 원본은 [당시 실패 기록](../optimization_validation_20261003/before_fix/evidence.json), 이번 실행 결과는 `evidence.json`이다. 성공 결과만 선택해 보고하지 않았다.',
           '', '## 같은 운영 조건의 기준선 비교','',
           '기준선은 매주 현재 부족분만 주문하고 품목 충족 비율이 낮은 순으로 1단위씩 적재하는 별도 Python 규칙이다. 같은 차량·출발시각·물품중량/부피·공급·예산·창고·조달·기한·휴식 가정을 사용하며 기준선 출력도 같은 독립 검사에 통과했다. 향후 필요량을 미리 조달하지 않는다. 실제 기관의 운영 규칙을 관찰한 기준선이 아니고, 이 합성 사례 평균을 현장 개선율로 발표하면 안 된다.',
           '비교의 기본 물류 조건: 이용률 20%, 체류 1일, 품목 중량 1.02/0.6/0.5/1.5 kg, 부피 0.001/0.002/0.01/0.02 m³, 단가 1/10/25/30, 기본 창고 100 m³, 초기 재고 0, 비교표에서는 기간 내 만료를 가정하지 않음(shelf_life_days=null). 단위별 중량·부피·단가·이용률은 합성값이다. 차량 1235 kg/11.5 m³는 제조사 제원 기반이고, 직접 왕복 40 km·편도 30분·운행당 60의 합성 도로/시간/비용과 월·목 출발을 사용했다. 조건별 예산·공급·조달·출발 후보 변경값은 synthetic_inputs.json에 전부 저장했다. 이 직접 경로 기준선 비교를 실제 폴란드 도로 운행 성과로 바꾸어 발표하지 않는다.',
           '', '| 조건 | 현재 주 부족분 규칙 충족률 | 공동 최적화 충족률 | 규칙 / 최적화 최대 부족률 | 규칙 / 최적화 총비용 |','|---|---:|---:|---:|---:|']
    labels={'easy-same-result':'충분한 자원','capacity-limited':'주 1회 적재 용량 부족','one-early-supply':'1주차에만 공급 가능','known-week3-supply-outage':'3주차 공급 중단이 사전에 알려짐','budget-limited':'예산 제한','seven-day-procurement':'조달 7일'}
    for r in comparisons:
        lines.append(f"| {labels[r['case']]} | {r['greedy_fulfillment_pct']:.2f}% | {r['milp_fulfillment_pct']:.2f}% | {r['greedy_worst_shortage_pct']:.2f}% / {r['milp_worst_shortage_pct']:.2f}% | {r['greedy_cost']:.2f} / {r['milp_cost']:.2f} |")
    lines += ['', '충족률은 물 L, 식량 일분, 키트/담요 개를 단순 합산하지 않고 품목별 총수요로 정규화한 평균이다. 최우선 목적은 최대 품목/주 부족률이며 평균만 좋아졌다고 우월하다고 판정하지 않는다. 비용 최소화는 충족 목적을 먼저 고정한 후 수행하므로 더 많이 지급하는 계획이 더 비쌀 수 있다. 이 실험은 고정 4주 계획 비교이며 실제 수요 관찰에 따른 롤링 재계획이나 현장 실적 비교가 아니다.',
              '', '## 스트레스와 입력 변화','']
    behavior_labels={
        'budget':('예산 0 / 1000 / 4000 / 8000 / 16000','최대 부족률 %'),
        'binding-fleet':('주당 180명 조건, 차량 1 / 2 / 3대','최대 부족률 %'),
        'procurement-delay':('조달 0 / 2 / 7 / 14일','최대 부족률 %'),
        'food-shelf-life':('식량 수명 1 / 7 / 14 / 30일','최대 부족률 %'),
        'warehouse':('창고 0.1 / 1 / 4 m³','최대 부족률 %'),
        'all-roads-closed':('모든 도로 폐쇄','운행 수'),
        'return-closed':('복귀 도로 폐쇄','운행 수'),
        'truck-unavailable':('차량 사용 불가','운행 수'),
        'travel-time-factor-10':('편도 시간 10배, 연속 운전 한도 초과','운행 수'),
    }
    for item in evidence['behavior']:
        label,metric=behavior_labels[item['group']]
        lines.append(f"- {label}: {'통과' if item['passed'] else '실패'}, {metric} {', '.join(f'{x:.3f}' for x in item['values'])}.")
    lines += ['', '24개 추가 조합은 seed=20261004를 고정한 공급/수요/예산/조달/기한 사례다. 현장 확률분포에서 뽑은 표본이나 통계적 신뢰구간이 아니다. 도로 폐쇄·차량 고장 항목은 해당 조건을 알고 재계산했을 때의 동작이며 운행 중 사고에 대한 자동 대응을 입증하지 않는다.',
              '', '## 공식 도로를 사용한 입력 적합성','',
              '| 출발 후보–도착지 | 계획 왕복 거리 합 km | 계산·검사 초 | 별도 재계산 길이 최대 차 km |','|---|---:|---:|---:|']
    for r in official:lines.append(f"| {r['case']} | {r['distance_km']:.3f} | {r['seconds']:.2f} | {r['geodesic_error_km']:.9f} |")
    lines += ['', '거리 합은 한 번의 편도 거리가 아니라 선택된 모든 운행의 왕복 합이다. 계산·검사 시간은 그래프 로딩/구축 이후의 최적화와 공개 결과 검사 시간이며 전체 UI 응답 시간이 아니다. 원자료는 보존된 GUGiK 도로·UUG 주소이며 SHA256 확인 후 사용한다. 출력 좌표를 같은 pyproj.Geod 라이브러리로 별도 재계산해 경로 길이의 전달·합산을 검산했다. 거리 알고리즘 자체의 독립 검증이나 실측/GPS 비교는 아니다. 두 후보 창고의 현재 운영·일방통행·시설 진입·현장 시간은 확인하지 않았다. 공식 선형을 사용하는 것과 트럭 통행 적합성 검증은 다르다. 모든 결과의 operational_ready=false를 유지한다.',
              '', '## 현실에서 설명 가능한 부분과 아직 입증하지 못한 부분','',
              '| 주장 | 이번 증거로 말할 수 있는 범위 |','|---|---|',
              '| 주문·운송·재고를 따로 계산한 얄팍한 모델인가? | 화물과 개별 차량 왕복 점유를 배치별 재고·만료·예산과 공동 계산하고 공개 결과를 별도로 대사한다. 작은 정수 문제의 정답도 일치한다. |',
              '| 실제 구호 물류 개념에 맞는가? | WFP의 차량 용량/운행 일정, 조달 리드타임, FEFO·만료 격리 개념과 대응된다. 기관이 이 모델을 인증하거나 검수한 것은 아니다. |',
              '| 어떤 때 추가 복잡성이 필요한가? | 공급 시점·조달 지연·적재/예산 부족이 있을 때 선조달/비축과 공동 적재가 단순 규칙보다 도움이 되는 합성 사례를 제시했다. 쉬운 사례의 동률도 공개했다. |',
              '| 현장 비용·ETA·수요 정확도가 검증됐는가? | 아니다. 제품 포장, 이용률·체류기간, 실제 계약 리드타임/단가, 교통·운행 기록이 없다. |',
              '| 폴란드 전국의 최적 경로인가? | 아니다. 간편 UI는 수집한 지역 그래프의 k=1 최단거리와 월/목 출발 후보에 한정된다. 휴식 시점도 고정 정책이다. |',
              '| 어느 규모까지 실용적인가? | 여기서 시험한 유한 사례만 말할 수 있다. 전국·다구호소 공유 자원·고밀도 출발 격자는 이번 실험의 범위 밖이다. |',
              '', '## 공식·1차 근거','',
              '- [WFP 연구: The Nutritious Supply Chain](https://pubsonline.informs.org/doi/10.1287/ijoo.2019.0047), §3.5: 기존 운영 비용 대사·기준 계획 비교·사용자 검토를 통한 검증 방법. 우리 프로젝트 운영 효과의 근거로 전용하지 않는다.',
              '- [WFP Logistics Cluster: Sending Goods by Road](https://log.logcluster.org/en/sending-goods-road): 용량·근무시간·경로·평균속도·처리시간을 고려한 운행 계획.',
              '- [WFP Logistics Cluster: Procurement](https://log.logcluster.org/en/procurement): 조달 개념과 리드타임.',
              '- [WFP Logistics Cluster: Physical Storage Guidelines](https://log.logcluster.org/en/physical-storage-guidelines): FEFO와 만료품 분리.',
              '- [SciPy milp 공식 문서](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.milp.html): status와 MIP gap의 의미.',
              '- 차량 제조사·GUGiK/UUG 원문과 취득 내역은 `../../docs/road_ui_integration.md`, `../../docs/poland_road_data.md`에 보존. 문서 확인일 2026-10-03.',
              '', '## 재현과 제출 자료','',
              '```powershell','python scripts/validate_optimizer.py','python -m pytest ofr_v2/tests -q','```','',
              '`cases.csv`: 모든 사례/시간/충족률/비용, `baseline_comparison.csv`: 같은 조건 기준선, `synthetic_inputs.json`: 입력 전체, `evidence.json`: 해시·독립 검사·전수 열거·변조 검증, `example_synthetic_result.json` 및 `example_official_result.json`: 실제 출력 예시. 선택적으로 `--quick --skip-official`은 개발용 축소 검사이며 전체 결과와 구분한다.',
              '', '**팀 의사결정에 사용할 결론:** 제한된 입력과 후보 범위에서 공동 물류 계획을 설명·검산할 수 있는 연구용 운영 지원 모델이다. 현장 운영 인증·실측 비용 절감·현재 폴란드 배송 가능성을 증명했다고 발표하지 않는다. 실제 기록을 확보하면 동일 검사/비교 틀에 입력을 교체하고 별도 시범 평가를 진행할 수 있다.','']
    if evidence['failures']:
        lines += ['## 이번 실행의 실패 기록','', '```json', json.dumps(evidence['failures'],ensure_ascii=False,indent=2), '```','']
    (OUTPUT/'report.md').write_text('\n'.join(lines),encoding='utf-8')


def main():
    global OUTPUT
    parser=argparse.ArgumentParser();parser.add_argument('--quick',action='store_true');parser.add_argument('--skip-official',action='store_true')
    parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args();OUTPUT=args.output
    OUTPUT.mkdir(parents=True,exist_ok=True)
    frozen=frozen_assets();rows=[];audits=[];saved=[];oracle=[];comparison=[];failures=[];mutations=[]
    def evaluate(name,u,kind,fn=solve):
        at=time.perf_counter()
        try:
            result=fn(u);a=audit(u,result)
            row=dict(case=name,kind=kind,status='pass' if a['passed'] else 'audit-failure',seconds=time.perf_counter()-at,checks=a['total_checks'],**public_metrics(u,result))
            if not a['passed']:failures.append(dict(case=name,failures=a['failures']))
            audits.append(dict(case=name,**a));rows.append(row)
            print(f'{kind} {name}: {row["status"]}, {row["seconds"]:.2f}s, {row["fulfillment_pct"]:.1f}%',flush=True)
            return result,row
        except Exception as e:
            rows.append(dict(case=name,kind=kind,status='error',seconds=time.perf_counter()-at,error=str(e)))
            failures.append(dict(case=name,error=str(e)));print(f'ERROR {name}: {e}',flush=True)
            return None,None
    for name,u in oracle_cases(8 if args.quick else 48):
        expected,count=enumerated_truth(u);r,row=evaluate(name,u,'enumeration')
        if r:
            actual=score(u,r);ok=all(abs(a-b)<3e-5 for a,b in zip(expected,actual))
            oracle.append(dict(case=name,matched=ok,assignments=count,expected=expected,actual=actual))
            if not ok:failures.append(dict(case=name,oracle=expected,actual=actual))
    for k,(name,u) in enumerate(scenarios()):
        if args.quick and k>=6:break
        r,row=evaluate(name,u,'stress')
        saved.append(dict(case=name,request=u))
        if name=='unconstrained' and r:
            mutations=mutation_checks(u,r)
            (OUTPUT/'example_synthetic_result.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
            if not all(x['detected'] for x in mutations):failures.append(dict(mutation_failures=mutations))
    for name,u in benchmarks():
        r,row=evaluate(name,u,'optimized')
        b,br=evaluate(name+'-greedy',u,'greedy',greedy)
        if r and b:
            comparison.append(dict(case=name,**{'milp_'+k:v for k,v in public_metrics(u,r).items()},**{'greedy_'+k:v for k,v in public_metrics(u,b).items()}))
            a=score(u,r);other=score(u,b)
            if a[0]>other[0]+3e-5:failures.append(dict(case=name,error='MILP worse on primary objective than feasible heuristic'))
        saved.append(dict(case='benchmark-'+name,request=u))
    if not args.skip_official:
        for warehouse in ('przemysl-lwowska-36','przemysl-wodna-11'):
            for site in ('Medyka','Korczowa','Dorohusk'):
                u=fixture((30,30,30,30),site)
                common={k:u['logistics'][k] for k in COMMON}
                logistics,metadata=build_ui_logistics(common,dict(warehouse_id=warehouse,truck_count=1,reference_date='2026-01-26'),site)
                u['logistics']=logistics
                r,row=evaluate(warehouse+'-'+site,u,'official-geometry')
                if r:
                    from pyproj import Geod
                    geod=Geod(ellps='WGS84');max_error=0.
                    for trip in r['truck_plan']:
                        lengths=[]
                        for segment in trip['outbound_geometry']+trip['return_geometry']:
                            pts=segment['coordinates'];lengths.append(geod.line_length([p[0] for p in pts],[p[1] for p in pts])/1000)
                        max_error=max(max_error,abs(sum(lengths)-trip['round_trip_distance_km']))
                    row['geodesic_error_km']=max_error;row['source_documents']=len(logistics['road_network']['sources']);row['operational_ready']=r['model_info']['operational_ready']
                    if max_error>1e-4:failures.append(dict(case=row['case'],geometry_error=max_error))
                    if warehouse=='przemysl-lwowska-36' and site=='Medyka':
                        (OUTPUT/'example_official_result.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
                # Avoid retaining full large official graphs/results for all sites.
                del u,logistics,r
    after=frozen_assets()
    unchanged=frozen==after
    if not unchanged:failures.append(dict(error='Frozen forecast/engine assets changed'))
    write_csv(OUTPUT/'cases.csv',rows);write_csv(OUTPUT/'baseline_comparison.csv',comparison)
    (OUTPUT/'synthetic_inputs.json').write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
    behavior=behavior_checks(rows)
    for check in behavior:
        if not check['passed']:failures.append(dict(behavior_failure=check))
    evidence=dict(seed=SEED,quick=args.quick,official_skipped=args.skip_official,generated_at=datetime.now(timezone.utc).isoformat(),frozen_assets=frozen,frozen_assets_unchanged=unchanged,
                  optimizer_cases=len(rows),passed=sum(r['status']=='pass' for r in rows),failures=failures,
                  enumeration=oracle,mutations=mutations,audits=audits,comparison=comparison,behavior=behavior)
    render_report(evidence,rows)
    (OUTPUT/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Completed: {len(rows)} cases, {len(failures)} failures; frozen assets unchanged={unchanged}',flush=True)
    return 1 if failures else 0


if __name__=='__main__':
    raise SystemExit(main())

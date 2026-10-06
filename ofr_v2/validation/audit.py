"""Independent public-output audit. No optimizer/Graph/Model helpers are imported.

This checks consistency with declared inputs, not truth of field parameters.
Units, weekly deadlines and FEFO are checked from the published request/result.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import math

ITEMS = ('water', 'food', 'hygiene_kit', 'blanket')
DISCRETE = set(ITEMS[1:])
TOL = 2e-5


def demand(forecast, utilization, stay):
    out = {}
    for w, value in forecast.items():
        n = int((Decimal(str(value))*Decimal(str(utilization))).to_integral_value(rounding=ROUND_CEILING))
        out[int(w)] = dict(water=n*stay*15, food=n*stay, hygiene_kit=n, blanket=n)
    return out


def audit(request, result):
    """Return failures and number of explicit scalar checks; never call the solver."""
    errors, checks = [], Counter()
    def check(group, condition, detail):
        checks[group] += 1
        if not condition:
            errors.append(f'{group}: {detail}')
    def near(group, a, b, detail):
        check(group, math.isfinite(float(a)) and abs(a-b) <= TOL, detail)
    u, l = request, request['logistics']
    n = l['road_network']
    site = u['selected_site']
    expected = demand(u['ml_forecast'][site], u['utilization_rate'], u['stay_days'])
    rows = {(p['item'], p['week']):p for p in result['plan']}
    check('schema', len(rows)==16 and len(result['plan'])==16, 'exactly four items x four weeks')
    edges = {e['id']:e for e in n['edges']}
    trucks = {t['id']:t for t in n['trucks']}
    nodes = {p['id']:p for p in n['nodes']}
    start = datetime.fromisoformat(n['planning_start']).astimezone(timezone.utc)
    hour = lambda value: (datetime.fromisoformat(value).astimezone(timezone.utc)-start).total_seconds()/3600
    slot = n.get('slot_seconds', n['slot_minutes']*60)/60
    rounded = lambda minutes: math.ceil(minutes/slot-1e-9)*slot
    deadlines = {int(w):float(h) for w,h in n['delivery_deadline_hours'].items()}
    lots = defaultdict(dict)
    for p in result['lot_plan']:
        check('schema', p['week'] not in lots[p['lot_id']], 'duplicate lot/week')
        lots[p['lot_id']][p['week']] = p
    fixed = {b['id']:b for kind in ('initial_lots','pipeline_lots') for b in l[kind]}
    cargo_meta, dispatched = {}, Counter()
    occupied, drive_windows, weekly_drive, entry = defaultdict(list), Counter(), Counter(), Counter()
    transport_cost = 0.
    trips = result['truck_plan']
    check('schema', len({p['trip_id'] for p in trips})==len(trips), 'duplicate tour ID')
    for p in trips:
        tid = p['truck_id']
        check('truck', tid in trucks, 'unknown truck')
        if tid not in trucks:
            continue
        t = trucks[tid]
        h = {k:hour(p[k]) for k in ('load_start_at','departure_at','arrival_at','delivery_complete_at','return_at','available_again_at')}
        check('schedule', h['departure_at'] in n['departure_hours'], 'departure outside declared grid')
        near('schedule', (h['departure_at']-h['load_start_at'])*60, rounded(t['loading_minutes']), 'loading duration')
        near('schedule', (h['delivery_complete_at']-h['arrival_at'])*60, rounded(t['unloading_minutes']), 'unloading duration')
        turnaround=[e for e in p['timeline'] if e['kind']=='turnaround']
        if turnaround:
            near('schedule', (hour(turnaround[0]['end_at'])-hour(turnaround[0]['start_at']))*60, rounded(t['turnaround_minutes']), 'turnaround duration')
            near('schedule', hour(turnaround[0]['end_at']), h['available_again_at'], 'release after turnaround')
        else:
            near('schedule', (h['available_again_at']-h['return_at'])*60, rounded(t['turnaround_minutes']), 'turnaround duration')
        check('schedule', list(h.values())==sorted(h.values()), 'nonmonotonic times')
        occupied[tid].append((h['load_start_at'],h['available_again_at']))
        ws = [k for k,w in enumerate(t['availability']) if w['start_hour']-TOL<=h['load_start_at'] and h['available_again_at']<=w['end_hour']+TOL]
        rests = [e for e in p['timeline'] if e['kind']=='daily_rest']
        if rests:
            check('rest', t.get('allow_overnight_return',False) and len(rests)==1, 'overnight permission/count')
            r=rests[0]; a,b=hour(r['start_at']),hour(r['end_at'])
            first=[k for k,w in enumerate(t['availability']) if w['start_hour']-TOL<=h['load_start_at'] and a<=w['end_hour']+TOL]
            check('rest', r['node']==n['destination_node'] and 11-TOL<=b-a<=36+TOL, 'destination daily rest 11..36h')
            near('rest', a,h['delivery_complete_at'],'rest after delivery')
            check('schedule', len(first)==1 and first[0]+1<len(t['availability']), 'two consecutive duties required')
            if len(first)==1 and first[0]+1<len(t['availability']):
                next_window=t['availability'][first[0]+1]
                near('rest', b,next_window['start_hour'],'return starts at next duty')
                check('schedule', h['available_again_at']<=next_window['end_hour']+TOL,'return released within next duty')
        else:
            check('schedule', len(ws)==1, 'tour does not fit exactly one duty window')
        if 'overnight_return' in p:
            check('rest', p['overnight_return']==bool(rests),'reported overnight flag')
        weight = sum(p['cargo'][i]*l['item_weight_kg'][i] for i in ITEMS)
        volume = sum(p['cargo'][i]*u['item_volume_m3'][i] for i in ITEMS)
        near('truck', p['weight_kg'], weight, 'reported cargo weight')
        near('truck', p['volume_m3'], volume, 'reported cargo volume')
        check('truck', weight<=t['payload_kg']+TOL and weight+t['tare_kg']<=t['max_gross_weight_kg']+TOL, 'payload/gross capacity')
        check('truck', volume<=t['volume_m3']+TOL, 'volume capacity')
        for i,q in p['cargo'].items():
            check('integrality', q>=-TOL and (i not in DISCRETE or abs(q-round(q))<=TOL), 'cargo integrality/nonnegative')
            near('cargo', q, sum(b['quantity'] for b in p['cargo_lots'] if b['item']==i), 'cargo = purchased lots')
            dispatched[i,p['departure_week']] += q
        for b in p['cargo_lots']:
            check('schema', b['lot_id'] not in cargo_meta, 'purchased lot split across trips')
            cargo_meta[b['lot_id']] = b
            ready = (b['order_week']-1)*168 + rounded(l['procurement_lead_days'][b['item']]*1440)/60
            check('lead', h['load_start_at']+TOL>=ready, 'loading before supplier ready')
            if b['expires_at'] is not None:
                expiry = h['departure_at']+math.floor(l['shelf_life_days'][b['item']]*1440/slot+1e-9)*slot/60
                near('expiry', hour(b['expires_at']), expiry, 'shelf clock starts at dispatch')
                check('expiry', deadlines[p['arrival_week']]<expiry-TOL, 'deadline not before expiry')
        correct_week = next((w for w,d in deadlines.items() if h['delivery_complete_at']<=d+TOL), None)
        check('deadline', correct_week==p['arrival_week'], 'wrong arrival bucket')
        costs = t['fixed_trip_cost']
        distance = 0.
        for phase,field,origin,target in (('outbound','outbound_edges',n['depot_node'],n['destination_node']),('return','return_edges',n['destination_node'],n['depot_node'])):
            current = origin
            for eid in p[field]:
                check('path', eid in edges, 'unknown edge')
                if eid not in edges:
                    continue
                e = edges[eid]
                check('path', e['from_node']==current, 'disconnected path')
                current=e['to_node']
                distance += e['distance_km']
                costs += e['toll_cost']+e['distance_km']*t['cost_per_km']
                check('road', t['height_m']<=e['max_height_m']+TOL and t['width_m']<=e['max_width_m']+TOL, 'vehicle dimensions')
                check('road', t['vehicle_type'] in e['allowed_vehicle_types'], 'vehicle type restriction')
                check('road', t['tare_kg']+(weight if phase=='outbound' else 0)<=e['max_gross_weight_kg']+TOL, 'edge gross weight')
                if phase=='outbound':
                    check('road', all(q<=TOL or i in e['allowed_items'] for i,q in p['cargo'].items()), 'item restriction')
            check('path', current==target, 'wrong path endpoint')
        near('cost', p['round_trip_distance_km'], distance, 'round-trip km')
        rest_hours=sum(hour(e['end_at'])-hour(e['start_at']) for e in rests)
        billable=h['return_at']-h['load_start_at']-rest_hours
        components=dict(fixed=t['fixed_trip_cost'],distance=distance*t['cost_per_km'],
                        time=billable*t.get('cost_per_hour',0),overnight=t.get('overnight_cost',0) if rests else 0,
                        toll=costs-t['fixed_trip_cost']-distance*t['cost_per_km'])
        components['minimum_adjustment']=max(0,t.get('minimum_trip_cost',0)-sum(components[k] for k in ('fixed','distance','time')))
        costs=sum(components.values())
        if 'billable_hours' in p: near('cost',p['billable_hours'],billable,'billable on-duty hours')
        if 'cost_breakdown' in p:
            check('cost',set(p['cost_breakdown'])==set(components),'cost component keys')
            for k,v in components.items(): near('cost',p['cost_breakdown'].get(k,math.inf),v,k)
        near('cost', p['transport_cost'], costs, 'trip cost from edges')
        transport_cost += costs
        continuous, driving = 0., 0.
        actual_edges = {'outbound':[], 'return':[]}
        previous_end = h['load_start_at']
        for event in p['timeline']:
            a,b = hour(event['start_at']),hour(event['end_at'])
            check('schedule', a>=previous_end-TOL and b>=a-TOL, 'timeline overlap/order')
            previous_end=b
            if event['kind'] in ('break','daily_rest'):
                required=660 if event['kind']=='daily_rest' else rounded(t['break_minutes'])
                check('rest', nodes[event['node']]['rest_allowed'] and (b-a)*60+TOL>=required, 'break place/duration')
                continuous=0.
            if event['kind']!='daily_rest':
                duties=[k for k,w in enumerate(t['availability']) if w['start_hour']-TOL<=a and b<=w['end_hour']+TOL]
                check('schedule',len(duties)==1,'working event outside duty')
            if event['kind']!='drive':
                continue
            e=edges[event['edge']]
            actual_edges[event['phase']].append(event['edge'])
            minutes=(b-a)*60
            near('schedule', minutes, rounded(e['travel_minutes']), 'rounded edge travel time')
            check('road', any(w['start_hour']-TOL<=a and b<=w['end_hour']+TOL for w in e['open_windows']), 'edge traversal outside open window')
            continuous+=minutes; driving+=minutes
            if len(duties)==1: drive_windows[tid,duties[0]]+=minutes
            check('rest', continuous<=t['max_continuous_driving_minutes']+TOL, 'continuous driving limit')
            if e['capacity_resource']:
                entry[e['capacity_resource'],round(a,9)]+=1
            for w in range(1,5):
                weekly_drive[tid,w]+=max(0,min(b,w*168)-max(a,(w-1)*168))*60
        check('path', actual_edges['outbound']==p['outbound_edges'] and actual_edges['return']==p['return_edges'], 'timeline/route disagree')
        near('schedule', p['driving_minutes'], driving, 'driving duration')
    for tid,intervals in occupied.items():
        intervals.sort()
        check('occupancy', all(intervals[k][0]>=intervals[k-1][1]-TOL for k in range(1,len(intervals))), 'truck reused before release')
    for (tid,k),v in drive_windows.items():
        check('rest', v<=trucks[tid]['availability'][k]['max_driving_minutes']+TOL, 'duty-window driving')
    for tid,t in trucks.items():
        for w in range(1,5):
            check('rest', weekly_drive[tid,w]<=t['max_weekly_driving_minutes']+TOL, 'weekly driving')
            check('rest', weekly_drive[tid,w]+weekly_drive[tid,w+1]<=t['max_two_week_driving_minutes']+TOL, 'two-week driving')
    for (rid,at),value in entry.items():
        cap=next((w['max_entries'] for w in n['capacity_resources'][rid] if w['start_hour']-TOL<=at<w['end_hour']-TOL),0)
        check('road_capacity', value<=cap, 'shared entries including empty returns')
    orders = Counter()
    purchase = 0.
    for b in result['order_plan']:
        orders[b['item'],b['order_week']]+=b['quantity']
        purchase+=b['quantity']*u['unit_cost'][b['item']]
        check('cargo', b['trip_id'] in {p['trip_id'] for p in trips}, 'order missing trip')
    near('cost', purchase, sum(b['quantity']*u['unit_cost'][b['item']] for b in cargo_meta.values()), 'order/truck procurement reconciliation')
    disposal_cost=0.
    peaks=Counter()
    for i in ITEMS:
        for w in range(1,5):
            p=rows[i,w]
            ds=[b[w] for b in lots.values() if w in b and b[w]['item']==i]
            near('demand', p['demand'], expected[w][i], 'declared demand conversion')
            near('demand', p['served']+p['unmet_demand'], expected[w][i], 'served + unmet')
            near('stock', p['served'], sum(b['served'] for b in ds), 'lot/item served')
            near('stock', p['ending_inventory'], sum(b['ending_usable_inventory'] for b in ds), 'lot/item inventory')
            near('expiry', p['expired_quantity'], sum(b['expired_quantity'] for b in ds), 'expired reconciliation')
            near('supply', p['recommended_order'], orders[i,w], 'weekly order reconciliation')
            check('supply', orders[i,w]<=float(u['weekly_supply'][i].get(w,u['weekly_supply'][i].get(str(w),0)))+TOL, 'weekly supplier quota')
            near('cargo', p['dispatched'], dispatched[i,w], 'dispatch reconciliation')
            arrivals=sum(b['quantity'] for b in ds if b['arrival_week']==w and b['lot_id'] not in {x['id'] for x in l['initial_lots']})
            near('stock', p['recommended_shipment'], arrivals, 'arrivals reconciliation')
            prev=rows[i,w-1]['quarantined_inventory'] if w>1 else 0
            near('expiry', prev+p['expired_quantity']-p['disposed_quantity'], p['quarantined_inventory'], 'quarantine flow')
            check('expiry', -TOL<=p['disposed_quantity']<=l['disposal_capacity'][i].get(w,l['disposal_capacity'][i].get(str(w),0))+TOL, 'disposal capacity')
            disposal_cost+=p['disposed_quantity']*l['disposal_cost'][i]
            peaks[w]+=p['quarantined_inventory']*u['item_volume_m3'][i]
            for field in ('served','ending_inventory','unmet_demand','expired_quantity','disposed_quantity','quarantined_inventory','recommended_order'):
                check('integrality', p[field]>=-TOL and (i not in DISCRETE or abs(p[field]-round(p[field]))<=TOL), field)
    ranks={}
    for lid,history in lots.items():
        b=next(iter(history.values()))
        q=b['quantity']
        origin=fixed.get(lid,cargo_meta.get(lid))
        check('schema', origin is not None, 'lot has no input or purchase origin')
        if origin is None:
            continue
        near('stock', q, origin['quantity'], 'lot quantity')
        expiry=b['expiry_week']
        ranks[lid]=hour(cargo_meta[lid]['expires_at']) if lid in cargo_meta and cargo_meta[lid]['expires_at'] else (deadlines.get(expiry,deadlines[4]+(expiry-4)*168) if expiry is not None else math.inf)
        previous=0.
        for w,p in sorted(history.items()):
            available=q if w==p['arrival_week'] else previous
            near('stock', available, p['served']+p['ending_usable_inventory']+p['expired_quantity'], 'batch material balance')
            check('expiry', p['served']<=TOL or (w>=p['arrival_week'] and (expiry is None or w<expiry)), 'use before arrival/after expiry')
            if expiry is None or w<expiry:
                peaks[w]+=available*u['item_volume_m3'][p['item']]
            previous=p['ending_usable_inventory']
    for w in range(1,5):
        for lid,history in lots.items():
            later=history.get(w)
            if later is None or later['served']<=TOL:
                continue
            for earlier_id,earlier_history in lots.items():
                earlier=earlier_history.get(w)
                if earlier and earlier['item']==later['item'] and ranks.get(earlier_id,math.inf)<ranks.get(lid,math.inf):
                    check('FEFO', earlier['ending_usable_inventory']<=TOL, 'later lot used before earlier lot exhausted')
        reported=next(x for x in result['warehouse_summary'] if x['week']==w)
        near('warehouse', reported['peak_inventory_volume_m3'], peaks[w], 'peak = usable before distribution + retained quarantine')
        check('warehouse', peaks[w]<=u['warehouse_capacity_m3'][site]+TOL, 'warehouse capacity')
    s=result['summary']
    for field,value in (('total_procurement_cost',purchase),('transport_cost',transport_cost),('disposal_cost',disposal_cost),('total_cost',purchase+transport_cost+disposal_cost)):
        near('cost', s[field], value, field)
    check('budget', purchase+transport_cost+disposal_cost<=u['total_budget']+TOL, 'total budget')
    totals={i:sum(rows[i,w]['demand'] for w in range(1,5)) for i in ITEMS}
    weighted=sum(rows[i,w]['unmet_demand']/totals[i] for i in ITEMS if totals[i] for w in range(1,5))
    worst=max((p['unmet_demand']/p['demand'] for p in rows.values() if p['demand']),default=0.)
    measured=dict(stage_1_max_unmet_rate=worst,stage_2_weighted_unmet_objective=weighted,
                  stage_3_total_cost=purchase+transport_cost+disposal_cost,stage_5_trip_tiebreak=len(trips),
                  stage_6_driving_tiebreak=sum(p['driving_minutes']/slot for p in trips),
                  stage_7_departure_tiebreak=sum(hour(p['departure_at'])*60/slot for p in trips))
    for stage in result['model_info']['solver_stages']:
        check('solver', stage['status']==0 and (stage['mip_gap'] is None or stage['mip_gap']<=1e-6+1e-12), 'status/gap')
        if stage['stage'] in measured:
            check('objective_locks', measured[stage['stage']]<=stage['objective']+TOL, 'earlier objective degraded beyond output tolerance')
    return dict(passed=not errors, failures=errors, checks=dict(checks), total_checks=sum(checks.values()))

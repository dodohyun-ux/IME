"""Small UI input -> saved official geometry; never download roads on a request."""
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.optimization import InputValidationError
from backend.poland_roads import load_addresses, load_snapshot, geocoded_address, scenario_network
from backend.road_paths import shortest_paths

ROOT = Path(__file__).resolve().parents[2] / 'data' / 'roads'
COMMON = ('item_weight_kg', 'procurement_lead_days', 'shelf_life_days', 'initial_lots',
          'pipeline_lots', 'disposal_cost', 'disposal_capacity')
CONTROLS = ('speed_kph','fixed_trip_cost','cost_per_km','cost_per_hour','minimum_trip_cost',
            'overnight_cost','allow_overnight_return','assumed_intermediate_rest')


def road_options():
    registry = json.loads((ROOT / 'facilities.json').read_text(encoding='utf-8'))
    preset = json.loads((ROOT / 'ui_preset.json').read_text(encoding='utf-8'))
    return dict(warehouses=[dict(id=f['id'], address=f['address'], source_url=f['source_url'])
                            for f in registry['warehouse_candidates']], preset=preset)


def planning_calendar(reference_date):
    try:
        reference = date.fromisoformat(reference_date)
        if reference.isoformat() != reference_date or reference.weekday() != 0:
            raise ValueError('Monday required')
        start = datetime.combine(reference + timedelta(days=7), time(), ZoneInfo('Europe/Warsaw'))
        start_utc = start.astimezone(timezone.utc)
        def hour(day, value):
            local = datetime.combine(start.date() + timedelta(days=day), time(), start.tzinfo) + timedelta(hours=value)
            return (local.astimezone(timezone.utc) - start_utc).total_seconds()/3600
        days = [7*w+d for w in range(4) for d in range(5)]
        return start, days, hour
    except (TypeError, ValueError, OverflowError) as error:
        raise InputValidationError('배차 기준주는 YYYY-MM-DD 형식의 월요일이어야 합니다.') from error


@lru_cache(maxsize=6)
def geometry_template(warehouse_id, site):
    """Cache every warehouse-site pair (2 warehouses x 3 sites) so switching sites
    does not re-parse the raw road files on each request."""
    options = road_options()
    registry = json.loads((ROOT / 'facilities.json').read_text(encoding='utf-8'))
    origins = [f for f in registry['warehouse_candidates'] if f['id'] == warehouse_id]
    targets = [f for f in registry['destinations'] if f['site'] == site]
    if len(origins) != 1 or len(targets) != 1:
        raise InputValidationError('알 수 없는 창고 후보 또는 구호소입니다.')
    origin, target = origins[0], targets[0]
    lookups = load_addresses(ROOT / 'raw')
    def point(facility):
        matches = [r for r in lookups if r['query'] == facility['geocode_query'] and 'response' in r]
        if len(matches) != 1:
            raise InputValidationError('저장된 공식 주소 응답이 없습니다: '+facility['address'])
        return geocoded_address(matches[0]['response'], facility['city'], facility['number'], facility.get('street'))
    regions = ['Medyka'] if site == 'Medyka' else ['Medyka', 'Korczowa']
    if site == 'Dorohusk': regions += ['Dorohusk', 'DorohuskCorridor']
    snapshot = load_snapshot(ROOT / 'raw', regions)
    preset, settings = options['preset'], options['preset']['scenario']
    config = dict(trucks=[preset['vehicle']], delivery_deadline_hours={w:168*w for w in range(1,5)},
                  path_search=dict(method='k_shortest', k=1, metrics=['distance']))
    # Road restrictions are permissive scenario values, not researched limits.
    assumptions = dict(speed_kph=settings['speed_kph'], max_gross_weight_kg=100000,
                       max_height_m=10, max_width_m=10, toll_per_km=settings['toll_per_km'])
    network, diagnostics = scenario_network(snapshot, config, point(origin), point(target), assumptions,
                                            destination_rest_allowed=settings['destination_rest_allowed'])
    if not diagnostics['connected']:
        raise InputValidationError('현재 확보한 도로망으로 두 시설을 연결할 수 없습니다.')
    # Avoid copying the large component diagnostics into every HTTP result.
    metadata = dict(warehouse_id=warehouse_id, warehouse_address=origin['address'],
                    destination_address=target['address'], origin_snap_m=diagnostics['origin']['snap_distance_m'],
                    destination_snap_m=diagnostics['destination']['snap_distance_m'],
                    missing_tile_count=len(diagnostics['missing_tiles']),
                    node_count=diagnostics['retained_route_nodes'], edge_count=diagnostics['retained_route_directed_edges'])
    return network, metadata


def warm_geometry_cache():
    """Build every warehouse-site road template once at server start-up."""
    registry = json.loads((ROOT / 'facilities.json').read_text(encoding='utf-8'))
    for warehouse in registry['warehouse_candidates']:
        for destination in registry['destinations']:
            try:
                geometry_template(warehouse['id'], destination['site'])
            except InputValidationError:
                pass


def build_ui_logistics(logistics, planning, site):
    if not isinstance(logistics, dict) or set(logistics) != set(COMMON):
        raise InputValidationError('도로망 간편 입력에는 품목·재고·조달·기한 조건만 전달하세요. 상세 노선 입력과 혼합할 수 없습니다.')
    options = road_options()
    preset, settings = options['preset'], options['preset']['scenario']
    settings = dict(settings)
    overrides = planning.get('transport_controls') or {}
    if not isinstance(overrides,dict) or set(overrides)-set(CONTROLS):
        raise InputValidationError('알 수 없는 운송 조건입니다.')
    for key,value in overrides.items():
        if key in ('allow_overnight_return','assumed_intermediate_rest'):
            if not isinstance(value,bool): raise InputValidationError('휴식 시나리오는 참/거짓으로 입력하세요.')
        elif isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
            raise InputValidationError('운송 단가는 유한한 0 이상의 숫자여야 합니다.')
        settings[key]=value
    if not 30<=settings['speed_kph']<=90:
        raise InputValidationError('간편 입력의 평균 주행속도는 30~90 km/h여야 합니다.')
    count = planning['truck_count']
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= preset['max_truck_count']:
        raise InputValidationError('간편 도로망 계획의 차량 대수는 1~3대여야 합니다.')
    start, days, hour = planning_calendar(planning['reference_date'])
    template, metadata = geometry_template(planning['warehouse_id'], site)
    # Template geometry is immutable across requests; copy only mutable controls.
    network = dict(template)
    network['edges'] = [dict(e,travel_minutes=e['distance_km']/settings['speed_kph']*60) for e in template['edges']]
    rest_nodes=[]
    if settings.get('assumed_intermediate_rest',False):
        # A road vertex in a declared scenario, NOT a researched rest facility.
        edges={e['id']:e for e in network['edges']}; adj={}
        for eid,e in edges.items(): adj.setdefault(e['from_node'],[]).append(eid)
        for origin,target in ((network['depot_node'],network['destination_node']),
                              (network['destination_node'],network['depot_node'])):
            paths=shortest_paths(edges,adj,origin,target,lambda e:True,lambda e:e['distance_km'],1)
            if not paths: continue
            path=paths[0]
            slot=network.get('slot_seconds',network['slot_minutes']*60)/60
            minutes=lambda eid:math.ceil(edges[eid]['travel_minutes']/slot-1e-9)*slot
            halfway=sum(minutes(e) for e in path)/2
            duration=0.; choices=[]
            for eid in path[:-1]:
                duration+=minutes(eid)
                choices.append((abs(duration-halfway),edges[eid]['to_node']))
            if choices: rest_nodes.append(min(choices)[1])
        rest_nodes=sorted(set(rest_nodes)-{network['depot_node'],network['destination_node']})
        network['nodes']=[dict(n,rest_allowed=True) if n['id'] in rest_nodes else n for n in template['nodes']]
    network.update(planning_start=start.isoformat(), destination_site=site, capacity_resources={},
                   departure_hours=[hour(d, settings['departure_hour']) for d in days if d%7 in settings['departure_weekdays']])
    trucks = []
    for i in range(count):
        truck = dict(preset['vehicle'], id=f'truck-{i+1:02d}')
        for field in ('loading_minutes','unloading_minutes','turnaround_minutes','fixed_trip_cost',
                      'cost_per_km','max_continuous_driving_minutes','break_minutes',
                      'max_weekly_driving_minutes','max_two_week_driving_minutes'):
            truck[field] = settings[field]
        for field in ('allow_overnight_return','cost_per_hour','minimum_trip_cost','overnight_cost'):
            truck[field]=settings[field]
        truck['availability'] = [dict(start_hour=hour(d,settings['availability_start_hour']),
                                      end_hour=hour(d,settings['availability_end_hour']),
                                      max_driving_minutes=settings['max_daily_driving_minutes']) for d in days]
        trucks.append(truck)
    network['trucks'] = trucks
    result = deepcopy(logistics)
    result['road_network'] = network
    information = dict(metadata, vehicle_preset=preset, truck_count=count,
                       planning_start=start.isoformat(), timezone='Europe/Warsaw', scenario=True,
                       transport_controls={k:settings[k] for k in CONTROLS}, assumed_rest_nodes=rest_nodes,
                       cost_scope='Net distance reference plus user-entered extras; missing extras are excluded, not verified zero costs.',
                       rest_scope='Intermediate road vertices and destination rest access are scenario assumptions; no facility/permission verified.')
    return result, information

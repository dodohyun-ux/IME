"""Geographic integrity, path-search counterexamples and actual-data integration."""
from copy import deepcopy
from pathlib import Path
import itertools
import random
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ofr_v2/app'))
from backend.poland_roads import (parse_roadlinks, load_snapshot, endpoint_graph,
                                 snap_endpoint, geocoded_address, scenario_network, distance_km,
                                 route_subgraph, load_addresses)
from backend.road_paths import shortest_paths
from backend.road_network import Graph, example_road_logistics
from backend.optimization import InputValidationError, example_inputs, optimize_relief_plan


def xml(lines, count=None):
    features = ''.join(f'<RoadLink><localId>{j}</localId><beginLifespanVersion>2022-01-01T00:00:00Z</beginLifespanVersion><centrelineGeometry>LINESTRING ({line})</centrelineGeometry></RoadLink>' for j,line in enumerate(lines))
    return f'<FeatureCollection numberOfFeatures="{len(lines) if count is None else count}"><featureMembers>{features}</featureMembers></FeatureCollection>'.encode()


def graph(lines):
    return endpoint_graph(dict(links=[l | dict(source_id='official') for l in parse_roadlinks(xml(lines))]))


def test_axis_conversion_and_curved_length():
    link = parse_roadlinks(xml(['49.8 22.9,49.81 22.9,49.81 22.91']))[0]
    assert link['geometry'][0] == [22.9,49.8]
    assert distance_km(link['geometry']) > distance_km([link['geometry'][0],link['geometry'][-1]])


@pytest.mark.parametrize('raw', [b'<html>no data</html>',b'<!DOCTYPE a [<!ENTITY x "x">]><FeatureCollection/>',xml(['22.9 49.8,22.91 49.81']),xml(['49.8 22.9,49.81 22.91'],count=2),xml(['49.8 22.9 1,49.81 22.91 1'])])
def test_bad_geometry_is_rejected(raw):
    with pytest.raises(InputValidationError): parse_roadlinks(raw)


def test_interior_crossing_and_near_endpoints_do_not_connect():
    g = graph(['49.8 22.9,49.8 22.92','49.79 22.91,49.81 22.91','49.8 22.92000001,49.8 22.93'])
    assert len(g['nodes']) == 6
    assert sorted(map(len,g['components'])) == [2,2,2]


def test_exact_shared_endpoints_connect():
    g = graph(['49.8 22.9,49.8 22.92','49.8 22.92,49.81 22.92'])
    assert len(g['nodes']) == 3 and len(g['components']) == 1


def test_snap_has_hard_bound_and_no_fake_approach_edge():
    g = graph(['49.8 22.9,49.8 22.92'])
    s = snap_endpoint(g,[22.90001,49.8],20)
    assert s['snap_distance_m'] > 0 and not s['facility_access_verified']
    assert len(g['edges']) == 2
    with pytest.raises(InputValidationError): snap_endpoint(g,[23.5,51.2],500)


def test_cs92_address_lookup_matches_city_and_number():
    # Official UUG documentation's Marki, Andersa 1 sample.
    r = dict(results={'1':dict(city='Marki',number='1',x='644234.2904',y='499514.0342')})
    lon,lat = geocoded_address(r,'Marki','1')
    assert 20 < lon < 22 and 52 < lat < 53
    with pytest.raises(InputValidationError): geocoded_address(r,'Medyka','293')
    with pytest.raises(InputValidationError): geocoded_address(dict(results={}), 'Marki','1')
    with pytest.raises(InputValidationError): geocoded_address(dict(results=[r['results']['1']]*2),'Marki','1')


def tiny_paths(edges,start,end):
    def walk(n,seen,path):
        if n == end:
            yield tuple(path); return
        for eid,e in edges.items():
            if e['from_node']==n and e['to_node'] not in seen:
                yield from walk(e['to_node'],seen|{e['to_node']},path+[eid])
    return list(walk(start,{start},[]))


@pytest.mark.parametrize('seed',range(10))
def test_yen_matches_exhaustive_costs_with_parallel_edges_and_cycles(seed):
    rng=random.Random(seed); edges={}; adj={i:[] for i in range(6)}
    for a,b in itertools.permutations(range(6),2):
        if rng.random()<.4:
            for j in range(1+rng.randrange(2)):
                eid=f'{a}-{b}-{j}'; edges[eid]=dict(from_node=a,to_node=b,cost=rng.randrange(1,20));adj[a].append(eid)
    expected=sorted(sum(edges[e]['cost'] for e in p) for p in tiny_paths(edges,0,5))[:8]
    found=shortest_paths(edges,adj,0,5,lambda e:True,lambda e:e['cost'],8)
    assert [sum(edges[e]['cost'] for e in p) for p in found]==expected
    assert len(set(found))==len(found)


def test_path_restrictions_disconnect_and_work_limit_fail():
    e={'a':dict(from_node=0,to_node=1,cost=1)}; adj={0:['a']}
    assert shortest_paths(e,adj,0,1,lambda e:False,lambda e:e['cost'],2)==[]
    with pytest.raises(InputValidationError): shortest_paths(e,adj,0,1,lambda e:True,lambda e:1,2,max_relaxations=0)


def real_case():
    snapshot=load_snapshot(ROOT/'ofr_v2/data/roads/raw','Medyka')
    g=endpoint_graph(snapshot)
    largest=max(g['components'],key=len)
    # Real road endpoints for integration only, not fabricated facility addresses.
    a=min(largest,key=lambda n:g['nodes'][n]['coordinates'][0])
    b=max(largest,key=lambda n:g['nodes'][n]['coordinates'][0])
    f,u,v=example_inputs(); f={'Medyka':{1:50,2:0,3:0,4:0}}
    u.update(utilization_rate=.2,stay_days=1,total_budget=100000)
    u['initial_inventory']['Medyka']={i:0 for i in v}
    u['weekly_supply']={i:{w:10 if i=='food' and w==1 else 0 for w in range(1,5)} for i in v}
    u['warehouse_capacity_m3']['Medyka']=1000
    l=example_road_logistics();l['initial_lots']=[];l['shelf_life_days']={i:None for i in v}
    config=l['road_network'];config['trucks']=config['trucks'][:1];config['departure_hours']=[9];config['slot_minutes']=1
    assumptions=dict(speed_kph=40,max_gross_weight_kg=18000,max_height_m=4.5,max_width_m=3,toll_per_km=0)
    l['road_network'],diagnostic=scenario_network(snapshot,config,g['nodes'][a]['coordinates'],g['nodes'][b]['coordinates'],assumptions,1)
    return f,u,v,l,diagnostic


def test_actual_poland_geometry_joint_cargo_schedule_and_trace():
    f,u,v,l,d=real_case()
    result=optimize_relief_plan(f,u,v,logistics=l)
    assert d['road_feature_count']>=2040
    assert len(l['road_network']['nodes'])>32
    assert len(result['truck_plan'])==1
    p=result['truck_plan'][0]
    assert p['cargo']['food']==10
    assert p['outbound_geometry'] and p['return_geometry']
    assert p['round_trip_distance_km']>10
    assert p['time_rounding_added_minutes']>0
    assert p['time_rounding_added_minutes'] <= (len(p['outbound_edges'])+len(p['return_edges']))*5/60
    assert result['model_info']['slot_seconds']==5
    km=sum(distance_km(segment['coordinates']) for direction in ('outbound','return') for segment in p[direction+'_geometry'])
    assert km==pytest.approx(p['round_trip_distance_km'])
    assert all(segment['source_feature_ids'] for segment in p['outbound_geometry'])
    assert not result['model_info']['operational_ready']
    assert 'conditional' in result['model_info']['road_search_scope']


def test_unverified_official_geometry_cannot_be_promoted_to_operational():
    f,u,v,l,_=real_case(); l['road_network']['data_kind']='operational'
    with pytest.raises(InputValidationError,match='unverified'): optimize_relief_plan(f,u,v,logistics=l)


def test_geometry_endpoint_mismatch_rejected():
    f,u,v,l,_=real_case(); l['road_network']['edges'][0]['geometry'][0]=[20,50]
    with pytest.raises(InputValidationError,match='endpoints'): optimize_relief_plan(f,u,v,logistics=l)


@pytest.mark.parametrize('value',[0,7,61,True])
def test_subminute_grid_rejects_invalid_seconds(value):
    f,u,v,l,_=real_case(); l['road_network']['slot_seconds']=value
    with pytest.raises(InputValidationError): optimize_relief_plan(f,u,v,logistics=l)


def test_address_street_mismatch_is_rejected():
    r=dict(results={'1':dict(city='Przemyśl',street='Wodna',number='36',x='644234',y='499514')})
    with pytest.raises(InputValidationError): geocoded_address(r,'Przemyśl','36','Lwowska')


def test_snapshot_checksum_and_path_escape_are_rejected(tmp_path):
    import json
    p=ROOT/'ofr_v2/data/roads/raw/acquisition.json'
    manifest=json.loads(p.read_text(encoding='utf-8'))
    manifest['documents']=[d for d in manifest['documents'] if d.get('region')=='Medyka' and d['count']>0][:1]
    manifest['documents'][0]['name']='bad.gml'
    (tmp_path/'bad.gml').write_bytes(xml(['49.8 22.9,49.8 22.92']))
    (tmp_path/'acquisition.json').write_text(json.dumps(manifest))
    with pytest.raises(InputValidationError,match='hash'): load_snapshot(tmp_path,'Medyka')
    manifest['documents'][0]['name']='../bad.gml'
    (tmp_path/'acquisition.json').write_text(json.dumps(manifest))
    with pytest.raises(InputValidationError,match='inside'): load_snapshot(tmp_path,'Medyka')


def test_unacquired_region_is_not_silently_claimed():
    with pytest.raises(InputValidationError,match='no acquired'):
        load_snapshot(ROOT/'ofr_v2/data/roads/raw',['Medyka','unknown'])


def test_simple_path_subgraph_keeps_all_routes_and_removes_dangling_branch():
    g=graph(['49.8 22.9,49.8 22.91','49.8 22.91,49.8 22.92',
             '49.8 22.91,49.81 22.91','49.81 22.91,49.82 22.91',
             '49.8 22.9,49.79 22.91','49.79 22.91,49.8 22.92',
             '50.1 23.2,50.1 23.21'])
    a=snap_endpoint(g,[22.9,49.8],1)['node']; b=snap_endpoint(g,[22.92,49.8],1)['node']
    before=set(tiny_paths(g['edges'],a,b))
    trimmed=route_subgraph(g,a,b)
    assert len(trimmed['nodes'])==4
    assert set(tiny_paths(trimmed['edges'],a,b))==before
    assert all(e==g['edges'][eid] for eid,e in trimmed['edges'].items())


def test_address_response_integrity_and_registry_points(tmp_path):
    import json
    folder=ROOT/'ofr_v2/data/roads'
    records=load_addresses(folder/'raw')
    registry=json.loads((folder/'facilities.json').read_text(encoding='utf-8'))
    for candidate in registry['warehouse_candidates']+registry['destinations']:
        record=next(r for r in records if r['query']==candidate['geocode_query'])
        point=geocoded_address(record['response'],candidate['city'],candidate['number'],candidate.get('street'))
        assert candidate['coordinates']==pytest.approx(point)
    (tmp_path/'acquisition.json').write_bytes((folder/'raw/acquisition.json').read_bytes())
    (tmp_path/'addresses.json').write_text('[]')
    with pytest.raises(InputValidationError,match='hash'):
        load_addresses(tmp_path)


@pytest.mark.parametrize('site,regions',[('Medyka',['Medyka']),('Korczowa',['Medyka','Korczowa']),
    ('Dorohusk',['Medyka','Korczowa','Dorohusk','DorohuskCorridor'])])
def test_official_address_candidate_joint_routing_scenario(site,regions):
    import json
    folder=ROOT/'ofr_v2/data/roads'
    registry=json.loads((folder/'facilities.json').read_text(encoding='utf-8'))
    warehouse=next(c for c in registry['warehouse_candidates'] if c['id']=='przemysl-wodna-11')
    destination=next(c for c in registry['destinations'] if c['site']==site)
    f,u,v=example_inputs(); f={site:{1:50,2:0,3:0,4:0}}
    u.update(selected_site=site,utilization_rate=.2,stay_days=1,total_budget=100000)
    u['initial_inventory']={site:{i:0 for i in v}}
    u['weekly_supply']={i:{w:10 if i=='food' and w==1 else 0 for w in range(1,5)} for i in v}
    u['warehouse_capacity_m3']={site:1000}
    l=example_road_logistics(site);l['initial_lots']=[];l['shelf_life_days']={i:None for i in v}
    config=l['road_network'];config['trucks']=config['trucks'][:1];config['departure_hours']=[9]
    snapshot=load_snapshot(folder/'raw',regions)
    l['road_network'],d=scenario_network(snapshot,config,warehouse['coordinates'],destination['coordinates'],
        dict(speed_kph=60 if site=='Dorohusk' else 40,max_gross_weight_kg=18000,max_height_m=4.5,max_width_m=3,toll_per_km=0),
        destination_rest_allowed=(site=='Dorohusk'))
    assert d['connected']
    assert d['origin']['snap_distance_m']<500 and d['destination']['snap_distance_m']<500
    result=optimize_relief_plan(f,u,v,logistics=l)
    assert len(result['truck_plan'])==1
    p=result['truck_plan'][0]
    assert p['cargo']['food']==10
    assert p['outbound_geometry'][0]['coordinates'][0]==d['origin']['road_point']
    assert p['outbound_geometry'][-1]['coordinates'][-1]==d['destination']['road_point']
    assert not result['model_info']['operational_ready']
    if site=='Dorohusk':
        assert len(l['road_network']['nodes'])>50000
        assert p['round_trip_distance_km']>400
        assert any(e['kind']=='break' and e.get('phase')=='return' and e['node']==d['destination']['node'] for e in p['timeline'])
        # No rest permission: connected geometry alone must not produce an
        # illegal long return tour. Unloading cannot count as a driver break.
        target=next(n for n in l['road_network']['nodes'] if n['id']==d['destination']['node'])
        target['rest_allowed']=False
        blocked=optimize_relief_plan(f,u,v,logistics=l)
        assert blocked['truck_plan']==[]
        assert all(p['served']==0 for p in blocked['plan'] if p['item']=='food')


@pytest.mark.parametrize('permission',['yes',1,None])
def test_destination_rest_permission_requires_boolean(permission):
    f,u,v=example_inputs();l=example_road_logistics()
    with pytest.raises(InputValidationError,match='boolean'):
        scenario_network(dict(),l['road_network'],[22,50],[22.1,50],
            dict(speed_kph=40,max_gross_weight_kg=18000,max_height_m=4.5,max_width_m=3,toll_per_km=0),
            destination_rest_allowed=permission)


@pytest.mark.parametrize('change',[dict(k=9),dict(k=True),dict(method='unknown'),dict(metrics=[]),dict(metrics=['unknown'])])
def test_large_graph_search_configuration_validation(change):
    f,u,v,l,_=real_case(); l['road_network']['path_search'].update(change)
    with pytest.raises(InputValidationError): optimize_relief_plan(f,u,v,logistics=l)

"""Official GUGiK geometry import, with explicit unverified operating scenarios.

Raw WFS endpoints do not populate RoadLink startNode/endNode. Only identical
line endpoints are joined; geometric crossings and near points are never joined.
The importer cannot certify one-way rules, truck access, opening times or docks.
"""
from collections import defaultdict
from copy import deepcopy
import base64
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from pyproj import Geod, Transformer

from backend.optimization import InputValidationError
from backend.road_network import coordinates, number, optional_keys, sequence

GEOD = Geod(ellps='WGS84')
MAX_RAW_BYTES = 100000000


def distance_km(points):
    return GEOD.line_length([p[0] for p in points], [p[1] for p in points]) / 1000


def parse_roadlinks(raw):
    """WFS 1.1 requested EPSG:4326: latitude-first -> GeoJSON lon/lat.

    The acquired service serializes centrelineGeometry as WKT text despite GML
    feature packaging. Both featureMembers and featureMember are supported.
    """
    if len(raw) > MAX_RAW_BYTES or b'<!DOCTYPE' in raw or b'<!ENTITY' in raw:
        raise InputValidationError('Unsupported or oversized road XML')
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise InputValidationError('Invalid road XML') from error
    if root.tag.split('}')[-1] != 'FeatureCollection':
        raise InputValidationError('Expected official WFS FeatureCollection')
    links = []
    features = root.findall('.//{*}RoadLink')
    reported = root.get('numberOfFeatures')
    try:
        if reported is not None and int(reported) != len(features):
            raise InputValidationError('Road response count mismatch')
    except ValueError as error:
        raise InputValidationError('Invalid road feature count') from error
    for f in features:
        def text(tag):
            node = f.find('.//{*}'+tag)
            return None if node is None else node.text
        fid = text('localId')
        version, uri = text('beginLifespanVersion'), text('identifier')
        geom = f.find('.//{*}centrelineGeometry')
        if not fid or geom is None:
            raise InputValidationError('Road feature lacks ID/geometry')
        match = re.fullmatch(r'\s*LINESTRING\s*\(([^()]*)\)\s*', geom.text or '', re.I)
        if match:
            pairs = [part.split() for part in match[1].split(',')]
        else:
            line = geom.find('.//{*}posList')
            if line is None or line.get('srsDimension', '2') != '2':
                raise InputValidationError('Unsupported road centreline geometry')
            values = (line.text or '').split()
            if len(values) % 2:
                raise InputValidationError('Odd road coordinate count')
            pairs = [values[j:j+2] for j in range(0,len(values),2)]
        pts = []
        for pair in pairs:
            if len(pair) != 2:
                raise InputValidationError('Road geometry must have two-dimensional points')
            try:
                point = coordinates([float(pair[1]), float(pair[0])], 'official road coordinates')
            except ValueError as error:
                raise InputValidationError('Invalid road coordinate') from error
            # A swapped axis otherwise remains legal WGS84; reject outside Poland.
            if not (13 < point[0] < 25 and 48 < point[1] < 56):
                raise InputValidationError('Road coordinates outside Poland: check CRS/axis order')
            if not pts or pts[-1] != point:
                pts.append(point)
        if len(pts) < 2 or len(pts) > 20000:
            raise InputValidationError('Invalid road geometry length')
        links.append(dict(id=fid, geometry=pts, version=version, source_uri=uri,
                          fictitious=text('fictitious') == 'true'))
    return links


def load_snapshot(folder, region):
    """Read hash-checked exact public responses; no online or synthetic fallback."""
    folder = Path(folder)
    manifest = json.loads((folder/'acquisition.json').read_text(encoding='utf-8'))
    regions = [region] if isinstance(region,str) else list(region)
    if not regions or any(not isinstance(r,str) for r in regions) or len(set(regions)) != len(regions):
        raise InputValidationError('Distinct acquired regions required')
    if any(not any(d.get('region')==r for d in manifest['documents']) for r in regions):
        raise InputValidationError('Requested region has no acquired road coverage')
    documents = [d for d in manifest['documents'] if d.get('region') in regions]
    if not documents:
        raise InputValidationError('No acquired official road coverage for '+','.join(regions))
    links = {}
    sources = []
    for j, doc in enumerate(documents):
        if not isinstance(doc['name'],str) or Path(doc['name']).name != doc['name'] or '..' in doc['name']:
            raise InputValidationError('Road snapshot filenames must stay inside snapshot folder')
        path = folder/doc['name']
        if path.exists():
            raw = path.read_bytes()
        else:
            compressed = base64.b64decode(Path(str(path)+'.base64').read_text().strip(), validate=True)
            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
                raw = stream.read(MAX_RAW_BYTES+1)
        if len(raw) > MAX_RAW_BYTES or hashlib.sha256(raw).hexdigest() != doc['sha256']:
            raise InputValidationError('Official road snapshot hash mismatch: '+doc['name'])
        parsed = parse_roadlinks(raw)
        if len(parsed) != doc['count'] or len(parsed) >= 5000:
            raise InputValidationError('Road tile may be incomplete; acquire smaller tiles')
        sid = 'gugik-'+str(j)
        sources.append(dict(id=sid,publisher='GUGiK / Geoportal',url=doc['url'],
                            retrieved_at=doc.get('retrieved_at',manifest['fetched_at'])))
        for link in parsed:
            old = links.get(link['id'])
            if old and old['geometry'] != link['geometry']:
                raise InputValidationError('Conflicting overlapping road tile features')
            if not old:
                links[link['id']] = link | dict(source_id=sid)
    versions = sorted({l['version'] for l in links.values() if l['version']})
    missing=[e for e in manifest.get('errors',[]) if e['region'] in regions]
    return dict(links=list(links.values()),sources=sources,coverage='/'.join(regions),
                missing_tiles=missing,
                fetched_at=manifest['fetched_at'],feature_version_range=versions[::max(1,len(versions)-1)])


def endpoint_graph(snapshot):
    nodes, edges, adjacency = {}, {}, defaultdict(list)
    excluded = []
    points = {}
    def node(point):
        key = tuple(point)
        if key not in points:
            nid = 'n'+str(len(points))
            points[key] = nid
            nodes[nid] = dict(id=nid,label='GUGiK road endpoint '+nid,
                              coordinates=list(point),rest_allowed=False)
        return points[key]
    for link in snapshot['links']:
        pts = link['geometry']
        if link['fictitious'] or pts[0] == pts[-1]:
            excluded.append(link['id'])
            continue
        a,b = node(pts[0]), node(pts[-1])
        km = distance_km(pts)
        if km <= 0 or not math.isfinite(km):
            raise InputValidationError('Nonpositive official road length')
        for direction,x,y,geometry in [('f',a,b,pts),('r',b,a,list(reversed(pts)))]:
            eid = link['id']+':'+direction
            edges[eid] = dict(id=eid,from_node=x,to_node=y,geometry=geometry,
                              distance_km=km,source_feature_ids=[link['id']],
                              source_id=link['source_id'])
            adjacency[x].append(eid)
    components, visited = [], set()
    for nid in nodes:
        if nid in visited: continue
        pending, component = [nid], set()
        while pending:
            v = pending.pop()
            if v in visited: continue
            visited.add(v); component.add(v)
            pending.extend(edges[e]['to_node'] for e in adjacency[v])
        components.append(component)
    return dict(nodes=nodes,edges=edges,adjacency=adjacency,components=components,
                excluded_feature_ids=excluded)


def route_subgraph(graph, origin, target):
    """Keep the connected component and peel dead ends irrelevant to simple paths.

    The importer builds symmetric directed edges. Entering a dangling branch
    would require revisiting its attachment vertex, excluded by the existing
    loopless candidate search. This removes no admissible simple origin-target
    path and introduces no connections. Never apply this to a general directed
    operational graph or to a model allowing a visit to a dead-end rest stop.
    """
    component=next((c for c in graph['components'] if origin in c and target in c),None)
    if component is None:
        return graph
    retained=set(component)
    neighbours={n:set(graph['edges'][e]['to_node'] for e in graph['adjacency'][n]) & retained for n in retained}
    pending=[n for n in retained if n not in (origin,target) and len(neighbours[n])<=1]
    while pending:
        n=pending.pop()
        if n not in retained: continue
        retained.remove(n)
        for other in neighbours[n]:
            neighbours[other].discard(n)
            if other not in (origin,target) and len(neighbours[other])<=1:
                pending.append(other)
    edges={eid:e for eid,e in graph['edges'].items() if e['from_node'] in retained and e['to_node'] in retained}
    adjacency={n:[e for e in graph['adjacency'][n] if e in edges] for n in retained}
    return graph | dict(nodes={n:v for n,v in graph['nodes'].items() if n in retained},
                        edges=edges,adjacency=adjacency,components=[retained])


def load_addresses(folder):
    """Verify address responses against the same provenance manifest as roads."""
    folder=Path(folder)
    manifest=json.loads((folder/'acquisition.json').read_text(encoding='utf-8'))
    documents=[d for d in manifest['documents'] if d['name']=='addresses.json']
    if len(documents)!=1:
        raise InputValidationError('Exactly one official address response document required')
    raw=(folder/'addresses.json').read_bytes()
    if len(raw)>MAX_RAW_BYTES or hashlib.sha256(raw).hexdigest()!=documents[0]['sha256']:
        raise InputValidationError('Official address response hash mismatch')
    result=json.loads(raw)
    if not isinstance(result,list):
        raise InputValidationError('Official address response list required')
    return result


def snap_endpoint(graph, point, max_distance_m):
    """Snap only to an existing endpoint, reporting the unmodeled dock approach."""
    point = coordinates(point, 'facility coordinates')
    limit = number(max_distance_m, 'max_snap_distance_m', True)
    if not graph['nodes']:
        raise InputValidationError('Official graph is empty')
    distances = [(GEOD.inv(*point,*n['coordinates'])[2], nid) for nid,n in graph['nodes'].items()]
    metres,nid = min(distances)
    if metres > limit:
        raise InputValidationError(f'Facility is {metres:.1f}m from road endpoint, above {limit:.1f}m bound')
    return dict(node=nid,point=point,road_point=graph['nodes'][nid]['coordinates'],
                snap_distance_m=metres,facility_access_verified=False)


def geocoded_address(response, expected_city, expected_number, expected_street=None):
    """Reject ambiguous/city-only responses; address points are not truck docks."""
    results = response.get('results', {})
    values = list(results.values()) if isinstance(results,dict) else results
    if not isinstance(values,list):
        raise InputValidationError('Official address lookup is ambiguous or empty')
    values=[v for v in values if isinstance(v,dict) and (v.get('city') or '').casefold()==expected_city.casefold()
            and str(v.get('number',''))==expected_number
            and (expected_street is None or (v.get('street') or '').casefold()==expected_street.casefold())]
    if len(values) != 1:
        raise InputValidationError('Official address lookup is ambiguous or empty')
    value = values[0]
    if value.get('city','').casefold() != expected_city.casefold() or str(value.get('number','')) != expected_number:
        raise InputValidationError('Official address result does not match requested city/number')
    try:
        # UUG documentation uses x=easting,y=northing in Poland CS92 EPSG:2180.
        lon,lat = Transformer.from_crs(2180,4326,always_xy=True).transform(float(value['x']),float(value['y']))
        point = coordinates([lon,lat], 'geocoded address')
    except (KeyError,ValueError) as error:
        raise InputValidationError('Official address result lacks usable CS92 coordinates') from error
    if not (13 < lon < 25 and 48 < lat < 56):
        raise InputValidationError('Geocoded address outside Poland')
    return point


def scenario_network(snapshot, configuration, origin_point, destination_point, assumptions, max_snap_distance_m=500,
                     destination_rest_allowed=False):
    """Attach actual geometry to supplied MILP settings with explicit assumptions.

    Direction/access/time/toll are scenario inputs, NEVER attributed to GUGiK.
    Operational approval is deliberately unavailable through this function.
    """
    optional_keys(assumptions, ('speed_kph','max_gross_weight_kg','max_height_m','max_width_m','toll_per_km'), (), 'road assumptions')
    for field,value in assumptions.items(): number(value,field, field != 'toll_per_km')
    if not isinstance(destination_rest_allowed,bool):
        raise InputValidationError('destination_rest_allowed must be an explicit boolean scenario permission')
    graph = endpoint_graph(snapshot)
    origin = snap_endpoint(graph,origin_point,max_snap_distance_m)
    target = snap_endpoint(graph,destination_point,max_snap_distance_m)
    if origin['node'] == target['node']:
        raise InputValidationError('Facilities snap to same road endpoint')
    full_graph=graph
    graph=route_subgraph(graph,origin['node'],target['node'])
    network = deepcopy(configuration)
    # Finer ticks reduce per-short-segment rounding; existing minute-grid models unchanged.
    network['slot_minutes'] = 1
    network['slot_seconds'] = 5
    network.update(nodes=list(graph['nodes'].values()),edges=[],depot_node=origin['node'],
                   destination_node=target['node'],data_kind='official_geometry_scenario',sources=snapshot['sources'],
                   path_search=deepcopy(configuration.get('path_search',dict(method='k_shortest',k=2,metrics=['distance','travel_time']))),
                   geography=dict(publisher='GUGiK',geometry_verified=True,topology_reviewed=False,
                                  operating_values_verified=False,facility_access_verified=False,
                                  coverage=snapshot['coverage'],assumptions=[
                                      'Exact shared line endpoints infer topology; intersections inside lines are not joined. Source startNode/endNode are unpopulated.',
                                      'Both travel directions assumed: one-way and truck access are not in this snapshot.',
                                      'Speed, weight/height/width limits, tolls, open windows, truck data, costs and facility availability are scenario assumptions.',
                                      'Snapped road endpoints only; facility entrance/dock access and snap gaps are not modeled.',
                                      'Depot rest permission is a scenario assumption. Destination rest permission is explicitly supplied: '+str(destination_rest_allowed)+'; never inferred from its address or unloading.',
                                      'Only the origin-target connected component and branches relevant to loopless paths retained; no off-route rest facilities inferred.',
                                      'Regional geometry only; version dates can predate acquisition. No real-time congestion or closures. Missing tiles: '+str(len(snapshot.get('missing_tiles',[]))),
                                      'Travel rounded UP PER ROAD EDGE; slot quantization can considerably overestimate ETA on short segments.']))
    types = sorted({t['vehicle_type'] for t in network['trucks']})
    used_sources={e['source_id'] for e in graph['edges'].values()}
    network['sources']=[s for s in snapshot['sources'] if s['id'] in used_sources]
    end_hour = max(network['delivery_deadline_hours'].values())
    network['nodes'][list(graph['nodes']).index(origin['node'])]['rest_allowed'] = True
    network['nodes'][list(graph['nodes']).index(target['node'])]['rest_allowed'] = destination_rest_allowed
    for eid,e in graph['edges'].items():
        network['edges'].append(e | dict(road_name='GUGiK RoadLink '+e['source_feature_ids'][0],
            travel_minutes=e['distance_km']/assumptions['speed_kph']*60,
            toll_cost=e['distance_km']*assumptions['toll_per_km'],
            max_gross_weight_kg=assumptions['max_gross_weight_kg'],max_height_m=assumptions['max_height_m'],
            max_width_m=assumptions['max_width_m'],allowed_vehicle_types=types,
            allowed_items=['food','water','hygiene_kit','blanket'],open_windows=[dict(start_hour=0,end_hour=end_hour)],
            capacity_resource=None))
    diagnostics=dict(node_count=len(full_graph['nodes']),road_feature_count=len(snapshot['links']),
                     connected=any(origin['node'] in c and target['node'] in c for c in graph['components']),
                     directed_edge_count=len(full_graph['edges']),component_sizes=sorted((len(c) for c in full_graph['components']),reverse=True),
                     retained_route_nodes=len(graph['nodes']),retained_route_directed_edges=len(graph['edges']),
                     imported_source_count=len(snapshot['sources']),retained_source_count=len(network['sources']),
                     excluded_feature_ids=graph['excluded_feature_ids'],origin=origin,destination=target,
                     feature_version_range=snapshot['feature_version_range'],fetched_at=snapshot['fetched_at'],
                     missing_tiles=snapshot.get('missing_tiles',[]),
                     assumptions=assumptions,operational_ready=False)
    diagnostics['destination_rest_allowed_scenario']=destination_rest_allowed
    return network,diagnostics

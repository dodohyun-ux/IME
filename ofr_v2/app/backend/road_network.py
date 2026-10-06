"""Joint road-path, named-truck, cargo and departure-time MILP adapter.

Small graphs enumerate ALL simple outbound/return paths. An explicit k-shortest
mode supports larger regional graphs and reports conditional optimality.
Exceeding work/size limits raises. No network or synthetic operational fallback.
Weekly demand/FEFO/quarantine constraints remain in logistics.py.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from urllib.parse import urlparse

from backend import optimization as base

MAX_PATHS = 256
MAX_CANDIDATES = 4096
MAX_PATH_COMBINATIONS = 100000
MAX_ORDER_LOTS = 1024
MAX_FEFO_TERMS = 1000000
SOURCES = [
    dict(publisher='GUGiK / Geoportal.gov.pl', title='BDOT10k official vector data',
         url='https://www.geoportal.gov.pl/pl/dane/baza-danych-obiektow-topograficznych-bdot10k/'),
    dict(publisher='GDDKiA', title='Official road status map',
         url='https://www.gov.pl/web/gddkia/msbd'),
    dict(publisher='GDDKiA', title='Road information service',
         url='https://drogi.gddkia.gov.pl/'),
    dict(publisher='European Commission', title='Driving time and rest periods',
         url='https://transport.ec.europa.eu/transport-modes/road/social-provisions/driving-time-and-rest-periods_en'),
]


def number(v, path, positive=False):
    return base._finite_number(v, path, minimum=0, strictly_positive=positive)


def keys(v, expected, path):
    v = base._require_mapping(v, path)
    base._check_exact_keys(v, expected, path)
    return v


def optional_keys(v, required, optional, path):
    v = base._require_mapping(v, path)
    if set(v) - set(required) - set(optional) or set(required) - set(v):
        raise base.InputValidationError(f'{path} has unknown or missing fields')
    return v


def coordinates(value, path):
    if not isinstance(value, list) or len(value) != 2:
        raise base.InputValidationError(f'{path} requires [longitude, latitude]')
    lon = base._finite_number(value[0], path, minimum=-180)
    lat = base._finite_number(value[1], path, minimum=-90)
    if lon > 180 or lat > 90:
        raise base.InputValidationError(f'{path} outside WGS84 range')
    return [lon, lat]


def identifier(v, path):
    if not isinstance(v, str) or not v.strip() or len(v) > 120:
        raise base.InputValidationError(f'{path} must be a nonempty string of at most 120 characters')
    return v


def sequence(v, path, maximum, minimum=0):
    if not isinstance(v, list) or not minimum <= len(v) <= maximum:
        raise base.InputValidationError(f'{path} must be a list of {minimum}..{maximum} entries')
    return v


def unique_strings(v, allowed, path):
    vals = sequence(v, path, 64)
    if any(not isinstance(x, str) or x not in allowed for x in vals) or len(set(vals)) != len(vals):
        raise base.InputValidationError(f'{path} requires distinct declared IDs')
    return set(vals)


def parse_time(v, path):
    if not isinstance(v, str):
        raise base.InputValidationError(f'{path} requires an ISO 8601 datetime with UTC offset')
    try:
        d = datetime.fromisoformat(v.replace('Z', '+00:00'))
    except ValueError as error:
        raise base.InputValidationError(f'{path} is not a valid datetime') from error
    if d.tzinfo is None or d.utcoffset() is None:
        raise base.InputValidationError(f'{path} requires a UTC offset')
    return d.astimezone(timezone.utc)


class Graph:
    def __init__(self, raw, data):
        n = optional_keys(raw, ('planning_start', 'slot_minutes', 'destination_site', 'depot_node',
                       'destination_node', 'nodes', 'edges', 'trucks', 'departure_hours',
                       'delivery_deadline_hours', 'capacity_resources', 'data_kind', 'sources'),
                 ('path_search', 'geography', 'slot_seconds'), 'road_network')
        self.search = n.get('path_search')
        if self.search is not None:
            keys(self.search, ('method', 'k', 'metrics'), 'path_search')
            if self.search['method'] != 'k_shortest':
                raise base.InputValidationError('path_search.method must be k_shortest')
            k = base._integer_value(self.search['k'], 'path_search.k', minimum=1)
            if k > 8:
                raise base.InputValidationError('path_search.k must be <=8')
            unique_strings(self.search['metrics'], {'distance', 'travel_time', 'transport_cost'}, 'path_search.metrics')
            if not self.search['metrics']:
                raise base.InputValidationError('path_search.metrics cannot be empty')
        self.geography = n.get('geography')
        if self.geography is not None:
            keys(self.geography, ('publisher', 'geometry_verified', 'topology_reviewed',
                                 'operating_values_verified', 'facility_access_verified',
                                 'coverage', 'assumptions'), 'geography')
            for field in ('geometry_verified', 'topology_reviewed', 'operating_values_verified', 'facility_access_verified'):
                if not isinstance(self.geography[field], bool):
                    raise base.InputValidationError('geography verification flags must be boolean')
            identifier(self.geography['publisher'], 'geography.publisher')
            identifier(self.geography['coverage'], 'geography.coverage')
            for assumption in sequence(self.geography['assumptions'], 'geography.assumptions', 32):
                if not isinstance(assumption, str) or not assumption.strip() or len(assumption) > 1000:
                    raise base.InputValidationError('geography assumptions must be text')
        self.start = parse_time(n['planning_start'], 'planning_start')
        self.slot = base._integer_value(n['slot_minutes'], 'slot_minutes', minimum=1)
        if self.slot > 60 or 60 % self.slot:
            raise base.InputValidationError('slot_minutes must divide 60 and be at most 60')
        self.slot_seconds = self.slot * 60
        if 'slot_seconds' in n:
            self.slot_seconds = base._integer_value(n['slot_seconds'], 'slot_seconds', minimum=1)
            if self.slot != 1 or self.slot_seconds > 60 or 60 % self.slot_seconds:
                raise base.InputValidationError('Sub-minute slot_seconds must divide 60; set slot_minutes=1')
            self.slot = self.slot_seconds / 60
        self.week_slots = 604800 // self.slot_seconds
        self.horizon = data.weeks[-1] * self.week_slots
        try:
            self.start + timedelta(minutes=self.horizon*self.slot)
        except OverflowError as error:
            raise base.InputValidationError('Planning dates exceed datetime range') from error
        if n['destination_site'] != data.selected_site:
            raise base.InputValidationError('road_network.destination_site must match selected_site')
        self.data_kind = n['data_kind']
        if self.data_kind not in ('synthetic', 'operational', 'official_geometry_scenario'):
            raise base.InputValidationError('Invalid road data_kind')
        if self.data_kind == 'official_geometry_scenario' and self.geography is None:
            raise base.InputValidationError('Official geometry scenarios require geography metadata')
        if self.data_kind == 'operational' and self.geography is not None and not all(
                self.geography[f] for f in ('geometry_verified', 'topology_reviewed',
                                           'operating_values_verified', 'facility_access_verified')):
            raise base.InputValidationError('Imported geometry has unverified operating/topology/facility values')
        self.sources = {}
        for raw_source in sequence(n['sources'], 'sources', 256 if self.search else 32):
            source = keys(raw_source, ('id', 'publisher', 'url', 'retrieved_at'), 'source')
            sid = identifier(source['id'], 'source.id')
            if sid in self.sources:
                raise base.InputValidationError('Duplicate source ID')
            identifier(source['publisher'], 'source.publisher')
            if not isinstance(source['url'], str) or urlparse(source['url']).scheme != 'https' or not urlparse(source['url']).netloc:
                raise base.InputValidationError('source.url must be an HTTPS URL')
            parse_time(source['retrieved_at'], 'source.retrieved_at')
            self.sources[sid] = dict(source)
        if self.data_kind != 'synthetic' and not self.sources:
            raise base.InputValidationError('Operational graphs require recorded sources')
        self.nodes = {}
        for raw_node in sequence(n['nodes'], 'nodes', 100000 if self.search else 32, 2):
            node = optional_keys(raw_node, ('id', 'label', 'rest_allowed'), ('coordinates',), 'node')
            nid = identifier(node['id'], 'node.id')
            if nid in self.nodes or not isinstance(node['rest_allowed'], bool):
                raise base.InputValidationError('Nodes need unique IDs and boolean rest_allowed')
            identifier(node['label'], 'node.label')
            self.nodes[nid] = dict(node)
            if 'coordinates' in node:
                self.nodes[nid]['coordinates'] = coordinates(node['coordinates'], 'node.coordinates')
        self.depot, self.destination = n['depot_node'], n['destination_node']
        if not isinstance(self.depot, str) or not isinstance(self.destination, str) or self.depot not in self.nodes or self.destination not in self.nodes or self.depot == self.destination:
            raise base.InputValidationError('Distinct declared depot_node and destination_node required')
        self.departures = [self.hour(h, 'departure_hours') for h in
                           sequence(n['departure_hours'], 'departure_hours', 128, 1)]
        if len(set(self.departures)) != len(self.departures):
            raise base.InputValidationError('departure_hours must be unique')
        self.departures.sort()
        values = base._normalize_week_mapping(n['delivery_deadline_hours'], 'delivery_deadline_hours')
        base._check_exact_keys(values, data.weeks, 'delivery_deadline_hours')
        self.deadlines = {}
        for w in data.weeks:
            value = values[w]
            k = self.hour(value, f'delivery_deadline_hours.{w}')
            if not (w - 1) * self.week_slots < k <= w * self.week_slots:
                raise base.InputValidationError('Each delivery deadline must be inside its own week (end inclusive)')
            self.deadlines[w] = k
        self.resources = {}
        for rid, windows in base._require_mapping(n['capacity_resources'], 'capacity_resources').items():
            identifier(rid, 'capacity_resource ID')
            cap = {}
            for a, b, raw_window in self.windows(windows, 'capacity_resource', extra=('max_entries',)):
                value = base._integer_value(raw_window['max_entries'], 'max_entries', minimum=0)
                cap.update({k: value for k in range(a, b)})
                if len(cap) > 1000000:
                    raise base.InputValidationError('Road capacity slot limit exceeded')
            self.resources[rid] = cap
        self.trucks = {}
        for raw_truck in sequence(n['trucks'], 'trucks', 24, 1):
            t = optional_keys(raw_truck, ('id', 'vehicle_type', 'payload_kg', 'tare_kg', 'max_gross_weight_kg',
                                 'volume_m3', 'height_m', 'width_m', 'loading_minutes',
                                 'unloading_minutes', 'turnaround_minutes', 'fixed_trip_cost',
                                 'cost_per_km', 'max_continuous_driving_minutes', 'break_minutes',
                                 'max_weekly_driving_minutes', 'max_two_week_driving_minutes',
                                 'availability'), ('allow_overnight_return', 'overnight_cost',
                                                   'cost_per_hour', 'minimum_trip_cost'), 'truck')
            tid = identifier(t['id'], 'truck.id')
            if tid in self.trucks:
                raise base.InputValidationError('Truck IDs must be unique')
            truck = dict(t)
            identifier(t['vehicle_type'], 'vehicle_type')
            for field in ('payload_kg', 'tare_kg', 'max_gross_weight_kg', 'volume_m3', 'height_m', 'width_m'):
                truck[field] = number(t[field], field, True)
            if truck['max_gross_weight_kg'] <= truck['tare_kg']:
                raise base.InputValidationError('Truck gross limit must exceed tare')
            for field in ('fixed_trip_cost', 'cost_per_km'):
                truck[field] = number(t[field], field)
            for field in ('overnight_cost', 'cost_per_hour', 'minimum_trip_cost'):
                truck[field] = number(t.get(field, 0), field)
            truck['allow_overnight_return'] = t.get('allow_overnight_return', False)
            if not isinstance(truck['allow_overnight_return'], bool):
                raise base.InputValidationError('allow_overnight_return must be boolean')
            for field in ('loading_minutes', 'unloading_minutes', 'turnaround_minutes', 'break_minutes'):
                truck[field + '_slots'] = math.ceil(number(t[field], field) / self.slot)
            continuous = number(t['max_continuous_driving_minutes'], 'max_continuous_driving_minutes', True)
            if continuous > 270 or number(t['break_minutes'], 'break_minutes') < 45:
                raise base.InputValidationError('Conservative policy requires driving blocks <=270 min and breaks >=45 min')
            truck['continuous_slots'] = math.floor(continuous / self.slot)
            if not truck['continuous_slots']:
                raise base.InputValidationError('Driving block is shorter than the time slot')
            for field, limit in (('max_weekly_driving_minutes', 3360), ('max_two_week_driving_minutes', 5400)):
                truck[field] = number(t[field], field, True)
                if truck[field] > limit:
                    raise base.InputValidationError(f'{field} exceeds conservative standard limit {limit}')
            windows = self.windows(t['availability'], 'truck.availability', extra=('max_driving_minutes',))
            truck['windows'] = []
            last_end = None
            consecutive = 0
            for a, b, raw_window in windows:
                driving = number(raw_window['max_driving_minutes'], 'max_driving_minutes', True)
                if driving > 540 or (b-a)*self.slot > 780:
                    raise base.InputValidationError('An approved duty window permits at most 9h driving within 13h duty')
                if last_end is not None and (a-last_end)*self.slot < 660:
                    raise base.InputValidationError('Duty windows require at least 11h intervening rest')
                consecutive = 1 if last_end is None or (a-last_end)*self.slot >= 2700 else consecutive+1
                if consecutive > 6:
                    raise base.InputValidationError('After six duty windows provide at least 45h rest')
                truck['windows'].append((a, b, driving))
                last_end = b
            self.trucks[tid] = truck
        types = {t['vehicle_type'] for t in self.trucks.values()}
        self.edges, self.adj = {}, defaultdict(list)
        point_count = 0
        for raw_edge in sequence(n['edges'], 'edges', 250000 if self.search else 128):
            e = optional_keys(raw_edge, ('id', 'from_node', 'to_node', 'road_name', 'distance_km',
                               'travel_minutes', 'toll_cost', 'max_gross_weight_kg',
                               'max_height_m', 'max_width_m', 'allowed_vehicle_types',
                               'allowed_items', 'open_windows', 'capacity_resource', 'source_id'),
                              ('geometry', 'source_feature_ids'), 'edge')
            eid = identifier(e['id'], 'edge.id')
            if eid in self.edges:
                raise base.InputValidationError('Edge IDs must be unique')
            if not isinstance(e['from_node'], str) or not isinstance(e['to_node'], str) or e['from_node'] not in self.nodes or e['to_node'] not in self.nodes or e['from_node'] == e['to_node']:
                raise base.InputValidationError('Edges must connect two distinct declared nodes')
            edge = dict(e)
            if 'geometry' in e:
                edge['geometry'] = [coordinates(p, 'edge.geometry') for p in
                                    sequence(e['geometry'], 'edge.geometry', 20000, 2)]
                point_count += len(edge['geometry'])
                if point_count > 5000000:
                    raise base.InputValidationError('Road geometry point limit exceeded')
                for nid, point in ((e['from_node'], edge['geometry'][0]), (e['to_node'], edge['geometry'][-1])):
                    expected = self.nodes[nid].get('coordinates')
                    if expected is not None and any(abs(a-b)>1e-8 for a,b in zip(expected,point)):
                        raise base.InputValidationError('Road geometry endpoints must match node coordinates')
            if 'source_feature_ids' in e:
                for fid in sequence(e['source_feature_ids'], 'source_feature_ids', 10000, 1):
                    identifier(fid, 'source_feature_id')
            identifier(e['road_name'], 'road_name')
            for field in ('distance_km', 'travel_minutes', 'max_gross_weight_kg', 'max_height_m', 'max_width_m'):
                edge[field] = number(e[field], field, True)
            edge['toll_cost'] = number(e['toll_cost'], 'toll_cost')
            edge['travel_slots'] = math.ceil(edge['travel_minutes'] / self.slot)
            edge['types'] = unique_strings(e['allowed_vehicle_types'], types, 'allowed_vehicle_types')
            edge['items'] = unique_strings(e['allowed_items'], base.ITEMS, 'allowed_items')
            edge['open'] = []
            for a,b,_ in self.windows(e['open_windows'], 'open_windows'):
                if edge['open'] and edge['open'][-1][1]==a:
                    edge['open'][-1]=(edge['open'][-1][0],b)
                else:
                    edge['open'].append((a,b))
            resource = e['capacity_resource']
            if resource is not None and (not isinstance(resource, str) or resource not in self.resources):
                raise base.InputValidationError('Edge capacity_resource must be declared')
            source = e['source_id']
            if source is not None and (not isinstance(source, str) or source not in self.sources):
                raise base.InputValidationError('Edge source_id must be declared')
            if self.data_kind != 'synthetic' and source is None:
                raise base.InputValidationError('Every operational edge requires source_id')
            self.edges[eid] = edge
            self.adj[edge['from_node']].append(eid)
        for es in self.adj.values():
            es.sort()

    def hour(self, value, path):
        slots = number(value, path) * 60 / self.slot
        if not math.isclose(slots, round(slots), abs_tol=1e-8, rel_tol=0) or slots > self.horizon:
            raise base.InputValidationError(f'{path} must align with the slot grid and lie inside the horizon')
        return round(slots)

    def windows(self, values, path, extra=()):
        windows = []
        for raw in sequence(values, path, 128):
            raw = keys(raw, ('start_hour', 'end_hour')+extra, path)
            a, b = self.hour(raw['start_hour'], path), self.hour(raw['end_hour'], path)
            if b <= a:
                raise base.InputValidationError(f'{path} has an empty/reversed window')
            windows.append((a,b,raw))
        windows.sort(key=lambda row: row[0])
        if any(a < windows[k-1][1] for k,(a,b,_) in enumerate(windows) if k):
            raise base.InputValidationError(f'{path} windows must not overlap')
        return windows

    def iso(self, slot):
        return (self.start + timedelta(minutes=slot*self.slot)).isoformat()

    def paths(self, start, end, truck):
        if self.search:
            from backend.road_paths import shortest_paths
            def permitted(e):
                return (truck['vehicle_type'] in e['types'] and truck['height_m'] <= e['max_height_m']
                        and truck['width_m'] <= e['max_width_m'] and truck['tare_kg'] <= e['max_gross_weight_kg']
                        and e['open'] and e['travel_slots'] <= truck['continuous_slots'])
            weights = {'distance': lambda e:e['distance_km'],
                       'travel_time': lambda e:e['travel_slots'],
                       'transport_cost': lambda e:e['toll_cost'] + e['distance_km']*truck['cost_per_km']}
            paths = set()
            for metric in self.search['metrics']:
                paths.update(shortest_paths(self.edges, self.adj, start, end, permitted,
                                            weights[metric], self.search['k']))
            return sorted(paths)
        found = []
        visits = 0
        def visit(node, seen, path):
            nonlocal visits
            visits += 1
            if visits > MAX_PATH_COMBINATIONS:
                raise base.InputValidationError('Road path search size exceeded; simplify the approved graph')
            if node == end:
                found.append(tuple(path))
                if len(found) > MAX_PATHS:
                    raise base.InputValidationError('More than 256 simple paths in a leg; simplify graph (no paths truncated)')
                return
            for eid in self.adj[node]:
                e = self.edges[eid]
                if e['to_node'] in seen or truck['vehicle_type'] not in e['types'] or truck['height_m'] > e['max_height_m'] or truck['width_m'] > e['max_width_m'] or truck['tare_kg'] > e['max_gross_weight_kg']:
                    continue
                visit(e['to_node'], seen | {e['to_node']}, path+[eid])
        visit(start, {start}, [])
        return found

    def break_positions(self, path, truck, continuous=0):
        """Latest permitted stops on a FIXED full driving path, including return.

        Look ahead over the entire tour: a necessary break can lie before the
        delivery stop, even when the outward leg alone is below the limit.
        This deterministic policy does not enumerate discretionary break times.
        """
        prefix=[0]
        for eid in path: prefix.append(prefix[-1]+self.edges[eid]['travel_slots'])
        chosen=set(); latest=None; last=-1; used=continuous
        for j,eid in enumerate(path):
            e=self.edges[eid]; duration=e['travel_slots']
            if duration>truck['continuous_slots']: return None
            if self.nodes[e['from_node']]['rest_allowed']: latest=j
            if used+duration>truck['continuous_slots']:
                if latest is None or latest<=last: return None
                used=prefix[j]-prefix[latest]
                if used+duration>truck['continuous_slots']: return None
                chosen.add(latest); last=latest
            used+=duration
        return chosen

    def leg(self, path, at, continuous, truck, phase, break_before=None):
        if break_before is None:
            break_before=self.break_positions(path,truck,continuous)
        if break_before is None: return None
        events, entries, drives = [], [], []
        for j,eid in enumerate(path):
            e = self.edges[eid]
            duration = e['travel_slots']
            if duration > truck['continuous_slots']:
                return None
            if j in break_before:
                if not self.nodes[e['from_node']]['rest_allowed']:
                    return None
                end_break = at + truck['break_minutes_slots']
                events.append(dict(kind='break', phase=phase, node=e['from_node'], start=at, end=end_break))
                at, continuous = end_break, 0
            if continuous + duration > truck['continuous_slots']:
                return None
            exit_slot = at + duration
            if not any(a <= at and exit_slot <= b for a,b in e['open']):
                return None
            if e['capacity_resource'] is not None:
                rid = e['capacity_resource']
                if self.resources[rid].get(at, 0) < 1:
                    return None
                entries.append((rid, at))
            events.append(dict(kind='drive', phase=phase, edge=eid, from_node=e['from_node'],
                               to_node=e['to_node'], road_name=e['road_name'], start=at, end=exit_slot))
            drives.extend(range(at, exit_slot))
            at, continuous = exit_slot, continuous + duration
        return at, continuous, events, entries, drives

    def tour(self, out, back, departure, load_start, truck):
        """Same-duty first; explicit next-duty return after >=11h daily rest.

        Each leg must fit its own duty driving cap. No mid-leg off-duty waiting.
        This bounded fallback does not enumerate a general multi-day VRP.
        """
        stops = self.break_positions(tuple(out)+tuple(back), truck)
        forward = None if stops is None else self.leg(out,departure,0,truck,'outbound',
                                                    {j for j in stops if j<len(out)})
        if forward is not None:
            delivered = forward[0]+truck['unloading_minutes_slots']
            backward = self.leg(back,delivered,forward[1],truck,'return',
                                {j-len(out) for j in stops if j>=len(out)})
            if backward is not None:
                release = backward[0]+truck['turnaround_minutes_slots']+(truck['break_minutes_slots'] if self.nodes[self.depot]['rest_allowed'] else 0)
                drive = len(forward[4])+len(backward[4])
                for k,(a,b,cap) in enumerate(truck['windows']):
                    if a<=load_start and release<=b and drive*self.slot<=cap:
                        return forward,backward,{k:drive*self.slot},None
        if not truck['allow_overnight_return'] or not self.nodes[self.destination]['rest_allowed']:
            return None
        stops = self.break_positions(out,truck)
        forward = None if stops is None else self.leg(out,departure,0,truck,'outbound',stops)
        if forward is None: return None
        delivered = forward[0]+truck['unloading_minutes_slots']
        first = next((k for k,(a,b,cap) in enumerate(truck['windows'])
                      if a<=load_start and delivered<=b and len(forward[4])*self.slot<=cap),None)
        if first is None or first+1>=len(truck['windows']): return None
        a,b,cap = truck['windows'][first+1]
        if not 660 <= (a-delivered)*self.slot <= 2160: return None
        stops = self.break_positions(back,truck)
        backward = None if stops is None else self.leg(back,a,0,truck,'return',stops)
        if backward is None: return None
        release = backward[0]+truck['turnaround_minutes_slots']+(truck['break_minutes_slots'] if self.nodes[self.depot]['rest_allowed'] else 0)
        if release>b or len(backward[4])*self.slot>cap: return None
        rest = dict(kind='daily_rest',phase='destination_overnight',node=self.destination,start=delivered,end=a)
        return forward,backward,{first:len(forward[4])*self.slot,first+1:len(backward[4])*self.slot},rest

    def candidates(self):
        result, evaluated, drive_slots = {}, 0, 0
        for tid, t in self.trucks.items():
            outs, backs = self.paths(self.depot, self.destination, t), self.paths(self.destination, self.depot, t)
            for departure in self.departures:
                load_start = departure - t['loading_minutes_slots']
                if load_start < 0:
                    continue
                for out in outs:
                    for back in backs:
                        evaluated += 1
                        if evaluated > MAX_PATH_COMBINATIONS:
                            raise base.InputValidationError('Road tour enumeration exceeds 100000 combinations; simplify graph/grid')
                        tour = self.tour(out,back,departure,load_start,t)
                        if tour is None: continue
                        forward,backward,window_driving,overnight = tour
                        arrival,continuous,events,entries,drives=forward
                        delivered=arrival+t['unloading_minutes_slots']
                        arrival_week=next((w for w,k in self.deadlines.items() if delivered<=k),None)
                        if arrival_week is None: continue
                        returned, _, return_events, return_entries, return_drives = backward
                        # Reset driving only through an explicit depot break,
                        # never by calling loading or turnaround a driver rest.
                        depot_break = t['break_minutes_slots'] if self.nodes[self.depot]['rest_allowed'] else 0
                        turnaround_start = returned + depot_break
                        release = turnaround_start + t['turnaround_minutes_slots']
                        driving = drives + return_drives
                        allowed = set(base.ITEMS)
                        for eid in out:
                            allowed &= self.edges[eid]['items']
                        payload = min(t['payload_kg'], t['max_gross_weight_kg']-t['tare_kg'],
                                      *(self.edges[eid]['max_gross_weight_kg']-t['tare_kg'] for eid in out))
                        distance = sum(self.edges[eid]['distance_km'] for eid in out+back)
                        rest_slots = 0 if overnight is None else overnight['end']-overnight['start']
                        billable_hours = (returned-load_start-rest_slots)*self.slot/60
                        breakdown = dict(fixed=t['fixed_trip_cost'],distance=distance*t['cost_per_km'],
                                         time=billable_hours*t['cost_per_hour'],
                                         overnight=0 if overnight is None else t['overnight_cost'],
                                         toll=sum(self.edges[eid]['toll_cost'] for eid in out+back))
                        subtotal = breakdown['fixed']+breakdown['distance']+breakdown['time']
                        breakdown['minimum_adjustment'] = max(0,t['minimum_trip_cost']-subtotal)
                        cost = sum(breakdown.values())
                        if not math.isfinite(cost) or not math.isfinite(distance):
                            raise base.InputValidationError('Road tour distance/cost overflow')
                        if not allowed or payload <= 0:
                            continue
                        key = f'tour-{len(result)+1:05d}'
                        drive_slots += len(driving)
                        if drive_slots > 2000000:
                            raise base.InputValidationError('Road driving slot work limit exceeded; reduce grid or candidates')
                        timeline = [dict(kind='load', node=self.depot, start=load_start, end=departure)] + events + [
                            dict(kind='unload', node=self.destination, start=arrival, end=delivered)] + ([] if overnight is None else [overnight]) + return_events
                        if depot_break:
                            timeline.append(dict(kind='break', phase='depot_rest', node=self.depot,
                                                  start=returned, end=turnaround_start))
                        timeline.append(dict(kind='turnaround', node=self.depot, start=turnaround_start, end=release))
                        result[key] = dict(id=key, truck_id=tid, departure=departure, load_start=load_start,
                                           arrival=arrival, delivered=delivered, returned=returned, release=release,
                                           arrival_week=arrival_week, departure_week=departure//self.week_slots+1,
                                           window_driving=window_driving, outbound=out, returning=back, timeline=timeline,
                                           entries=Counter(entries+return_entries), drives=driving,
                                           allowed_items=allowed, payload=payload, volume=t['volume_m3'],
                                           distance=distance, cost=cost, cost_breakdown=breakdown,
                                           billable_hours=billable_hours)
                        if len(result) > MAX_CANDIDATES:
                            raise base.InputValidationError('More than 4096 feasible tours; simplify graph/grid (no candidates truncated)')
        return result, evaluated


@dataclass
class RoadTransport:
    graph: Graph
    candidates: dict
    trip: dict
    routes: dict
    lots: list
    enumerated: int

    def tie_breaks(self):
        return [('stage_6_driving_tiebreak', {self.trip[k,c['departure_week']]: len(c['drives']) for k,c in self.candidates.items()}),
                ('stage_7_departure_tiebreak', {self.trip[k,c['departure_week']]: c['departure'] for k,c in self.candidates.items()})]

    def format_and_verify(self, result, x, lots, weights, data):
        g = self.graph
        plans, usage = [], Counter()
        occupied, driven, window_drive = defaultdict(list), Counter(), Counter()
        for key,c in self.candidates.items():
            z = x[self.trip[key,c['departure_week']]]
            cargo_lots = [b for b in lots if b.route == key and b.order is not None]
            cargo = {i: sum(max(0.,float(x[b.order])) for b in cargo_lots if b.item == i) for i in base.ITEMS}
            weight = sum(cargo[i]*weights[i] for i in base.ITEMS)
            volume = sum(cargo[i]*data.item_volume_m3[i] for i in base.ITEMS)
            if not z:
                if any(q > 1e-5 for q in cargo.values()):
                    raise base.OptimizationError('Cargo assigned to unused road tour', stage='road verification')
                continue
            if z != 1 or weight > c['payload']+1e-5 or volume > c['volume']+1e-5:
                raise base.OptimizationError('Road truck load verification failed', stage='road verification')
            t = g.trucks[c['truck_id']]
            for b in cargo_lots:
                if x[b.order] <= 1e-6:
                    continue
                if b.item not in c['allowed_items'] or (b.item in base.DISCRETE_ITEMS and abs(x[b.order]-round(x[b.order]))>1e-5):
                    raise base.OptimizationError('Road item/integrality verification failed', stage='road verification')
                if b.arrival != c['arrival_week'] or (b.expiry_slot is not None and g.deadlines[b.arrival]>=b.expiry_slot):
                    raise base.OptimizationError('Road delivery/expiry verification failed', stage='road verification')
            continuous = 0
            for event in c['timeline']:
                if event['kind'] in ('break','daily_rest'):
                    required = 660 if event['kind']=='daily_rest' else t['break_minutes']
                    if not g.nodes[event['node']]['rest_allowed'] or (event['end']-event['start'])*g.slot < required:
                        raise base.OptimizationError('Road rest verification failed', stage='road verification')
                    continuous = 0
                if event['kind']!='drive':
                    continue
                e = g.edges[event['edge']]
                gross = t['tare_kg'] + (weight if event['phase']=='outbound' else 0)
                continuous += event['end']-event['start']
                if continuous>t['continuous_slots'] or gross>e['max_gross_weight_kg']+1e-5 or not any(a<=event['start'] and event['end']<=b for a,b in e['open']):
                    raise base.OptimizationError('Road segment verification failed', stage='road verification')
            usage.update(c['entries'])
            occupied[c['truck_id']].append((c['load_start'],c['release']))
            for window,minutes in c['window_driving'].items():
                window_drive[c['truck_id'],window] += minutes
            for k in c['drives']:
                driven[c['truck_id'],k//g.week_slots+1] += g.slot
            timeline = [{k:v for k,v in event.items() if k not in ('start','end')} |
                        dict(start_at=g.iso(event['start']), end_at=g.iso(event['end'])) for event in c['timeline']]
            plans.append(dict(trip_id=key, truck_id=c['truck_id'], vehicle_type=g.trucks[c['truck_id']]['vehicle_type'],
                              origin_node=g.depot, destination_node=g.destination, destination_site=data.selected_site,
                              load_start_at=g.iso(c['load_start']), departure_at=g.iso(c['departure']),
                              arrival_at=g.iso(c['arrival']), delivery_complete_at=g.iso(c['delivered']),
                              return_at=g.iso(c['returned']), available_again_at=g.iso(c['release']),
                              departure_week=c['departure_week'], arrival_week=c['arrival_week'],
                              cargo=cargo, cargo_units=dict(base.ITEM_UNITS), cargo_lots=[
                                  dict(lot_id=b.id, item=b.item, quantity=float(x[b.order]), order_week=b.order_week,
                                       expiry_week=b.expiry, expires_at=None if b.expiry_slot is None else g.iso(b.expiry_slot))
                                  for b in cargo_lots if x[b.order]>1e-6],
                              weight_kg=weight, volume_m3=volume, payload_limit_kg=c['payload'],
                              volume_limit_m3=c['volume'], outbound_edges=list(c['outbound']),
                              return_edges=list(c['returning']), route_nodes=[g.depot]+[g.edges[e]['to_node'] for e in c['outbound']],
                              driving_minutes=len(c['drives'])*g.slot, round_trip_distance_km=c['distance'],
                              unrounded_driving_minutes=sum(g.edges[e]['travel_minutes'] for e in c['outbound']+c['returning']),
                              transport_cost=c['cost'], cost_breakdown=c['cost_breakdown'],
                              billable_hours=c['billable_hours'],
                              overnight_return=any(e['kind']=='daily_rest' for e in timeline), timeline=timeline))
        for (rid,k),value in usage.items():
            if value > g.resources[rid].get(k,0):
                raise base.OptimizationError('Road capacity verification failed', stage='road verification')
        for tid,intervals in occupied.items():
            intervals.sort()
            if any(a < intervals[j-1][1] for j,(a,b) in enumerate(intervals) if j):
                raise base.OptimizationError('Truck used before return/turnaround', stage='road verification')
        for (tid,k),minutes in window_drive.items():
            if minutes > g.trucks[tid]['windows'][k][2]+1e-5:
                raise base.OptimizationError('Driver duty-window limit exceeded', stage='road verification')
        for tid,t in g.trucks.items():
            for w in data.weeks:
                if driven[tid,w] > t['max_weekly_driving_minutes']+1e-5 or driven[tid,w]+driven[tid,w+1] > t['max_two_week_driving_minutes']+1e-5:
                    raise base.OptimizationError('Driver weekly limit exceeded', stage='road verification')
        plans.sort(key=lambda p:(p['departure_at'],p['truck_id'],p['trip_id']))
        if abs(sum(p['transport_cost'] for p in plans)-result['summary']['transport_cost'])>1e-5:
            raise base.OptimizationError('Road transport cost reconciliation failed', stage='road verification')
        result['truck_plan'] = plans
        for p in plans:
            p['time_rounding_added_minutes'] = p['driving_minutes']-p['unrounded_driving_minutes']
            for phase, field in (('outbound', 'outbound_edges'), ('return', 'return_edges')):
                p[phase+'_geometry'] = [dict(edge_id=eid, source_id=g.edges[eid]['source_id'],
                                            source_feature_ids=g.edges[eid].get('source_feature_ids', []),
                                            coordinates=g.edges[eid].get('geometry', [])) for eid in p[field]]
        result['transport_plan'] = [dict(route=p['trip_id'], truck_id=p['truck_id'], week=p['departure_week'],
                                          arrival_week=p['arrival_week'], trips=1, vehicle_type=p['vehicle_type'],
                                          cargo=p['cargo'], weight_kg=p['weight_kg'], volume_m3=p['volume_m3'],
                                          departure_at=p['departure_at'], arrival_at=p['arrival_at'],
                                          outbound_edges=p['outbound_edges'], return_edges=p['return_edges']) for p in plans]
        for order in result['order_plan']:
            c = self.candidates[order['route']]
            order.update(trip_id=c['id'], truck_id=c['truck_id'], load_start_at=g.iso(c['load_start']),
                         dispatch_at=g.iso(c['departure']), delivery_complete_at=g.iso(c['delivered']))
        result['road_capacity_usage'] = [dict(resource=rid, entry_at=g.iso(k), entries=value,
                                               max_entries=g.resources[rid].get(k,0)) for (rid,k),value in sorted(usage.items())]
        result['model_info'].update(road_network_enabled=True, road_graph_data_kind=g.data_kind,
                                    geography=g.geography,
                                    operational_ready=False,
                                    operational_data_declared=(g.data_kind=='operational'),
                                    path_search=g.search or dict(method='all_simple'),
                                    break_policy='Same-duty first; latest reachable declared rest nodes. Optional next-duty return uses 11..36h destination rest and separate per-duty driving limits. Node permissions are input assumptions.',
                                    transport_cost_policy='max(minimum_trip_cost, fixed + distance + on-duty hours) + overnight supplement + toll; on-duty hours exclude destination daily rest and post-return depot handling. Missing extras default to excluded zero.',
                                    road_graph_sources=list(g.sources.values()),
                                    sources=result['model_info']['sources']+SOURCES,
                                    road_candidates=len(self.candidates), path_combinations_evaluated=self.enumerated,
                                    slot_minutes=g.slot, slot_seconds=g.slot_seconds, planning_start=g.iso(0),
                                    delivery_deadlines={w:g.iso(k) for w,k in g.deadlines.items()},
                                    time_convention='Travel/loading/unloading/break/lead minutes rounded up to slots; weekly demand usable only at/after delivery completion and before expiry at its explicit weekly deadline.',
                                    optimization_method=('Joint cargo and binary named-truck tour MILP; lexicographic ' + ('fairness, ' if data.priority == 'fairness' else '') + 'weighted unmet, total cost, waste, tours, driving, departure.'),
                                    road_search_scope=('Explicit k-shortest candidate union by supplied metrics, every supplied departure slot. MILP optimality is conditional on this pool; no global network optimality claim.' if g.search else
                                                       'All simple outbound and return paths on supplied directed graph, every supplied departure slot; size limits fail explicitly, no top-k truncation.'),
                                    limitations=[
                                        'One origin depot and one selected relief site; each loaded tour visits the site once and returns empty.',
                                        'Supplied graph and departure grid only; imported regional geometry is not a live traffic feed or certified truck navigation.',
                                        'No discretionary en-route waiting, rerouting mid-trip or alternate origins; insert intermediate rest nodes for long edges.',
                                        'Breaks use a deterministic latest-permitted-stop policy. Other break timing choices may make a closed-window route feasible and are not enumerated.',
                                        'Weekly demand deadlines, fixed supplier readiness at order-week start plus lead; warehouse conservatively batches receipts before weekly distribution.',
                                        'One assigned driver per truck; approved duty windows and pre-horizon rest are inputs. Conservative standard driving/break limits do not certify all EU labor, derogation, tachograph or axle-load compliance.',
                                        'Prepaid pipeline deliveries already booked; availability and road capacities must be net of existing bookings.',
                                        'Initial/pipeline expiry remains first unusable week; actual manufacturer shelf-life and packed weights required.',
                                        'Operational provenance is caller-recorded, not independently authenticated by the solver.'])
        result['summary']['planned_truck_trips'] = len(plans)
        result['summary']['round_trip_distance_km'] = sum(p['round_trip_distance_km'] for p in plans)


def build_road_transport(model, data, weights, logistics, Lot):
    g = Graph(logistics['road_network'], data)
    candidates, evaluated = g.candidates()
    trips, routes, lots = {}, {}, []
    for key,c in candidates.items():
        w = c['departure_week']
        z = trips[key,w] = model.var(('road_tour',key), 1, True)
        routes[key] = dict(trip_cost=c['cost'], corridor=None, corridor_lag=0,
                           vehicle_type=g.trucks[c['truck_id']]['vehicle_type'],
                           lag=c['arrival_week']-w, busy=max(1,math.ceil((c['release']-c['departure'])*g.slot/10080)))
        for i in base.ITEMS:
            if i not in c['allowed_items']:
                continue
            lead_days = number(logistics['procurement_lead_days'][i], 'procurement_lead_days')
            if lead_days > data.weeks[-1]*7:
                continue # No horizon order can become available; avoid numeric overflow.
            lead = math.ceil(lead_days * 1440 / g.slot)
            raw_shelf = logistics['shelf_life_days'][i]
            shelf_days = None if raw_shelf is None else number(raw_shelf, 'shelf_life_days', True)
            if shelf_days is not None and shelf_days > 1000000:
                raise base.InputValidationError('road shelf_life_days must be at most 1000000 days')
            shelf = None if shelf_days is None else math.floor(shelf_days*1440/g.slot)
            expiry_slot = None if shelf is None else c['departure']+shelf
            if expiry_slot is not None:
                try:
                    g.start+timedelta(minutes=expiry_slot*g.slot)
                except OverflowError as error:
                    raise base.InputValidationError('Shelf expiry exceeds datetime range') from error
            expiry_week = None if expiry_slot is None else next((week for week,deadline in g.deadlines.items() if deadline >= expiry_slot), data.weeks[-1]+1)
            if expiry_week is not None and c['arrival_week'] >= expiry_week:
                continue
            for o in data.weeks:
                ready = (o-1)*g.week_slots+lead
                if ready > c['load_start']:
                    continue
                cap = data.weekly_supply[i][o]
                k = model.var(('road_order',i,o,key), cap, i in base.DISCRETE_ITEMS)
                lots.append(Lot(f'order:{i}:{o}:{key}',i,c['arrival_week'],expiry_week,cap,k,o,w,key,expiry_slot))
                if len(lots)>MAX_ORDER_LOTS:
                    raise base.InputValidationError('More than 1024 road order lots; simplify graph/grid (no lots truncated)')
        loaded = [b for b in lots if b.route == key]
        model.constraint({b.order:weights[b.item] for b in loaded} | {z:-c['payload']}, upper=0)
        model.constraint({b.order:data.item_volume_m3[b.item] for b in loaded} | {z:-c['volume']}, upper=0)
        if not loaded:
            model.constraint({z:1}, upper=0)
    # Physical truck occupancy: all load/drive/rest/unload/return/turnaround time.
    # Check every interval start; the active set only grows there.
    for tid,t in g.trucks.items():
        own = [(key,c) for key,c in candidates.items() if c['truck_id']==tid]
        for at in sorted({c['load_start'] for _,c in own}):
            model.constraint({trips[key,c['departure_week']]:1 for key,c in own
                              if c['load_start'] <= at < c['release']}, upper=1)
        for k,(_,_,cap) in enumerate(t['windows']):
            model.constraint({trips[key,c['departure_week']]:c['window_driving'][k]
                              for key,c in own if k in c['window_driving']}, upper=cap)
            if not g.nodes[g.depot]['rest_allowed']:
                model.constraint({trips[key,c['departure_week']]:1 for key,c in own if k in c['window_driving']}, upper=1)
        weekly = {w:{trips[key,c['departure_week']]:sum(1 for at in c['drives'] if at//g.week_slots+1==w)*g.slot
                      for key,c in own} for w in data.weeks}
        for w in data.weeks:
            model.constraint(weekly[w], upper=t['max_weekly_driving_minutes'])
            terms = Counter(weekly[w]); terms.update(weekly.get(w+1,{}))
            model.constraint(dict(terms), upper=t['max_two_week_driving_minutes'])
    # Both loaded outward and empty return entries consume shared resources.
    resource_terms = defaultdict(dict)
    for key,c in candidates.items():
        for resource, count in c['entries'].items():
            resource_terms[resource][trips[key,c['departure_week']]] = count
    for (rid,at),terms in resource_terms.items():
        model.constraint(terms, upper=g.resources[rid].get(at,0))
    return RoadTransport(g,candidates,trips,routes,lots,evaluated)


def example_road_logistics(selected_site='Medyka'):
    """Synthetic graph/vehicles; exclusively a reproducible test/example fixture."""
    from backend.logistics import example_logistics
    l = example_logistics(selected_site)
    for field in ('vehicles', 'routes', 'corridors'):
        del l[field]
    nodes = [dict(id=k,label='Synthetic '+k,rest_allowed=True) for k in ('depot','north','south','site')]
    edges = []
    for a,b,minutes,km in (('depot','north',60,20), ('north','site',60,20),
                            ('depot','south',90,30), ('south','site',90,30)):
        for origin,dest in ((a,b),(b,a)):
            edges.append(dict(id=origin+'-'+dest,from_node=origin,to_node=dest,
                              road_name='Synthetic road '+origin+'-'+dest, distance_km=km,
                              travel_minutes=minutes,toll_cost=0,max_gross_weight_kg=10000,
                              max_height_m=4.5,max_width_m=3,allowed_vehicle_types=['rigid'],
                              allowed_items=list(base.ITEMS),open_windows=[dict(start_hour=0,end_hour=672)],
                              capacity_resource=None,source_id=None))
    trucks = []
    for tid in ('truck-01','truck-02'):
        trucks.append(dict(id=tid,vehicle_type='rigid',payload_kg=2000,tare_kg=5000,
                           max_gross_weight_kg=7500,volume_m3=10,height_m=3.5,width_m=2.5,
                           loading_minutes=30,unloading_minutes=30,turnaround_minutes=30,
                           fixed_trip_cost=100,cost_per_km=1,max_continuous_driving_minutes=270,
                           break_minutes=45,max_weekly_driving_minutes=3360,max_two_week_driving_minutes=5400,
                           availability=[dict(start_hour=168*w+8.5,end_hour=168*w+21.5,max_driving_minutes=540)
                                         for w in range(4)]))
    l['road_network'] = dict(planning_start='2026-10-05T00:00:00+02:00',slot_minutes=30,
                             destination_site=selected_site,depot_node='depot',destination_node='site',
                             nodes=nodes,edges=edges,trucks=trucks,
                             departure_hours=[168*w+h for w in range(4) for h in (9,15.5)],
                             delivery_deadline_hours={w:168*(w-1)+20 for w in range(1,5)},
                             capacity_resources={},data_kind='synthetic',sources=[])
    return l

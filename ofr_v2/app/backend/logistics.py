"""Lot-tracked MILP with weekly routes or joint road tours. See docs/.

All capacities, times, costs and shelf lives are caller-supplied operational
parameters. No official document supplies universal values for these fields.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_array

from backend import optimization as base

SOURCES = [
    {"publisher": "WFP Logistics Cluster", "title": "Sending Goods by Road",
     "url": "https://log.logcluster.org/en/sending-goods-road"},
    {"publisher": "WFP Logistics Cluster", "title": "Unique Concepts to Road Transportation",
     "url": "https://log.logcluster.org/en/unique-concepts-road-transportation"},
    {"publisher": "WFP Logistics Cluster", "title": "Procurement",
     "url": "https://log.logcluster.org/en/procurement"},
    {"publisher": "WFP Logistics Cluster", "title": "Physical Storage Guidelines",
     "url": "https://log.logcluster.org/en/physical-storage-guidelines"},
]


def _num(v, path, positive=False):
    return base._finite_number(v, path, minimum=0, strictly_positive=positive)


def _keys(v, keys, path):
    v = base._require_mapping(v, path)
    base._check_exact_keys(v, keys, path)
    return v


def _weekly(v, weeks, path, integer=False):
    values = base._normalize_week_mapping(v, path)
    base._check_exact_keys(values, weeks, path)
    if integer:
        for w, n in values.items():
            base._integer_value(n, f"{path}[{w}]")
    return values


def _expiry(value, path):
    # First UNUSABLE week; zero/negative values can represent already expired lots.
    if value is None:
        return None
    return base._integer_value(value, path, minimum=-100000)


@dataclass
class Lot:
    id: str
    item: str
    arrival: int
    expiry: int | None
    quantity: float
    order: int | None = None
    order_week: int | None = None
    dispatch_week: int | None = None
    route: str | None = None
    expiry_slot: int | None = None


class Model:
    def __init__(self):
        self.names, self.lo, self.hi, self.integer = [], [], [], []
        self.rows, self.lower, self.upper = [], [], []
        self.stage_reports = []

    def var(self, name, upper, integer=False):
        if not math.isfinite(float(upper)) or upper < 0:
            raise base.InputValidationError(f"Invalid numerical variable bound for {name}")
        k = len(self.names)
        self.names.append(name)
        self.lo.append(0.)
        self.hi.append(float(upper))
        self.integer.append(int(integer))
        return k

    def constraint(self, terms, lower=-np.inf, upper=np.inf):
        self.rows.append({k: v for k, v in terms.items() if v})
        self.lower.append(lower)
        self.upper.append(upper)

    def solve(self, stages, config):
        rr, cc, vv = [], [], []
        for row, terms in enumerate(self.rows):
            for col, value in terms.items():
                rr.append(row); cc.append(col); vv.append(value)
        matrix = csc_array((np.array(vv, dtype=float),
                            (np.array(rr, dtype=np.int32), np.array(cc, dtype=np.int32))),
                           shape=(len(self.rows), len(self.names)))
        constraints = [LinearConstraint(matrix, self.lower, self.upper)]
        objectives = {}
        for name, terms in stages:
            c = np.zeros(len(self.names))
            for k, value in terms.items():
                c[k] = value
            try:
                result = milp(c, integrality=np.array(self.integer),
                              bounds=Bounds(self.lo, self.hi), constraints=constraints,
                              options={"time_limit": config.time_limit_seconds,
                                       "mip_rel_gap": config.mip_rel_gap, "presolve": True})
            except (ValueError, RuntimeError) as error:
                raise base.OptimizationError(str(error), stage=name, status='exception') from error
            if result.status != 0 or result.x is None or not np.all(np.isfinite(result.x)):
                raise base.OptimizationError("Logistics model did not prove an optimal solution",
                                             status=result.status, stage=name,
                                             solver_message=str(result.message))
            # HiGHS may report integral variables just below their integer value.
            # Locking raw fun (e.g. 2.9999996 tours) can exclude the actual integer
            # incumbent from the next stage. Re-evaluate every lock using rounded
            # discrete coordinates; retain the configured objective tolerance.
            discrete = np.asarray(self.integer, dtype=bool)
            if np.any(np.abs(result.x[discrete]-np.round(result.x[discrete]))>1e-5):
                raise base.OptimizationError('Nonintegral logistics stage solution', stage=name)
            lock_x = np.asarray(result.x).copy()
            lock_x[discrete] = np.round(lock_x[discrete])
            lock_value = float(c @ lock_x)
            objectives[name] = lock_value
            self.stage_reports.append(dict(stage=name, status=int(result.status),
                                           objective=lock_value,
                                           raw_solver_objective=float(result.fun),
                                           integrality_lock_adjustment=lock_value-float(result.fun),
                                           mip_gap=float(result.mip_gap) if getattr(result, 'mip_gap', None) is not None else None))
            constraints.append(LinearConstraint(csc_array(c.reshape(1, -1)),
                                                 -np.inf, lock_value + config.objective_tolerance))
        x = np.asarray(result.x)
        discrete = np.asarray(self.integer, dtype=bool)
        if np.any(np.abs(x[discrete] - np.round(x[discrete])) > 1e-5):
            raise base.OptimizationError("Nonintegral logistics solution", stage="verification")
        x[discrete] = np.round(x[discrete])
        x[np.abs(x) < 1e-8] = 0
        # Verify all original constraints and all preceding objective locks AFTER rounding.
        for constraint in constraints:
            y = np.asarray(constraint.A @ x).ravel()
            if np.any(y < np.asarray(constraint.lb) - 1e-5) or np.any(y > np.asarray(constraint.ub) + 1e-5):
                raise base.OptimizationError("Logistics constraint verification failed",
                                             stage="post-solve verification")
        if np.any(x < np.array(self.lo) - 1e-5) or np.any(x > np.array(self.hi) + 1e-5):
            raise base.OptimizationError("Logistics bound verification failed", stage="verification")
        return x, objectives


def optimize_logistics(ml_forecast, user_input, item_volume_m3, logistics,
                       item_weights=None, solver_config=None):
    data = base._normalize_and_validate(ml_forecast, user_input, item_volume_m3,
                                        item_weights, solver_config)
    demands = base._calculate_demands(data)
    weeks, items, site = data.weeks, base.ITEMS, data.selected_site
    end = weeks[-1]
    raw = base._require_mapping(logistics, "logistics")
    road_mode = "road_network" in raw
    common = ("item_weight_kg", "procurement_lead_days", "shelf_life_days",
              "initial_lots", "pipeline_lots", "disposal_cost", "disposal_capacity")
    l = _keys(raw, common + (("road_network",) if road_mode else
                            ("vehicles", "routes", "corridors")), "logistics")
    weights = {i: _num(v, f"item_weight_kg.{i}", True)
               for i, v in _keys(l["item_weight_kg"], items, "item_weight_kg").items()}
    procurement = {i: math.ceil(_num(v, f"procurement_lead_days.{i}") / 7)
                   for i, v in _keys(l["procurement_lead_days"], items, "procurement_lead_days").items()}
    shelf = {i: None if v is None else math.floor(_num(v, f"shelf_life_days.{i}", True) / 7)
             for i, v in _keys(l["shelf_life_days"], items, "shelf_life_days").items()}
    disposal_cost = {i: _num(v, f"disposal_cost.{i}")
                     for i, v in _keys(l["disposal_cost"], items, "disposal_cost").items()}
    disposal_cap = {i: _weekly(v, weeks, f"disposal_capacity.{i}", i in base.DISCRETE_ITEMS)
                    for i, v in _keys(l["disposal_capacity"], items, "disposal_capacity").items()}
    if not road_mode:
        vehicles = base._require_mapping(l["vehicles"], "vehicles")
        if not vehicles:
            raise base.InputValidationError("vehicles must contain at least one vehicle type")
        fleet = {}
        for key, v in vehicles.items():
            if not isinstance(key, str) or not key:
                raise base.InputValidationError("Vehicle type IDs must be nonempty strings")
            v = _keys(v, ("payload_kg", "volume_m3", "available"), f"vehicles.{key}")
            fleet[key] = dict(payload_kg=_num(v["payload_kg"], f"vehicles.{key}.payload_kg", True),
                              volume_m3=_num(v["volume_m3"], f"vehicles.{key}.volume_m3", True),
                              available=_weekly(v["available"], weeks, f"vehicles.{key}.available", True))
        corridors = {}
        for key, value in base._require_mapping(l["corridors"], "corridors").items():
            corridors[key] = _weekly(value, weeks, f"corridors.{key}", True)
        if not isinstance(l["routes"], list) or not 1 <= len(l["routes"]) <= 16:
            raise base.InputValidationError("routes must be a list of 1..16 pre-approved alternatives")
        routes = {}
        for raw in l["routes"]:
            r = _keys(raw, ("id", "destination", "vehicle_type", "transit_days", "round_trip_days",
                            "trip_cost", "max_trips", "max_weight_kg", "max_volume_m3",
                            "corridor", "corridor_delay_days", "allowed_items"), "route")
            key = r["id"]
            if not isinstance(key, str) or not key or key in routes:
                raise base.InputValidationError("Route IDs must be nonempty and unique")
            if r["destination"] != site or not isinstance(r["vehicle_type"], str) or r["vehicle_type"] not in fleet:
                raise base.InputValidationError("Route destination/vehicle type does not match scenario")
            if r["corridor"] is not None and (not isinstance(r["corridor"], str) or r["corridor"] not in corridors):
                raise base.InputValidationError("Route corridor must be declared in corridors")
            allowed = r["allowed_items"]
            if not isinstance(allowed, list) or any(not isinstance(i, str) or i not in items for i in allowed) or len(set(allowed)) != len(allowed):
                raise base.InputValidationError("allowed_items must contain distinct known item names")
            transit = _num(r["transit_days"], f"routes.{key}.transit_days")
            crossing = _num(r["corridor_delay_days"], f"routes.{key}.corridor_delay_days")
            if crossing > transit or (r["corridor"] is None and crossing != 0):
                raise base.InputValidationError("corridor_delay_days must fall between departure and arrival")
            cycle = _num(r["round_trip_days"], f"routes.{key}.round_trip_days")
            if cycle < transit:
                raise base.InputValidationError("round_trip_days cannot be less than transit_days")
            routes[key] = dict(r, lag=math.ceil(transit / 7), corridor_lag=math.ceil(crossing / 7), busy=max(1, math.ceil(cycle / 7)),
                               trip_cost=_num(r["trip_cost"], f"routes.{key}.trip_cost"),
                               max_trips=_weekly(r["max_trips"], weeks, f"routes.{key}.max_trips", True),
                               max_weight_kg=_weekly(r["max_weight_kg"], weeks, f"routes.{key}.max_weight_kg"),
                               max_volume_m3=_weekly(r["max_volume_m3"], weeks, f"routes.{key}.max_volume_m3"))
    m = Model()
    lots, ids = [], set()
    for kind in ("initial_lots", "pipeline_lots"):
        raw_lots = l[kind]
        if not isinstance(raw_lots, list) or len(raw_lots) > 64:
            raise base.InputValidationError(f"{kind} must be a list with at most 64 lots")
        for raw in raw_lots:
            expected = ("id", "item", "quantity", "expiry_week") + (("arrival_week",) if kind == "pipeline_lots" else ())
            v = _keys(raw, expected, kind)
            if not isinstance(v["id"], str) or not v["id"] or v["id"] in ids or v["id"].startswith("order:"):
                raise base.InputValidationError("Lot IDs must be unique; 'order:' prefix is reserved")
            ids.add(v["id"])
            if not isinstance(v["item"], str) or v["item"] not in items:
                raise base.InputValidationError("Unknown lot item")
            i = v["item"]
            q = _num(v["quantity"], f"{kind}.{v['id']}.quantity")
            if i in base.DISCRETE_ITEMS:
                base._integer_value(q, f"{kind}.{v['id']}.quantity")
            expiry = _expiry(v["expiry_week"], f"{kind}.{v['id']}.expiry_week")
            if shelf[i] is not None and expiry is None:
                raise base.InputValidationError(f"Perishable {i} requires a lot expiry_week")
            arrival = 1 if kind == "initial_lots" else base._integer_value(v["arrival_week"], "arrival_week", minimum=1)
            if arrival > end:
                raise base.InputValidationError("pipeline arrival_week must fall within the planning horizon")
            lots.append(Lot(v["id"], i, arrival, expiry, q))
    for i in items:
        total = sum(b.quantity for b in lots if b.item == i and b.id in {v['id'] for v in l['initial_lots']})
        if not math.isclose(total, data.initial_inventory[site][i], abs_tol=1e-6, rel_tol=0):
            raise base.InputValidationError(f"initial_lots for {i} must sum to initial_inventory exactly")

    road = None
    if road_mode:
        from backend.road_network import build_road_transport
        road = build_road_transport(m, data, weights, l, Lot)
        trip, routes = road.trip, road.routes
        # Existing lots define expiry by first unusable deadline; purchased lots
        # retain their actual conservative slot expiry for FEFO ordering.
        for b in lots:
            if b.expiry is not None:
                b.expiry_slot = road.graph.deadlines.get(b.expiry,
                    road.graph.deadlines[end] + (b.expiry-end)*road.graph.week_slots)
        lots.extend(road.lots)
    else:
        trip = {(r, w): m.var(("trips", r, w), routes[r]["max_trips"][w], True)
                for r in routes for w in weeks}
        # Quantity purchased in origin week o; supplier dispatches when procurement completes.
        for i in items:
            for o in weeks:
                d = o + procurement[i]
                if d > end:
                    continue
                for r, route in routes.items():
                    a = d + route['lag']
                    expiry = None if shelf[i] is None else d + shelf[i]
                    if a > end or i not in route['allowed_items'] or (expiry is not None and a >= expiry):
                        continue
                    q = data.weekly_supply[i][o]
                    k = m.var(("order", i, o, r), q, i in base.DISCRETE_ITEMS)
                    lots.append(Lot(f"order:{i}:{o}:{r}", i, a, expiry, q, k, o, d, r))
        for i in items:
            for w in weeks:
                m.constraint({b.order: 1 for b in lots if b.item == i and b.order_week == w},
                             upper=data.weekly_supply[i][w])
        for r, route in routes.items():
            truck = fleet[route['vehicle_type']]
            for w in weeks:
                departing = [b for b in lots if b.route == r and b.dispatch_week == w]
                for unit, cap, field in ((weights, truck['payload_kg'], 'max_weight_kg'),
                                         (data.item_volume_m3, truck['volume_m3'], 'max_volume_m3')):
                    terms = {b.order: unit[b.item] for b in departing}
                    m.constraint(terms, upper=route[field][w])
                    m.constraint(terms | {trip[r, w]: -cap}, upper=0)
        for vehicle, truck in fleet.items():
            for w in weeks:
                m.constraint({trip[r, d]: 1 for r, route in routes.items()
                              if route['vehicle_type'] == vehicle for d in weeks
                              if d <= w < d + route['busy']}, upper=truck['available'][w])
        for corridor, cap in corridors.items():
            for w in weeks:
                m.constraint({trip[r, d]: 1 for r in routes if routes[r]['corridor'] == corridor
                              for d in weeks if d + routes[r]['corridor_lag'] == w}, upper=cap[w])
    if road_mode:
        # Supplier allocation is shared by every truck/path/departure alternative.
        for i in items:
            for w in weeks:
                m.constraint({b.order: 1 for b in lots if b.item == i and b.order_week == w},
                             upper=data.weekly_supply[i][w])

    use, inv, expired = {}, {}, { (i, w): {} for i in items for w in weeks }
    for b in lots:
        for w in weeks:
            if w < b.arrival:
                continue
            if b.expiry is not None and w >= b.expiry:
                if w == max(b.arrival, b.expiry):
                    if w == b.arrival:
                        # Prepaid pipeline or opening lots already expired on receipt.
                        expired[b.item, w][("fixed", b.id)] = b.quantity
                    elif (b.id, w-1) in inv:
                        expired[b.item, w][inv[b.id, w-1]] = 1
                continue
            use[b.id, w] = m.var(("use", b.id, w), b.quantity, b.item in base.DISCRETE_ITEMS)
            inv[b.id, w] = m.var(("stock", b.id, w), b.quantity, b.item in base.DISCRETE_ITEMS)
            terms = {use[b.id, w]: 1, inv[b.id, w]: 1}
            rhs = 0
            if w == b.arrival:
                if b.order is None:
                    rhs = b.quantity
                else:
                    terms[b.order] = -1
            else:
                terms[inv[b.id, w-1]] = -1
            m.constraint(terms, rhs, rhs)
    # Hard FEFO: a later-expiring lot may be consumed only after ALL earlier
    # usable lots of the same item have been exhausted. Equal expiry dates tie.
    fefo_terms = 0
    for i in items:
        for w in weeks:
            active = [b for b in lots if b.item == i and (b.id, w) in use]
            for later in active:
                def expiry_rank(b):
                    return (b.expiry_slot if road_mode else b.expiry) if b.expiry is not None else math.inf
                earlier = [b for b in active if expiry_rank(b) < expiry_rank(later)]
                if not earlier:
                    continue
                if road_mode:
                    from backend.road_network import MAX_FEFO_TERMS
                    fefo_terms += len(earlier)+1
                    if fefo_terms > MAX_FEFO_TERMS:
                        raise base.InputValidationError('Road FEFO model exceeds 1000000 terms; simplify graph/grid')
                switch = m.var(("FEFO", later.id, w), 1, True)
                m.constraint({use[later.id, w]: 1, switch: -later.quantity}, upper=0)
                bound = sum(b.quantity for b in earlier)
                m.constraint({inv[b.id, w]: 1 for b in earlier} | {switch: bound}, upper=bound)

    unmet, quarantine, disposal = {}, {}, {}
    cost = {b.order: data.unit_cost[b.item] for b in lots if b.order is not None}
    cost.update({k: routes[r]['trip_cost'] for (r, w), k in trip.items()})
    max_unmet = m.var("max_unmet_rate", 1)
    weighted = {}
    for i in items:
        bound = sum(b.quantity for b in lots if b.item == i)
        for w in weeks:
            key = (site, i, w)
            d = demands.demand[key]
            u = unmet[i, w] = m.var(("unmet", i, w), d, i in base.DISCRETE_ITEMS)
            m.constraint({use[b.id, w]: 1 for b in lots if b.item == i and (b.id, w) in use} | {u: 1}, d, d)
            if d:
                m.constraint({u: 1, max_unmet: -d}, upper=0)
                weighted[u] = data.item_weights[i] / demands.item_total_demand[i]
            quarantine[i, w] = m.var(("quarantine", i, w), bound, i in base.DISCRETE_ITEMS)
            disposal[i, w] = m.var(("disposal", i, w), disposal_cap[i][w], i in base.DISCRETE_ITEMS)
            terms = {quarantine[i, w]: 1, disposal[i, w]: 1}
            if w > 1:
                terms[quarantine[i, w-1]] = -1
            fixed = 0
            for k, v in expired[i, w].items():
                if isinstance(k, tuple):
                    fixed += v
                else:
                    terms[k] = -v
            m.constraint(terms, fixed, fixed)
            cost[disposal[i, w]] = disposal_cost[i]
    # Dispose/segregate expired units first, receive all deliveries, then serve.
    # Retained quarantine occupies the same total warehouse capacity.
    for w in weeks:
        terms, fixed = {}, 0
        for i in items:
            terms[quarantine[i, w]] = data.item_volume_m3[i]
        for b in lots:
            if (b.id, w) not in use:
                continue
            v = data.item_volume_m3[b.item]
            if w == b.arrival:
                if b.order is None:
                    fixed += b.quantity * v
                else:
                    terms[b.order] = v
            else:
                terms[inv[b.id, w-1]] = v
        m.constraint(terms, upper=data.warehouse_capacity_m3[site] - fixed)
    m.constraint(cost, upper=data.total_budget)
    stages = []
    if data.priority == 'fairness':
        stages.append(('stage_1_max_unmet_rate', {max_unmet: 1}))
    stages += [('stage_2_weighted_unmet_objective', weighted), ('stage_3_total_cost', cost)]
    # Final tie-break reduces expiry and retained quarantine without trading away
    # fulfillment or increasing the already minimized total cost.
    waste = {}
    for i in items:
        scale = 1 / max(1, demands.item_total_demand[i])
        waste[quarantine[i, end]] = scale
        for w in weeks:
            for k, v in expired[i, w].items():
                if isinstance(k, int):
                    waste[k] = waste.get(k, 0) + scale * v
    stages.append(('stage_4_waste_tiebreak', waste))
    stages.append(('stage_5_trip_tiebreak', {k: 1 for k in trip.values()}))
    if road_mode:
        stages += road.tie_breaks()
    x, objectives = m.solve(stages, data.solver_config)
    val = lambda k: max(0., float(x[k]))
    values = {g: {} for g in ('shipment', 'served', 'unmet', 'inventory')}
    detail = []
    for b in lots:
        q = b.quantity if b.order is None else val(b.order)
        for w in weeks:
            served = val(use[b.id, w]) if (b.id, w) in use else 0.
            remaining = val(inv[b.id, w]) if (b.id, w) in inv else 0.
            if q > 1e-6 and w >= b.arrival:
                expired_now = 0.
                if b.expiry is not None and w == max(b.arrival, b.expiry):
                    expired_now = q if w == b.arrival else val(inv[b.id, w-1])
                detail.append(dict(lot_id=b.id, item=b.item, week=w, arrival_week=b.arrival,
                                   expiry_week=b.expiry, quantity=q, served=served,
                                   expired_quantity=expired_now, ending_usable_inventory=remaining))
    initial_ids = {v['id'] for v in l['initial_lots']}
    for i in items:
        for w in weeks:
            key = (site, i, w)
            active = [b for b in lots if b.item == i]
            values['shipment'][key] = sum(b.quantity if b.order is None else val(b.order)
                                          for b in active if b.arrival == w and b.id not in initial_ids)
            values['served'][key] = sum(val(use[b.id, w]) for b in active if (b.id, w) in use)
            values['unmet'][key] = val(unmet[i, w])
            values['inventory'][key] = sum(val(inv[b.id, w]) for b in active if (b.id, w) in inv)
    result = base._format_result(values, data, demands, objectives)
    procurement_cost = sum(val(b.order) * data.unit_cost[b.item] for b in lots if b.order is not None)
    transport_cost = sum(val(k) * routes[r]['trip_cost'] for (r, w), k in trip.items())
    waste_cost = sum(val(k) * disposal_cost[i] for (i, w), k in disposal.items())
    total_cost = procurement_cost + transport_cost + waste_cost
    if total_cost > data.total_budget + 1e-5:
        raise base.OptimizationError("Total budget failed after formatting", stage="verification")
    result['summary'].update(total_procurement_cost=procurement_cost, transport_cost=transport_cost,
                             disposal_cost=waste_cost, total_cost=total_cost,
                             budget_remaining=max(0., data.total_budget-total_cost),
                             message=f"{site}: 운송·리드타임·기한·폐기를 반영한 {end}주 계획. "
                                     f"총비용 {total_cost:,.2f}, 수요 충족률 "
                                     f"{result['summary']['overall_weighted_fulfillment_rate']:.1%}.")
    for row in result['plan']:
        i, w = row['item'], row['week']
        fixed_expired = sum(v for k, v in expired[i, w].items() if isinstance(k, tuple))
        expired_q = fixed_expired + sum(val(k)*v for k, v in expired[i, w].items() if isinstance(k, int))
        row.update(recommended_order=sum(val(b.order) for b in lots if b.item == i and b.order_week == w),
                   dispatched=sum(val(b.order) for b in lots if b.item == i and b.dispatch_week == w),
                   expired_quantity=expired_q, disposed_quantity=val(disposal[i, w]),
                   quarantined_inventory=val(quarantine[i, w]))
    # Replace legacy peak summaries (they cannot account for expired stock).
    result['warehouse_summary'] = []
    for w in weeks:
        peak = sum(val(quarantine[i, w])*data.item_volume_m3[i] for i in items)
        for b in lots:
            if (b.id, w) in use:
                q = (b.quantity if b.order is None else val(b.order)) if w == b.arrival else val(inv[b.id, w-1])
                peak += q * data.item_volume_m3[b.item]
        result['warehouse_summary'].append(dict(site=site, week=w, peak_inventory_volume_m3=peak,
                                                warehouse_capacity_m3=data.warehouse_capacity_m3[site],
                                                warehouse_utilization_rate=peak/data.warehouse_capacity_m3[site]))
    result['transport_plan'] = []
    if not road_mode:
        for (r, w), k in trip.items():
            cargo = {i: sum(val(b.order) for b in lots if b.item == i and b.route == r and b.dispatch_week == w) for i in items}
            result['transport_plan'].append(dict(route=r, corridor=routes[r]['corridor'], week=w,
                                                 crossing_week=w+routes[r]['corridor_lag'] if routes[r]['corridor'] else None,
                                                 arrival_week=w+routes[r]['lag'], vehicle_release_week=w+routes[r]['busy'], trips=round(val(k)),
                                                 vehicle_type=routes[r]['vehicle_type'], cargo=cargo,
                                                 weight_kg=sum(cargo[i]*weights[i] for i in items),
                                                 volume_m3=sum(cargo[i]*data.item_volume_m3[i] for i in items)))
    result['order_plan'] = [dict(item=b.item, order_week=b.order_week, dispatch_week=b.dispatch_week,
                                 arrival_week=b.arrival, expiry_week=b.expiry, route=b.route,
                                 quantity=val(b.order)) for b in lots if b.order is not None and val(b.order)>1e-6]
    result['lot_plan'] = detail
    result['model_info'].update(logistics_enabled=True, sources=SOURCES,
                               source_checked_on='2026-10-02', stage_objectives=objectives,
                               solver_stages=m.stage_reports,
                               variables=len(m.names), constraints=len(m.rows),
                               parameter_provenance='Caller-supplied operational values; not verified by official guidance',
                               optimization_method='Lexicographic: fairness (optional), normalized unmet, total cost, waste tie-break',
                               time_convention='ceil(procurement_days/7), ceil(transit_days/7); shelf life floor(days/7) from dispatch. expiry_week is first unusable week.',
                               warehouse_capacity_basis='After expiry segregation/disposal, before distribution; retained quarantine included.',
                               limitations=['Single selected site; pre-approved direct routes, no road-graph routing',
                                            'Conservative weekly buckets, at most one departure per available vehicle per week',
                                            'Supplier dispatch immediately after procurement; no upstream inventory',
                                            'Pipeline is prepaid and transport-booked; enter fleet availability net of prior bookings',
                                            'Driver-hour, axle-load, customs, packing and temperature compliance require pre-approved route/vehicle inputs',
                                            'No multi-site resource sharing or stochastic delay optimization',
                                            'Shelf life requires actual label/lot data; no universal item defaults'])
    if road_mode:
        road.format_and_verify(result, x, lots, weights, data)
    return result


def example_logistics(selected_site='Medyka'):
    """Explicitly synthetic fixture, never an operational default."""
    weeks = range(1, 5)
    return {
        'item_weight_kg': dict(water=1.02, food=0.6, hygiene_kit=0.5, blanket=1.5),
        'procurement_lead_days': {i: 0 for i in base.ITEMS},
        'shelf_life_days': dict(water=365, food=180, hygiene_kit=None, blanket=None),
        'initial_lots': [dict(id='opening:'+i, item=i, quantity=q, expiry_week=20 if i in ('water','food') else None)
                         for i, q in base.example_inputs(selected_site)[1]['initial_inventory'][selected_site].items()],
        'pipeline_lots': [],
        'vehicles': {'truck': {'payload_kg': 12000, 'volume_m3': 40, 'available': {w: 3 for w in weeks}}},
        'routes': [dict(id='domestic-direct', destination=selected_site, vehicle_type='truck',
                        transit_days=0, round_trip_days=1, trip_cost=250, max_trips={w:3 for w in weeks},
                        max_weight_kg={w:36000 for w in weeks}, max_volume_m3={w:120 for w in weeks},
                        corridor='local-access', corridor_delay_days=0, allowed_items=list(base.ITEMS))],
        'corridors': {'local-access': {w:3 for w in weeks}},
        'disposal_cost': {i:0.1 for i in base.ITEMS},
        'disposal_capacity': {i:{w:100000 for w in weeks} for i in base.ITEMS},
    }

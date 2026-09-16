"""Relief-supply procurement and allocation optimization engine.

This module intentionally contains no UI, database, or network code.  Its public
API is :func:`optimize_relief_plan`, which accepts plain Python mappings and
returns JSON-serializable dictionaries/lists.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
import math
from numbers import Real
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, OptimizeResult, milp
from scipy.sparse import csc_array


SITES: tuple[str, ...] = ("Medyka", "Korczowa", "Dorohusk")
ITEMS: tuple[str, ...] = ("water", "food", "hygiene_kit", "blanket")
DISCRETE_ITEMS: frozenset[str] = frozenset(
    {"food", "hygiene_kit", "blanket"}
)
ITEM_UNITS: dict[str, str] = {
    "water": "L",
    "food": "daily ration",
    "hygiene_kit": "item",
    "blanket": "item",
}
DEFAULT_ITEM_WEIGHTS: dict[str, float] = {item: 1.0 for item in ITEMS}

_USER_INPUT_FIELDS: tuple[str, ...] = (
    "selected_site",
    "utilization_rate",
    "stay_days",
    "initial_inventory",
    "weekly_supply",
    "unit_cost",
    "total_budget",
    "warehouse_capacity_m3",
)
_ALLOWED_UTILIZATION_RATES: tuple[float, ...] = (0.05, 0.10, 0.20)
_ALLOWED_STAY_DAYS: tuple[int, ...] = (1, 2, 3, 4)
_NUMERICAL_CHECK_TOLERANCE = 1e-5


class InputValidationError(ValueError):
    """Raised before optimization when an input is missing or invalid."""


class OptimizationError(RuntimeError):
    """Raised when the solver cannot provide a proven, usable solution."""

    def __init__(
        self,
        message: str,
        *,
        status: int | str | None = None,
        solver_message: str | None = None,
        stage: str | None = None,
        inputs_to_check: Sequence[str] = (),
    ) -> None:
        self.status = status
        self.solver_message = solver_message
        self.stage = stage
        self.inputs_to_check = tuple(inputs_to_check)

        details: list[str] = []
        if stage is not None:
            details.append(f"stage={stage}")
        if status is not None:
            details.append(f"status={status}")
        if solver_message:
            details.append(f"solver_message={solver_message}")
        if self.inputs_to_check:
            details.append("확인할 입력=" + ", ".join(self.inputs_to_check))
        suffix = f" ({'; '.join(details)})" if details else ""
        super().__init__(message + suffix)


@dataclass(frozen=True)
class SolverConfig:
    """Configuration shared by all three lexicographic MILP stages."""

    time_limit_seconds: float = 30.0
    mip_rel_gap: float = 1e-6
    objective_tolerance: float = 1e-7


@dataclass(frozen=True)
class _NormalizedInput:
    sites: tuple[str, ...]
    selected_site: str
    weeks: tuple[int, ...]
    forecast: dict[str, dict[int, float]]
    utilization_rate: float
    stay_days: int
    initial_inventory: dict[str, dict[str, float]]
    weekly_supply: dict[str, dict[int, float]]
    unit_cost: dict[str, float]
    total_budget: float
    warehouse_capacity_m3: dict[str, float]
    item_volume_m3: dict[str, float]
    item_weights: dict[str, float]
    solver_config: SolverConfig


@dataclass(frozen=True)
class _DemandData:
    supported_people: dict[tuple[str, int], int]
    demand: dict[tuple[str, str, int], float]
    item_total_demand: dict[str, float]


@dataclass(frozen=True)
class _VariableIndex:
    shipment: dict[tuple[str, str, int], int]
    served: dict[tuple[str, str, int], int]
    unmet: dict[tuple[str, str, int], int]
    inventory: dict[tuple[str, str, int], int]
    max_unmet_rate: int
    size: int


@dataclass(frozen=True)
class _OptimizationModel:
    index: _VariableIndex
    bounds: Bounds
    integrality: np.ndarray
    base_constraint: LinearConstraint
    stage_one_objective: np.ndarray
    stage_two_objective: np.ndarray
    stage_three_objective: np.ndarray


def _require_mapping(value: Any, path: str) -> Mapping[Any, Any]:
    if not isinstance(value, Mapping):
        raise InputValidationError(f"{path} must be a mapping/dict.")
    return value


def _check_required_keys(
    mapping: Mapping[Any, Any], required: Sequence[str], path: str
) -> None:
    missing = [key for key in required if key not in mapping]
    if missing:
        raise InputValidationError(f"{path} is missing required keys: {missing}.")


def _check_exact_keys(
    mapping: Mapping[Any, Any], expected: Sequence[str], path: str
) -> None:
    expected_set = set(expected)
    actual_set = set(mapping)
    missing = sorted(expected_set - actual_set)
    unexpected = sorted(actual_set - expected_set, key=str)
    if missing or unexpected:
        parts: list[str] = []
        if missing:
            parts.append(f"missing={missing}")
        if unexpected:
            parts.append(f"unexpected={unexpected}")
        raise InputValidationError(f"{path} has invalid keys ({', '.join(parts)}).")


def _check_selected_forecast_keys(
    mapping: Mapping[Any, Any], selected_site: str, path: str
) -> None:
    """Accept a selected-site forecast or the ML team's complete forecast."""

    actual = set(mapping)
    allowed_shapes = ({selected_site}, set(SITES))
    if actual not in allowed_shapes:
        raise InputValidationError(
            f"{path} must contain either only the selected site {selected_site!r} "
            f"or all three ML sites {list(SITES)}; received "
            f"{sorted(actual, key=str)}."
        )


def _finite_number(
    value: Any,
    path: str,
    *,
    minimum: float | None = None,
    strictly_positive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise InputValidationError(f"{path} must be a finite numeric value.")
    number = float(value)
    if not math.isfinite(number):
        raise InputValidationError(f"{path} must be finite; NaN/Infinity is invalid.")
    if strictly_positive and number <= 0:
        raise InputValidationError(f"{path} must be greater than 0.")
    if minimum is not None and number < minimum:
        raise InputValidationError(f"{path} must be at least {minimum}.")
    return number


def _integer_value(value: Any, path: str, *, minimum: int = 0) -> int:
    number = _finite_number(value, path)
    if not number.is_integer():
        raise InputValidationError(f"{path} must be an integer.")
    integer = int(number)
    if integer < minimum:
        raise InputValidationError(f"{path} must be at least {minimum}.")
    return integer


def _normalize_week_mapping(
    value: Any,
    path: str,
    *,
    minimum: float = 0.0,
) -> dict[int, float]:
    mapping = _require_mapping(value, path)
    normalized: dict[int, float] = {}
    for raw_week, raw_value in mapping.items():
        if isinstance(raw_week, bool):
            raise InputValidationError(f"{path} contains invalid week key {raw_week!r}.")
        if isinstance(raw_week, int):
            week = raw_week
        elif isinstance(raw_week, str) and raw_week.isdigit():
            week = int(raw_week)
        else:
            raise InputValidationError(
                f"{path} week keys must be integers 1..4 (or numeric JSON keys)."
            )
        if week in normalized:
            raise InputValidationError(
                f"{path} contains duplicate normalized week key {week}."
            )
        if week not in (1, 2, 3, 4):
            raise InputValidationError(f"{path} contains week {week}; only 1..4 are valid.")
        normalized[week] = _finite_number(
            raw_value, f"{path}[{week}]", minimum=minimum
        )
    return normalized


def _normalize_solver_config(value: SolverConfig | Mapping[str, Any] | None) -> SolverConfig:
    if value is None:
        config = SolverConfig()
    elif isinstance(value, SolverConfig):
        config = value
    elif isinstance(value, Mapping):
        allowed = {"time_limit_seconds", "mip_rel_gap", "objective_tolerance"}
        unexpected = set(value) - allowed
        if unexpected:
            raise InputValidationError(
                f"solver_config has unexpected keys: {sorted(unexpected)}."
            )
        try:
            config = SolverConfig(**dict(value))
        except TypeError as exc:
            raise InputValidationError(f"Invalid solver_config: {exc}") from exc
    else:
        raise InputValidationError(
            "solver_config must be None, SolverConfig, or a compatible mapping."
        )

    time_limit = _finite_number(
        config.time_limit_seconds,
        "solver_config.time_limit_seconds",
        strictly_positive=True,
    )
    gap = _finite_number(config.mip_rel_gap, "solver_config.mip_rel_gap", minimum=0.0)
    tolerance = _finite_number(
        config.objective_tolerance,
        "solver_config.objective_tolerance",
        strictly_positive=True,
    )
    return SolverConfig(time_limit, gap, tolerance)


def _normalize_and_validate(
    ml_forecast: Mapping[str, Mapping[int, Real]],
    user_input: Mapping[str, Any],
    item_volume_m3: Mapping[str, Real],
    item_weights: Mapping[str, Real] | None,
    solver_config: SolverConfig | Mapping[str, Any] | None,
) -> _NormalizedInput:
    user = _require_mapping(user_input, "user_input")
    _check_required_keys(user, _USER_INPUT_FIELDS, "user_input")

    selected_site_raw = user["selected_site"]
    if not isinstance(selected_site_raw, str) or selected_site_raw not in SITES:
        raise InputValidationError(
            "user_input.selected_site must be exactly one of "
            f"{', '.join(SITES)}."
        )
    selected_site = selected_site_raw
    active_sites = (selected_site,)

    forecast_raw = _require_mapping(ml_forecast, "ml_forecast")
    _check_selected_forecast_keys(forecast_raw, selected_site, "ml_forecast")

    forecast: dict[str, dict[int, float]] = {}
    for site in active_sites:
        forecast[site] = _normalize_week_mapping(
            forecast_raw[site], f"ml_forecast[{site!r}]"
        )

    weeks = tuple(sorted(forecast[active_sites[0]]))
    if not 1 <= len(weeks) <= 4:
        raise InputValidationError("Planning horizon must contain between 1 and 4 weeks.")
    expected_weeks = tuple(range(1, len(weeks) + 1))
    if weeks != expected_weeks:
        raise InputValidationError(
            f"Planning weeks must be consecutive from week 1; received {list(weeks)}."
        )
    for site in active_sites[1:]:
        site_weeks = tuple(sorted(forecast[site]))
        if site_weeks != weeks:
            raise InputValidationError(
                f"ml_forecast[{site!r}] weeks {list(site_weeks)} do not match "
                f"planning weeks {list(weeks)}."
            )

    utilization_input = _finite_number(
        user["utilization_rate"], "user_input.utilization_rate", minimum=0.0
    )
    utilization_matches = [
        candidate
        for candidate in _ALLOWED_UTILIZATION_RATES
        if math.isclose(utilization_input, candidate, rel_tol=0.0, abs_tol=1e-12)
    ]
    if not utilization_matches:
        raise InputValidationError(
            "user_input.utilization_rate must be exactly one of 0.05, 0.10, 0.20."
        )
    utilization_rate = utilization_matches[0]

    stay_days = _integer_value(user["stay_days"], "user_input.stay_days", minimum=1)
    if stay_days not in _ALLOWED_STAY_DAYS:
        raise InputValidationError("user_input.stay_days must be one of 1, 2, 3, 4.")

    initial_raw = _require_mapping(user["initial_inventory"], "initial_inventory")
    _check_exact_keys(initial_raw, active_sites, "initial_inventory")
    initial_inventory: dict[str, dict[str, float]] = {}
    for site in active_sites:
        site_inventory = _require_mapping(
            initial_raw[site], f"initial_inventory[{site!r}]"
        )
        _check_exact_keys(site_inventory, ITEMS, f"initial_inventory[{site!r}]")
        initial_inventory[site] = {}
        for item in ITEMS:
            path = f"initial_inventory[{site!r}][{item!r}]"
            amount = _finite_number(site_inventory[item], path, minimum=0.0)
            if item in DISCRETE_ITEMS and not amount.is_integer():
                raise InputValidationError(
                    f"{path} must be an integer because {item} is a discrete item."
                )
            initial_inventory[site][item] = amount

    supply_raw = _require_mapping(user["weekly_supply"], "weekly_supply")
    _check_exact_keys(supply_raw, ITEMS, "weekly_supply")
    weekly_supply: dict[str, dict[int, float]] = {}
    for item in ITEMS:
        item_supply = _normalize_week_mapping(
            supply_raw[item], f"weekly_supply[{item!r}]"
        )
        supply_weeks = tuple(sorted(item_supply))
        if supply_weeks != weeks:
            raise InputValidationError(
                f"weekly_supply[{item!r}] weeks {list(supply_weeks)} do not match "
                f"planning weeks {list(weeks)}."
            )
        if item in DISCRETE_ITEMS:
            for week, amount in item_supply.items():
                if not amount.is_integer():
                    raise InputValidationError(
                        f"weekly_supply[{item!r}][{week}] must be an integer "
                        f"because {item} is a discrete item."
                    )
        weekly_supply[item] = item_supply

    cost_raw = _require_mapping(user["unit_cost"], "unit_cost")
    _check_exact_keys(cost_raw, ITEMS, "unit_cost")
    unit_cost = {
        item: _finite_number(
            cost_raw[item], f"unit_cost[{item!r}]", strictly_positive=True
        )
        for item in ITEMS
    }

    total_budget = _finite_number(
        user["total_budget"], "user_input.total_budget", minimum=0.0
    )

    capacity_raw = _require_mapping(
        user["warehouse_capacity_m3"], "warehouse_capacity_m3"
    )
    _check_exact_keys(capacity_raw, active_sites, "warehouse_capacity_m3")
    warehouse_capacity_m3 = {
        site: _finite_number(
            capacity_raw[site],
            f"warehouse_capacity_m3[{site!r}]",
            strictly_positive=True,
        )
        for site in active_sites
    }

    volume_raw = _require_mapping(item_volume_m3, "item_volume_m3")
    _check_exact_keys(volume_raw, ITEMS, "item_volume_m3")
    normalized_volumes = {
        item: _finite_number(
            volume_raw[item], f"item_volume_m3[{item!r}]", strictly_positive=True
        )
        for item in ITEMS
    }

    weights_raw: Mapping[str, Real]
    if item_weights is None:
        weights_raw = DEFAULT_ITEM_WEIGHTS
    else:
        weights_raw = _require_mapping(item_weights, "item_weights")
        _check_exact_keys(weights_raw, ITEMS, "item_weights")
    normalized_weights = {
        item: _finite_number(
            weights_raw[item], f"item_weights[{item!r}]", strictly_positive=True
        )
        for item in ITEMS
    }

    normalized_config = _normalize_solver_config(solver_config)

    for site in active_sites:
        initial_volume = sum(
            initial_inventory[site][item] * normalized_volumes[item] for item in ITEMS
        )
        capacity = warehouse_capacity_m3[site]
        capacity_comparison_tolerance = 1e-9 * max(1.0, capacity)
        if initial_volume > capacity + capacity_comparison_tolerance:
            raise InputValidationError(
                f"Initial inventory at {site} occupies {initial_volume:.6f} m^3, "
                f"which exceeds warehouse capacity {capacity:.6f} m^3. "
                "Reduce initial_inventory or correct item_volume_m3/capacity before solving."
            )

    return _NormalizedInput(
        sites=active_sites,
        selected_site=selected_site,
        weeks=weeks,
        forecast=forecast,
        utilization_rate=utilization_rate,
        stay_days=stay_days,
        initial_inventory=initial_inventory,
        weekly_supply=weekly_supply,
        unit_cost=unit_cost,
        total_budget=total_budget,
        warehouse_capacity_m3=warehouse_capacity_m3,
        item_volume_m3=normalized_volumes,
        item_weights=normalized_weights,
        solver_config=normalized_config,
    )


def _calculate_demands(data: _NormalizedInput) -> _DemandData:
    supported_people: dict[tuple[str, int], int] = {}
    demand: dict[tuple[str, str, int], float] = {}

    for site in data.sites:
        for week in data.weeks:
            # Decimal(str(...)) avoids a binary-float product just above an exact
            # integer boundary (for example, 20 * 0.05) being incorrectly ceiled
            # to one extra person.
            supported_decimal = (
                Decimal(str(data.forecast[site][week]))
                * Decimal(str(data.utilization_rate))
            )
            supported = int(supported_decimal.to_integral_value(rounding=ROUND_CEILING))
            supported_people[(site, week)] = supported
            calculated = {
                "water": supported * data.stay_days * 15,
                "food": supported * data.stay_days,
                "hygiene_kit": supported,
                "blanket": supported,
            }
            for item, exact_amount in calculated.items():
                try:
                    amount = float(exact_amount)
                except OverflowError as exc:
                    raise InputValidationError(
                        f"Calculated demand for {(site, item, week)} is too large "
                        "for the numerical solver. Check ml_forecast."
                    ) from exc
                if not math.isfinite(amount):
                    raise InputValidationError(
                        f"Calculated demand for {(site, item, week)} is not finite. "
                        "Check ml_forecast."
                    )
                demand[(site, item, week)] = amount

    item_total_demand = {
        item: sum(
            demand[(site, item, week)] for site in data.sites for week in data.weeks
        )
        for item in ITEMS
    }
    return _DemandData(supported_people, demand, item_total_demand)


def _make_variable_index(
    sites: Sequence[str], weeks: Sequence[int]
) -> _VariableIndex:
    keys = [(site, item, week) for site in sites for item in ITEMS for week in weeks]
    next_index = 0
    groups: list[dict[tuple[str, str, int], int]] = []
    for _ in range(4):
        group = {key: next_index + offset for offset, key in enumerate(keys)}
        groups.append(group)
        next_index += len(keys)
    z_index = next_index
    return _VariableIndex(
        shipment=groups[0],
        served=groups[1],
        unmet=groups[2],
        inventory=groups[3],
        max_unmet_rate=z_index,
        size=z_index + 1,
    )


def _build_milp_model(
    data: _NormalizedInput, demands: _DemandData
) -> _OptimizationModel:
    index = _make_variable_index(data.sites, data.weeks)

    lower_bounds = np.zeros(index.size, dtype=float)
    upper_bounds = np.full(index.size, np.inf, dtype=float)
    upper_bounds[index.max_unmet_rate] = 1.0
    integrality = np.zeros(index.size, dtype=np.uint8)

    for site in data.sites:
        for item in ITEMS:
            for week in data.weeks:
                key = (site, item, week)
                demand = demands.demand[key]
                upper_bounds[index.shipment[key]] = data.weekly_supply[item][week]
                upper_bounds[index.served[key]] = demand
                upper_bounds[index.unmet[key]] = demand
                upper_bounds[index.inventory[key]] = (
                    data.warehouse_capacity_m3[site] / data.item_volume_m3[item]
                )
                if item in DISCRETE_ITEMS:
                    integrality[index.shipment[key]] = 1
                    integrality[index.served[key]] = 1
                    integrality[index.unmet[key]] = 1
                    integrality[index.inventory[key]] = 1

    row_indices: list[int] = []
    column_indices: list[int] = []
    coefficients: list[float] = []
    constraint_lower: list[float] = []
    constraint_upper: list[float] = []

    def add_constraint(
        terms: Mapping[int, float], lower: float = -np.inf, upper: float = np.inf
    ) -> None:
        row = len(constraint_lower)
        for column, coefficient in terms.items():
            if coefficient != 0:
                row_indices.append(row)
                column_indices.append(column)
                coefficients.append(float(coefficient))
        constraint_lower.append(float(lower))
        constraint_upper.append(float(upper))

    # Demand identity: Y + U = D.
    for site in data.sites:
        for item in ITEMS:
            for week in data.weeks:
                key = (site, item, week)
                add_constraint(
                    {index.served[key]: 1.0, index.unmet[key]: 1.0},
                    demands.demand[key],
                    demands.demand[key],
                )

    # Inventory flow.
    for site in data.sites:
        for item in ITEMS:
            for week_position, week in enumerate(data.weeks):
                key = (site, item, week)
                terms = {
                    index.inventory[key]: 1.0,
                    index.shipment[key]: -1.0,
                    index.served[key]: 1.0,
                }
                if week_position == 0:
                    rhs = data.initial_inventory[site][item]
                else:
                    previous_key = (site, item, data.weeks[week_position - 1])
                    terms[index.inventory[previous_key]] = -1.0
                    rhs = 0.0
                add_constraint(terms, rhs, rhs)

    # The weekly supply is the amount allocated to this selected site's run.
    for item in ITEMS:
        for week in data.weeks:
            add_constraint(
                {
                    index.shipment[(site, item, week)]: 1.0
                    for site in data.sites
                },
                upper=data.weekly_supply[item][week],
            )

    # Total procurement budget.
    add_constraint(
        {
            index.shipment[(site, item, week)]: data.unit_cost[item]
            for site in data.sites
            for item in ITEMS
            for week in data.weeks
        },
        upper=data.total_budget,
    )

    # Peak warehouse volume immediately after delivery and before distribution.
    for site in data.sites:
        for week_position, week in enumerate(data.weeks):
            terms = {
                index.shipment[(site, item, week)]: data.item_volume_m3[item]
                for item in ITEMS
            }
            if week_position == 0:
                initial_volume = sum(
                    data.initial_inventory[site][item] * data.item_volume_m3[item]
                    for item in ITEMS
                )
                # Validation rejects meaningful over-capacity inputs.  Clamp only
                # sub-nanometric floating arithmetic noise to zero here so it
                # cannot turn an otherwise valid model infeasible.
                upper = max(0.0, data.warehouse_capacity_m3[site] - initial_volume)
            else:
                previous_week = data.weeks[week_position - 1]
                for item in ITEMS:
                    terms[index.inventory[(site, item, previous_week)]] = (
                        data.item_volume_m3[item]
                    )
                upper = data.warehouse_capacity_m3[site]
            add_constraint(terms, upper=upper)

    # Cell-level fairness for all cells with positive demand: U <= z * D.
    for site in data.sites:
        for item in ITEMS:
            for week in data.weeks:
                key = (site, item, week)
                demand = demands.demand[key]
                if demand > 0:
                    add_constraint(
                        {
                            index.unmet[key]: 1.0,
                            index.max_unmet_rate: -demand,
                        },
                        upper=0.0,
                    )

    matrix = csc_array(
        (
            np.asarray(coefficients, dtype=float),
            (
                np.asarray(row_indices, dtype=np.int32),
                np.asarray(column_indices, dtype=np.int32),
            ),
        ),
        shape=(len(constraint_lower), index.size),
    )
    base_constraint = LinearConstraint(
        matrix,
        np.asarray(constraint_lower, dtype=float),
        np.asarray(constraint_upper, dtype=float),
    )

    stage_one = np.zeros(index.size, dtype=float)
    stage_one[index.max_unmet_rate] = 1.0

    stage_two = np.zeros(index.size, dtype=float)
    for item in ITEMS:
        total_demand = demands.item_total_demand[item]
        if total_demand <= 0:
            continue
        coefficient = data.item_weights[item] / total_demand
        for site in data.sites:
            for week in data.weeks:
                stage_two[index.unmet[(site, item, week)]] = coefficient

    stage_three = np.zeros(index.size, dtype=float)
    for site in data.sites:
        for item in ITEMS:
            for week in data.weeks:
                stage_three[index.shipment[(site, item, week)]] = data.unit_cost[item]

    return _OptimizationModel(
        index=index,
        bounds=Bounds(lower_bounds, upper_bounds),
        integrality=integrality,
        base_constraint=base_constraint,
        stage_one_objective=stage_one,
        stage_two_objective=stage_two,
        stage_three_objective=stage_three,
    )


def _objective_constraint(
    objective: np.ndarray, upper: float
) -> LinearConstraint:
    return LinearConstraint(csc_array(objective.reshape(1, -1)), -np.inf, upper)


def _solve_stage(
    objective: np.ndarray,
    model: _OptimizationModel,
    config: SolverConfig,
    stage_name: str,
    extra_constraints: Sequence[LinearConstraint] = (),
) -> OptimizeResult:
    constraints = [model.base_constraint, *extra_constraints]
    try:
        result = milp(
            c=objective,
            integrality=model.integrality,
            bounds=model.bounds,
            constraints=constraints,
            options={
                "time_limit": config.time_limit_seconds,
                "mip_rel_gap": config.mip_rel_gap,
                "presolve": True,
                "disp": False,
            },
        )
    except Exception as exc:  # SciPy/HiGHS can raise ValueError or runtime errors.
        raise OptimizationError(
            f"{stage_name} solver execution failed: {exc}",
            status="exception",
            solver_message=str(exc),
            stage=stage_name,
            inputs_to_check=(
                "weekly_supply",
                "total_budget",
                "warehouse_capacity_m3",
                "item_volume_m3",
                "solver_config",
            ),
        ) from exc

    # HiGHS status 0 means an optimal solution was proven.  A time-limit
    # incumbent is deliberately rejected because it cannot preserve exact
    # lexicographic ordering in subsequent stages.
    if result.status != 0 or result.x is None or result.fun is None:
        raise OptimizationError(
            f"{stage_name} did not return a proven optimal solution.",
            status=result.status,
            solver_message=str(result.message),
            stage=stage_name,
            inputs_to_check=(
                "solver_config.time_limit_seconds",
                "weekly_supply",
                "total_budget",
                "warehouse_capacity_m3",
                "item_volume_m3",
            ),
        )
    if not np.all(np.isfinite(result.x)) or not math.isfinite(float(result.fun)):
        raise OptimizationError(
            f"{stage_name} returned non-finite solution values.",
            status=result.status,
            solver_message=str(result.message),
            stage=stage_name,
            inputs_to_check=("all numeric inputs",),
        )
    return result


def _solve_lexicographically(
    model: _OptimizationModel, config: SolverConfig
) -> tuple[np.ndarray, dict[str, float]]:
    stage_one = _solve_stage(
        model.stage_one_objective, model, config, "Stage 1 (minimize maximum unmet rate)"
    )
    stage_one_optimum = float(stage_one.fun)
    stage_one_constraint = _objective_constraint(
        model.stage_one_objective,
        stage_one_optimum + config.objective_tolerance,
    )

    stage_two = _solve_stage(
        model.stage_two_objective,
        model,
        config,
        "Stage 2 (minimize weighted normalized unmet demand)",
        (stage_one_constraint,),
    )
    stage_two_optimum = float(stage_two.fun)
    stage_two_constraint = _objective_constraint(
        model.stage_two_objective,
        stage_two_optimum + config.objective_tolerance,
    )

    stage_three = _solve_stage(
        model.stage_three_objective,
        model,
        config,
        "Stage 3 (minimize procurement cost)",
        (stage_one_constraint, stage_two_constraint),
    )
    return np.asarray(stage_three.x, dtype=float), {
        "stage_1_max_unmet_rate": stage_one_optimum,
        "stage_2_weighted_unmet_objective": stage_two_optimum,
        "stage_3_procurement_cost": float(stage_three.fun),
    }


def _clean_continuous(value: float) -> float:
    if abs(value) <= 1e-8:
        return 0.0
    return float(value)


def _extract_values(
    solution: np.ndarray, index: _VariableIndex, data: _NormalizedInput
) -> dict[str, dict[tuple[str, str, int], float]]:
    values: dict[str, dict[tuple[str, str, int], float]] = {
        "shipment": {},
        "served": {},
        "unmet": {},
        "inventory": {},
    }
    index_groups = {
        "shipment": index.shipment,
        "served": index.served,
        "unmet": index.unmet,
        "inventory": index.inventory,
    }
    for group_name, group_index in index_groups.items():
        for key, position in group_index.items():
            raw_value = _clean_continuous(float(solution[position]))
            if raw_value < -_NUMERICAL_CHECK_TOLERANCE:
                raise OptimizationError(
                    f"Solver returned negative {group_name} for cell {key}: "
                    f"{raw_value}.",
                    status="invalid_solution",
                    stage="post-solve verification",
                )
            if key[1] in DISCRETE_ITEMS:
                rounded = round(raw_value)
                if abs(raw_value - rounded) > _NUMERICAL_CHECK_TOLERANCE:
                    raise OptimizationError(
                        f"Solver returned non-integer {group_name} for discrete cell {key}: "
                        f"{raw_value}.",
                        status="invalid_solution",
                        stage="post-solve verification",
                    )
                raw_value = float(rounded)
            values[group_name][key] = 0.0 if raw_value < 0 else raw_value
    return values


def _verify_solution(
    values: dict[str, dict[tuple[str, str, int], float]],
    data: _NormalizedInput,
    demands: _DemandData,
    stage_objectives: Mapping[str, float],
) -> None:
    tol = _NUMERICAL_CHECK_TOLERANCE
    for site in data.sites:
        for item in ITEMS:
            previous_inventory = data.initial_inventory[site][item]
            for week in data.weeks:
                key = (site, item, week)
                shipment = values["shipment"][key]
                served = values["served"][key]
                unmet = values["unmet"][key]
                inventory = values["inventory"][key]
                demand = demands.demand[key]
                if min(shipment, served, unmet, inventory) < -tol:
                    raise OptimizationError(
                        f"Negative decision variable detected for {key}.",
                        status="invalid_solution",
                        stage="post-solve verification",
                    )
                if abs(served + unmet - demand) > tol:
                    raise OptimizationError(
                        f"Demand identity failed for {key}.",
                        status="invalid_solution",
                        stage="post-solve verification",
                    )
                if abs(previous_inventory + shipment - served - inventory) > tol:
                    raise OptimizationError(
                        f"Inventory flow identity failed for {key}.",
                        status="invalid_solution",
                        stage="post-solve verification",
                    )
                previous_inventory = inventory

    for item in ITEMS:
        for week in data.weeks:
            total_shipment = sum(
                values["shipment"][(site, item, week)] for site in data.sites
            )
            if total_shipment > data.weekly_supply[item][week] + tol:
                raise OptimizationError(
                    f"Weekly supply constraint failed for {(item, week)}.",
                    status="invalid_solution",
                    stage="post-solve verification",
                )

    total_cost = sum(
        values["shipment"][(site, item, week)] * data.unit_cost[item]
        for site in data.sites
        for item in ITEMS
        for week in data.weeks
    )
    if total_cost > data.total_budget + tol:
        raise OptimizationError(
            "Budget constraint failed in the returned solution.",
            status="invalid_solution",
            stage="post-solve verification",
        )

    for site in data.sites:
        for week_position, week in enumerate(data.weeks):
            peak_volume = 0.0
            for item in ITEMS:
                if week_position == 0:
                    before_delivery = data.initial_inventory[site][item]
                else:
                    previous_week = data.weeks[week_position - 1]
                    before_delivery = values["inventory"][(site, item, previous_week)]
                peak_quantity = before_delivery + values["shipment"][(site, item, week)]
                peak_volume += peak_quantity * data.item_volume_m3[item]
            if peak_volume > data.warehouse_capacity_m3[site] + tol:
                raise OptimizationError(
                    f"Peak warehouse capacity failed for {(site, week)}.",
                    status="invalid_solution",
                    stage="post-solve verification",
                )

    # Ensure the final plan still respects the lexicographic objective locks.
    actual_max_unmet = max(
        (
            values["unmet"][key] / demand
            for key, demand in demands.demand.items()
            if demand > 0
        ),
        default=0.0,
    )
    if actual_max_unmet > (
        stage_objectives["stage_1_max_unmet_rate"]
        + data.solver_config.objective_tolerance
        + tol
    ):
        raise OptimizationError(
            "Stage 1 objective lock failed in the final plan.",
            status="invalid_solution",
            stage="post-solve verification",
        )

    actual_stage_two = 0.0
    for item in ITEMS:
        total_demand = demands.item_total_demand[item]
        if total_demand <= 0:
            continue
        actual_stage_two += data.item_weights[item] * sum(
            values["unmet"][(site, item, week)]
            for site in data.sites
            for week in data.weeks
        ) / total_demand
    if actual_stage_two > (
        stage_objectives["stage_2_weighted_unmet_objective"]
        + data.solver_config.objective_tolerance
        + tol
    ):
        raise OptimizationError(
            "Stage 2 objective lock failed in the final plan.",
            status="invalid_solution",
            stage="post-solve verification",
        )

    expected_cost = stage_objectives["stage_3_procurement_cost"]
    cost_tolerance = max(tol, 1e-9 * abs(expected_cost))
    if abs(total_cost - expected_cost) > cost_tolerance:
        raise OptimizationError(
            "Stage 3 procurement cost does not match the returned plan.",
            status="invalid_solution",
            stage="post-solve verification",
        )


def _display_number(value: float, *, integer: bool) -> int | float:
    if integer:
        return int(round(value))
    return float(value)


def _format_message(
    selected_site: str,
    max_unmet_rate: float,
    fulfillment_rate: float,
    procurement_cost: float,
    budget_remaining: float,
    weeks_count: int,
) -> str:
    scope = f"{selected_site} 구호소"
    return (
        f"이 구호품 전달 계획을 사용하면 {scope}의 주어진 재고·주간 공급량·"
        "예산·창고용량 "
        f"제약 아래 {weeks_count}주 계획의 최대 미충족률을 "
        f"{max_unmet_rate * 100:.1f}%까지 낮추고, 품목별 단위를 정규화한 전체 "
        f"가중 수요의 {fulfillment_rate * 100:.1f}%를 충족할 수 있습니다. "
        f"총 조달비용은 {procurement_cost:,.2f}(입력 통화 단위)이며 잔여 예산은 "
        f"{budget_remaining:,.2f}(입력 통화 단위)입니다."
    )


def _format_result(
    values: dict[str, dict[tuple[str, str, int], float]],
    data: _NormalizedInput,
    demands: _DemandData,
    stage_objectives: Mapping[str, float],
) -> dict[str, Any]:
    plan: list[dict[str, Any]] = []
    for site in data.sites:
        for week in data.weeks:
            for item in ITEMS:
                key = (site, item, week)
                demand = demands.demand[key]
                shipment = values["shipment"][key]
                served = values["served"][key]
                unmet = values["unmet"][key]
                inventory = values["inventory"][key]
                is_discrete = item in DISCRETE_ITEMS
                plan.append(
                    {
                        "site": site,
                        "week": int(week),
                        "item": item,
                        "unit": ITEM_UNITS[item],
                        "forecast_arrivals": data.forecast[site][week],
                        "supported_people": demands.supported_people[(site, week)],
                        "demand": _display_number(demand, integer=is_discrete),
                        "recommended_shipment": _display_number(
                            shipment, integer=is_discrete
                        ),
                        "served": _display_number(served, integer=is_discrete),
                        "ending_inventory": _display_number(
                            inventory, integer=is_discrete
                        ),
                        "unmet_demand": _display_number(unmet, integer=is_discrete),
                        "fulfillment_rate": 1.0 if demand == 0 else served / demand,
                    }
                )

    item_summary: list[dict[str, Any]] = []
    for item in ITEMS:
        total_demand = demands.item_total_demand[item]
        total_served = sum(
            values["served"][(site, item, week)]
            for site in data.sites
            for week in data.weeks
        )
        total_unmet = sum(
            values["unmet"][(site, item, week)]
            for site in data.sites
            for week in data.weeks
        )
        is_discrete = item in DISCRETE_ITEMS
        item_summary.append(
            {
                "item": item,
                "unit": ITEM_UNITS[item],
                "total_demand": _display_number(total_demand, integer=is_discrete),
                "total_served": _display_number(total_served, integer=is_discrete),
                "total_unmet_demand": _display_number(
                    total_unmet, integer=is_discrete
                ),
                "fulfillment_rate": (
                    1.0 if total_demand == 0 else total_served / total_demand
                ),
                "weight": data.item_weights[item],
            }
        )

    site_summary: list[dict[str, Any]] = []
    for site in data.sites:
        weighted_unmet = 0.0
        active_weight = 0.0
        for item in ITEMS:
            site_demand = sum(
                demands.demand[(site, item, week)] for week in data.weeks
            )
            if site_demand <= 0:
                continue
            site_unmet = sum(
                values["unmet"][(site, item, week)] for week in data.weeks
            )
            weight = data.item_weights[item]
            weighted_unmet += weight * site_unmet / site_demand
            active_weight += weight
        normalized_unmet = weighted_unmet / active_weight if active_weight else 0.0
        site_summary.append(
            {
                "site": site,
                "weighted_fulfillment_rate": 1.0 - normalized_unmet,
            }
        )

    warehouse_summary: list[dict[str, Any]] = []
    for site in data.sites:
        capacity = data.warehouse_capacity_m3[site]
        for week_position, week in enumerate(data.weeks):
            peak_volume = 0.0
            for item in ITEMS:
                if week_position == 0:
                    before_delivery = data.initial_inventory[site][item]
                else:
                    previous_week = data.weeks[week_position - 1]
                    before_delivery = values["inventory"][(site, item, previous_week)]
                peak_volume += (
                    before_delivery + values["shipment"][(site, item, week)]
                ) * data.item_volume_m3[item]
            warehouse_summary.append(
                {
                    "site": site,
                    "week": int(week),
                    "peak_inventory_volume_m3": peak_volume,
                    "warehouse_capacity_m3": capacity,
                    "warehouse_utilization_rate": peak_volume / capacity,
                }
            )

    positive_demand_cells = [
        key for key, demand in demands.demand.items() if demand > 0
    ]
    max_unmet_rate = max(
        (
            values["unmet"][key] / demands.demand[key]
            for key in positive_demand_cells
        ),
        default=0.0,
    )
    weighted_unmet_sum = 0.0
    active_weight_sum = 0.0
    for item in ITEMS:
        total_demand = demands.item_total_demand[item]
        if total_demand <= 0:
            continue
        total_unmet = sum(
            values["unmet"][(site, item, week)]
            for site in data.sites
            for week in data.weeks
        )
        weight = data.item_weights[item]
        weighted_unmet_sum += weight * total_unmet / total_demand
        active_weight_sum += weight
    overall_weighted_unmet_rate = (
        weighted_unmet_sum / active_weight_sum if active_weight_sum else 0.0
    )
    overall_weighted_fulfillment_rate = 1.0 - overall_weighted_unmet_rate
    total_procurement_cost = sum(
        values["shipment"][(site, item, week)] * data.unit_cost[item]
        for site in data.sites
        for item in ITEMS
        for week in data.weeks
    )
    budget_remaining = max(0.0, data.total_budget - total_procurement_cost)

    summary = {
        "selected_site": data.selected_site,
        "planning_sites": list(data.sites),
        "utilization_rate": data.utilization_rate,
        "stay_days": data.stay_days,
        "planning_weeks": list(data.weeks),
        "max_unmet_rate": max_unmet_rate,
        "overall_weighted_unmet_rate": overall_weighted_unmet_rate,
        "overall_weighted_fulfillment_rate": overall_weighted_fulfillment_rate,
        "total_procurement_cost": total_procurement_cost,
        "budget": data.total_budget,
        "budget_remaining": budget_remaining,
        "message": _format_message(
            data.selected_site,
            max_unmet_rate,
            overall_weighted_fulfillment_rate,
            total_procurement_cost,
            budget_remaining,
            len(data.weeks),
        ),
    }

    model_info = {
        "site_scope": "single selected site",
        "selected_site": data.selected_site,
        "planning_sites": list(data.sites),
        "operational_input_scope": (
            "Every user_input value (utilization_rate, stay_days, initial_inventory, "
            "weekly_supply, unit_cost, total_budget, and warehouse_capacity_m3) "
            "applies only to selected_site."
        ),
        "solver": "scipy.optimize.milp (HiGHS mixed-integer linear programming)",
        "optimization_method": (
            "Three-stage lexicographic optimization: (1) minimize maximum cell-level "
            "unmet rate, (2) minimize weighted item-normalized unmet demand while "
            "locking Stage 1, (3) minimize procurement cost while locking Stages 1-2."
        ),
        "stage_objectives": dict(stage_objectives),
        "objective_tolerance": data.solver_config.objective_tolerance,
        "solver_config": {
            "time_limit_seconds_per_stage": data.solver_config.time_limit_seconds,
            "mip_rel_gap": data.solver_config.mip_rel_gap,
            "objective_tolerance": data.solver_config.objective_tolerance,
        },
        "demand_assumptions": {
            "water": "15 L per supported person per stay day",
            "food": "1 daily ration (2,100 kcal) per supported person per stay day",
            "hygiene_kit": "1 personal kit per supported person",
            "blanket": "1 personal blanket per supported person",
        },
        "time_aggregation_assumption": (
            "Because stay_days is at most 4 and the planning period is weekly, all water "
            "and food demand generated during the stay of people arriving in a week is "
            "assigned to that same week; no cross-week daily occupancy model is included."
        ),
        "warehouse_capacity_basis": (
            "Peak inventory immediately after each week's delivery and before distribution."
        ),
        "integrality": {
            "water": "continuous liters",
            "food": "integer daily rations",
            "hygiene_kit": "integer kits",
            "blanket": "integer blankets",
        },
        "currency_assumption": (
            "The engine does not assume a currency. unit_cost and total_budget must use "
            "one consistent currency chosen by the UI/caller."
        ),
        "resource_scope": (
            "In single-site mode, weekly_supply and total_budget are the amounts "
            "allocated to the selected site's scenario. Results from separate site "
            "runs are alternatives and must not be summed unless the caller has "
            "already partitioned shared central resources."
        ),
        "limitations": [
            "No transport vehicle/corridor capacity constraints",
            "No procurement or transport lead times",
            "No shelf-life or expiry constraints",
            "No cross-week daily occupancy model",
        ],
    }

    return {
        "summary": summary,
        "plan": plan,
        "item_summary": item_summary,
        "site_summary": site_summary,
        "warehouse_summary": warehouse_summary,
        "model_info": model_info,
    }


def optimize_relief_plan(
    ml_forecast: Mapping[str, Mapping[int, Real]],
    user_input: Mapping[str, Any],
    item_volume_m3: Mapping[str, Real],
    item_weights: Mapping[str, Real] | None = None,
    solver_config: SolverConfig | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute an optimal weekly relief procurement and allocation plan.

    Args:
        ml_forecast: Forecast arrivals for 1-4 consecutive weeks starting at
            week 1. In selected-site mode, it may contain either only that site
            or all three known sites; only the selected site is optimized.
        user_input: Operational inputs containing utilization, stay, inventories,
            supplies, unit costs, budget, and warehouse capacity.
            ``selected_site`` is required, and inventory/capacity mappings must
            contain exactly that one site. Every operational value applies only
            to this selected-site run.
        item_volume_m3: Actual packed volume per unit for every item.  The caller
            must supply real product values for operational use.
        item_weights: Optional strictly-positive weights for normalized Stage 2
            and summary metrics.  Defaults to 1.0 for every item.
        solver_config: Optional :class:`SolverConfig` or equivalent mapping.

    Returns:
        A JSON-serializable dictionary containing summary, plan, item_summary,
        site_summary, warehouse_summary, and model_info.

    Raises:
        InputValidationError: If any input is missing, invalid, non-finite, or
            initially exceeds warehouse capacity.
        OptimizationError: If a solver stage cannot prove an optimal solution or
            post-solve constraint verification fails.
    """

    normalized = _normalize_and_validate(
        ml_forecast, user_input, item_volume_m3, item_weights, solver_config
    )
    demands = _calculate_demands(normalized)
    model = _build_milp_model(normalized, demands)
    solution, stage_objectives = _solve_lexicographically(
        model, normalized.solver_config
    )
    values = _extract_values(solution, model.index, normalized)
    _verify_solution(values, normalized, demands, stage_objectives)
    return _format_result(values, normalized, demands, stage_objectives)


def compare_scenarios(
    ml_forecast: Mapping[str, Mapping[int, Real]],
    base_user_input: Mapping[str, Any],
    item_volume_m3: Mapping[str, Real],
    item_weights: Mapping[str, Real] | None = None,
    solver_config: SolverConfig | Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run all 12 utilization-rate and stay-duration combinations.

    The caller's mapping is never mutated.  Each returned row is the scenario's
    summary subset and is directly suitable for a DataFrame or JSON encoding.
    ``base_user_input['selected_site']`` is required. All 12 rows optimize only
    that site and identify it in ``selected_site``.
    """

    base = _require_mapping(base_user_input, "base_user_input")
    results: list[dict[str, Any]] = []
    for utilization_rate in _ALLOWED_UTILIZATION_RATES:
        for stay_days in _ALLOWED_STAY_DAYS:
            scenario_input = deepcopy(dict(base))
            scenario_input["utilization_rate"] = utilization_rate
            scenario_input["stay_days"] = stay_days
            result = optimize_relief_plan(
                ml_forecast,
                scenario_input,
                item_volume_m3,
                item_weights=item_weights,
                solver_config=solver_config,
            )
            summary = result["summary"]
            results.append(
                {
                    "selected_site": summary["selected_site"],
                    "utilization_rate": summary["utilization_rate"],
                    "stay_days": summary["stay_days"],
                    "max_unmet_rate": summary["max_unmet_rate"],
                    "overall_weighted_unmet_rate": summary[
                        "overall_weighted_unmet_rate"
                    ],
                    "overall_weighted_fulfillment_rate": summary[
                        "overall_weighted_fulfillment_rate"
                    ],
                    "total_procurement_cost": summary["total_procurement_cost"],
                    "budget_remaining": summary["budget_remaining"],
                    "message": summary["message"],
                }
            )
    return results


def example_inputs(
    selected_site: str = "Medyka",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, float]]:
    """Return a complete, deliberately synthetic four-week example.

    SYNTHETIC EXAMPLE ONLY — NOT REAL MEDYKA/KORCZOWA/DOROHUSK OPERATIONAL
    DATA.  In particular, replace ``item_volume_m3`` with measured packed
    product volumes before any operational use. The returned operational input
    always contains exactly one selected site.
    """

    # SYNTHETIC EXAMPLE ONLY.
    # NOT REAL MEDYKA/KORCZOWA/DOROHUSK OPERATIONAL DATA.
    ml_forecast: dict[str, Any] = {
        "Medyka": {1: 4000, 2: 3500, 3: 3800, 4: 3200},
        "Korczowa": {1: 2000, 2: 2200, 3: 1900, 4: 2100},
        "Dorohusk": {1: 1500, 2: 1400, 3: 1600, 4: 1300},
    }

    # SYNTHETIC EXAMPLE ONLY.
    # NOT REAL MEDYKA/KORCZOWA/DOROHUSK OPERATIONAL DATA.
    user_input: dict[str, Any] = {
        "utilization_rate": 0.10,
        "stay_days": 3,
        "initial_inventory": {
            "Medyka": {
                "water": 12000,
                "food": 800,
                "hygiene_kit": 150,
                "blanket": 180,
            },
            "Korczowa": {
                "water": 7000,
                "food": 450,
                "hygiene_kit": 100,
                "blanket": 120,
            },
            "Dorohusk": {
                "water": 5000,
                "food": 350,
                "hygiene_kit": 80,
                "blanket": 100,
            },
        },
        "weekly_supply": {
            "water": {1: 18000, 2: 18000, 3: 16000, 4: 16000},
            "food": {1: 1200, 2: 1200, 3: 1000, 4: 1000},
            "hygiene_kit": {1: 350, 2: 350, 3: 300, 4: 300},
            "blanket": {1: 400, 2: 400, 3: 350, 4: 350},
        },
        "unit_cost": {
            "water": 1.0,
            "food": 10.0,
            "hygiene_kit": 25.0,
            "blanket": 30.0,
        },
        "total_budget": 110000.0,
        "warehouse_capacity_m3": {
            "Medyka": 45.0,
            "Korczowa": 30.0,
            "Dorohusk": 25.0,
        },
    }

    if not isinstance(selected_site, str) or selected_site not in SITES:
        raise InputValidationError(
            f"selected_site must be exactly one of {', '.join(SITES)}."
        )
    user_input["selected_site"] = selected_site
    user_input["initial_inventory"] = {
        selected_site: user_input["initial_inventory"][selected_site]
    }
    user_input["warehouse_capacity_m3"] = {
        selected_site: user_input["warehouse_capacity_m3"][selected_site]
    }
    ml_forecast = {selected_site: ml_forecast[selected_site]}

    # These packed volumes are illustrative placeholders, not measured product
    # specifications and not real operational values.
    # SYNTHETIC EXAMPLE ONLY.
    # NOT REAL MEDYKA/KORCZOWA/DOROHUSK OPERATIONAL DATA.
    item_volume_m3 = {
        "water": 0.001,
        "food": 0.002,
        "hygiene_kit": 0.010,
        "blanket": 0.020,
    }
    return ml_forecast, user_input, item_volume_m3


__all__ = [
    "InputValidationError",
    "OptimizationError",
    "SolverConfig",
    "compare_scenarios",
    "example_inputs",
    "optimize_relief_plan",
]

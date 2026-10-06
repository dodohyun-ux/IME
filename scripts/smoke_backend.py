#!/usr/bin/env python3
"""Exercise the packaged forecast API functions and optimization solver."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ofr_v2" / "app"))

from backend.main import (  # noqa: E402
    OptimizeRequest,
    PredictionRequest,
    health,
    history,
    meta,
    optimize,
    predict,
)


def main() -> None:
    assert health()["status"] == "ok"
    assert len(meta()["hubs"]) == 3
    reference_date = "2026-01-26"
    inputs = history(reference_date)
    assert len(inputs["weeks"]) == 2
    assert all(len(row) == 2 for row in inputs["hub_inflow"].values())

    forecast = predict(PredictionRequest(reference_date=reference_date, hub_inflow=inputs["hub_inflow"]))
    assert forecast["source"] == "relief_model"
    assert all(forecast[f"week{week}"] > 0 for week in range(1, 5))

    items = ("water", "food", "hygiene_kit", "blanket")
    request = OptimizeRequest(
        ml_forecast={"Medyka": {str(week): value for week, value in enumerate(
            forecast["hub_forecast"]["medyka"], start=1
        )}},
        selected_site="Medyka",
        utilization_rate=0.10,
        stay_days=2,
        initial_inventory={"Medyka": {item: 0 for item in items}},
        weekly_supply={item: {str(week): 100_000 for week in range(1, 5)} for item in items},
        unit_cost={"water": 1, "food": 5, "hygiene_kit": 10, "blanket": 15},
        total_budget=1_000_000,
        warehouse_capacity_m3={"Medyka": 10_000},
        item_volume_m3={"water": 0.001, "food": 0.003, "hygiene_kit": 0.005, "blanket": 0.01},
        priority="fairness",
    )
    result = optimize(request)
    assert len(result["plan"]) == 16
    assert result["summary"]["selected_site"] == "Medyka"
    assert result["summary"]["overall_weighted_fulfillment_rate"] > 0.99
    print("Backend smoke verification passed.")


if __name__ == "__main__":
    main()


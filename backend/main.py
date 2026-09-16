from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.optimization import (
    optimize_relief_plan,
    InputValidationError,
    OptimizationError,
)

from pathlib import Path
from datetime import datetime, timedelta
import sys
import math

import joblib
import numpy as np
import pandas as pd


# --------------------------------------------------
# sklearn joblib compatibility
# --------------------------------------------------
try:
    import sklearn._loss._loss as sklearn_loss
    sys.modules["_loss"] = sklearn_loss
except Exception:
    pass


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8443",
        "http://127.0.0.1:8443",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# Model loading
# --------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT_DIR / "models"

MODEL_FILES = {
    "medyka": (
        MODEL_DIR / "model_Medyka_-_Szeginie.joblib",
        0.40,
    ),
    "dorohusk": (
        MODEL_DIR / "model_Dorohusk_-_Jagodzin.joblib",
        0.35,
    ),
    "korczowa": (
        MODEL_DIR / "model_Korczowa_-_Krakowiec.joblib",
        0.25,
    ),
}


MODELS = {}

for hub, (path, share) in MODEL_FILES.items():

    if not path.exists():
        raise RuntimeError(f"모델 파일을 찾을 수 없습니다: {path}")

    MODELS[hub] = {
        "models": joblib.load(path),
        "share": share,
    }


FEATURES = list(
    MODELS["medyka"]["models"][0.5].feature_names_in_
)


# --------------------------------------------------
# Request structure
# --------------------------------------------------
class ConflictRow(BaseModel):
    events: float = 0
    explosive: float = 0
    civilian: float = 0
    deaths: float = 0


class PredictionRequest(BaseModel):
    reference_date: str
    inflow: list[float]
    conflict: list[ConflictRow] = []
    use_conflict: bool = True


# --------------------------------------------------
# Helpers
# --------------------------------------------------
def weekly_to_daily(values):
    """
    UI:
    [최근1주, 최근2주, ... 최근8주]

    Model:
    oldest -> newest daily values
    """

    daily = []

    for weekly_value in reversed(values[:8]):
        daily_value = max(float(weekly_value), 0) / 7

        daily.extend([daily_value] * 7)

    return daily


def model_median_feature(model, feature_name):

    index = list(model.feature_names_in_).index(feature_name)

    thresholds = model._bin_mapper.bin_thresholds_[index]

    if len(thresholds) == 0:
        return 0.0

    return float(thresholds[len(thresholds) // 2])


def build_conflict_history(request, model):

    if not request.use_conflict or len(request.conflict) == 0:

        return (
            [np.nan] * 28,
            [np.nan] * 28,
        )

    rows = request.conflict[:4]

    events = [
        max(float(row.events), 0)
        for row in rows
    ]

    deaths = [
        max(float(row.deaths), 0)
        for row in rows
    ]

    event_base = np.median(events)

    death_base = np.median(deaths)

    if event_base <= 0:
        event_base = 1

    if death_base <= 0:
        death_base = 1

    training_intensity = model_median_feature(
        model,
        "conflict_intensity"
    )

    training_severity = model_median_feature(
        model,
        "conflict_severity"
    )

    intensity = []
    severity = []

    # oldest -> newest
    for row in reversed(rows):

        i = (
            training_intensity
            * max(float(row.events), 0)
            / event_base
        )

        s = (
            training_severity
            * max(float(row.deaths), 0)
            / death_base
        )

        intensity.extend([i] * 7)

        severity.extend([s] * 7)

    return intensity, severity


def inverse_target(value):
    """
    Stored models output log-scale prediction.
    Convert back to person count.
    """

    value = float(value)

    if value > 30:
        return max(value, 0)

    return max(math.expm1(value), 0)


def predict_hub(
    model_bundle,
    share,
    request,
    reference_date,
):

    median_model = model_bundle[0.5]

    # 8 weekly totals -> 56 daily observations
    total_history = weekly_to_daily(request.inflow)

    # convert total 3-hub inflow to each hub history
    target_history = [
        value * share
        for value in total_history
    ]

    intensity_history, severity_history = (
        build_conflict_history(
            request,
            median_model,
        )
    )

    daily_predictions = {
        0.1: [],
        0.5: [],
        0.9: [],
    }

    forecast_start = reference_date + timedelta(days=7)

    for step in range(28):

        forecast_date = (
            forecast_start
            + timedelta(days=step)
        )

        use_conflict = (
            request.use_conflict
            and not np.isnan(intensity_history[-1])
        )

        if use_conflict:

            conflict_intensity = intensity_history[-1]
            conflict_severity = severity_history[-1]

            conflict_intensity_lagged = (
                intensity_history[-2]
            )

            conflict_severity_lagged = (
                severity_history[-2]
            )

            conflict_intensity_rollmean_7 = float(
                np.mean(intensity_history[-7:])
            )

            conflict_severity_rollmean_7 = float(
                np.mean(severity_history[-7:])
            )

        else:

            conflict_intensity = np.nan
            conflict_severity = np.nan
            conflict_intensity_lagged = np.nan
            conflict_severity_lagged = np.nan
            conflict_intensity_rollmean_7 = np.nan
            conflict_severity_rollmean_7 = np.nan

        row = {
            "conflict_intensity":
                conflict_intensity,

            "conflict_severity":
                conflict_severity,

            "conflict_intensity_lagged":
                conflict_intensity_lagged,

            "conflict_severity_lagged":
                conflict_severity_lagged,

            # original spatial preprocessing is unavailable.
            # use model's central training value.
            "nearest_dist_km":
                model_median_feature(
                    median_model,
                    "nearest_dist_km",
                ),

            "conflict_intensity_rollmean_7":
                conflict_intensity_rollmean_7,

            "conflict_severity_rollmean_7":
                conflict_severity_rollmean_7,

            "dow":
                forecast_date.weekday(),

            "month":
                forecast_date.month,

            "days_since_war_start":
                (
                    forecast_date
                    - datetime(2022, 2, 24)
                ).days,

            "is_early_war":
                0,

            "target_lag_1":
                target_history[-1],

            "target_lag_2":
                target_history[-2],

            "target_lag_3":
                target_history[-3],

            "target_lag_7":
                target_history[-7],

            "target_lag_14":
                target_history[-14],

            "target_rollmean_7":
                float(
                    np.mean(
                        target_history[-7:]
                    )
                ),

            "target_rollmean_14":
                float(
                    np.mean(
                        target_history[-14:]
                    )
                ),

            "target_rollstd_7":
                float(
                    np.std(
                        target_history[-7:],
                        ddof=1,
                    )
                ),

            "target_rollstd_14":
                float(
                    np.std(
                        target_history[-14:],
                        ddof=1,
                    )
                ),
        }

        X = pd.DataFrame(
            [[row[f] for f in FEATURES]],
            columns=FEATURES,
        )

        today = {}

        for quantile in [0.1, 0.5, 0.9]:

            raw = model_bundle[
                quantile
            ].predict(X)[0]

            today[quantile] = (
                inverse_target(raw)
            )

            daily_predictions[
                quantile
            ].append(
                today[quantile]
            )

        # recursive forecast uses median prediction
        target_history.append(
            today[0.5]
        )

        # future conflict = latest observed level
        intensity_history.append(
            intensity_history[-1]
        )

        severity_history.append(
            severity_history[-1]
        )

    weekly = {}

    for q in [0.1, 0.5, 0.9]:

        weekly[q] = []

        for week in range(4):

            start = week * 7
            end = start + 7

            value = sum(
                daily_predictions[q][start:end]
            )

            weekly[q].append(value)

    return weekly


@app.get("/")
def root():
    return {
        "message":
            "Poland Relief backend 정상 작동"
    }


@app.post("/predict")
def predict(request: PredictionRequest):

    if len(request.inflow) < 8:
        raise HTTPException(
            status_code=400,
            detail="최근 8주 유입량이 필요합니다.",
        )

    if (
        request.use_conflict
        and len(request.conflict) < 4
    ):
        raise HTTPException(
            status_code=400,
            detail="최근 4주 분쟁정보가 필요합니다.",
        )

    try:

        reference_date = datetime.strptime(
            request.reference_date,
            "%Y-%m-%d",
        )

        hub_results = {}

        for hub, info in MODELS.items():

            hub_results[hub] = predict_hub(
                info["models"],
                info["share"],
                request,
                reference_date,
            )

        total_median = []

        total_low = []

        total_high = []

        for week in range(4):

            median = sum(
                hub_results[h][0.5][week]
                for h in hub_results
            )

            low = sum(
                hub_results[h][0.1][week]
                for h in hub_results
            )

            high = sum(
                hub_results[h][0.9][week]
                for h in hub_results
            )

            bounds = sorted(
                [low, median, high]
            )

            total_low.append(
                round(bounds[0])
            )

            total_median.append(
                round(median)
            )

            total_high.append(
                round(bounds[2])
            )

        return {
            "week1": total_median[0],
            "week2": total_median[1],
            "week3": total_median[2],
            "week4": total_median[3],

            "intervals": [
                {
                    "low": total_low[i],
                    "high": total_high[i],
                }
                for i in range(4)
            ],

            "hub_forecast": {
                hub: [
                    round(v)
                    for v in result[0.5]
                ]
                for hub, result
                in hub_results.items()
            },

            "source": "joblib_models",
        }

    except Exception as e:

        print("PREDICTION ERROR:", repr(e))

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )

class OptimizeRequest(BaseModel):
    ml_forecast: dict[str, dict[int, float]]

    selected_site: str
    utilization_rate: float
    stay_days: int

    initial_inventory: dict[str, dict[str, float]]
    weekly_supply: dict[str, dict[int, float]]
    unit_cost: dict[str, float]

    total_budget: float

    warehouse_capacity_m3: dict[str, float]
    item_volume_m3: dict[str, float]


@app.post("/optimize")
def optimize(request: OptimizeRequest):

    user_input = {
        "selected_site": request.selected_site,
        "utilization_rate": request.utilization_rate,
        "stay_days": request.stay_days,

        "initial_inventory": request.initial_inventory,
        "weekly_supply": request.weekly_supply,
        "unit_cost": request.unit_cost,

        "total_budget": request.total_budget,
        "warehouse_capacity_m3": request.warehouse_capacity_m3,
    }

    try:
        result = optimize_relief_plan(
            ml_forecast=request.ml_forecast,
            user_input=user_input,
            item_volume_m3=request.item_volume_m3,
        )

        return result

    except InputValidationError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )

    except OptimizationError as e:
        raise HTTPException(
            status_code=422,
            detail=str(e),
        )

    except Exception as e:
        print("OPTIMIZATION ERROR:", repr(e))

        raise HTTPException(
            status_code=500,
            detail=str(e),
        )
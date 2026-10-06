"""Team-supplied daily recursive forecaster, isolated from current optimization API.
Source preserved in incoming/forecast_20261006; estimator weights and feature formulas unchanged.
"""
from fastapi import HTTPException
from pydantic import BaseModel

from backend.bundle import load_bundle

from datetime import datetime, timedelta
import math

import numpy as np
import pandas as pd


# --------------------------------------------------
# Model loading
# --------------------------------------------------
WAR_START = datetime(2022, 2, 24)

# 학습 전처리(ofr_dashboard)와 동일: 개전 후 30일까지 '개전 초기'
EARLY_WAR_WINDOW_DAYS = 30

# 학습 마지막 날 = ACLED 종료일(2025-07-08) - 검증용 홀드아웃 60일
TRAINING_END = datetime(2025, 5, 9)


# --------------------------------------------------
# Calibration
# --------------------------------------------------
# The models were trained on per-crossing, distance-weighted daily conflict
# features (sum of exp(-distance/150km) over ACLED events). The UI collects
# Ukraine-wide weekly totals, so backend/calibrate.py estimates per-hub
# conversion factors from the training data:
#
#   daily intensity = intensity_per_event * weekly events / 7
#   daily severity  = (severity_per_death * weekly deaths
#                      + severity_per_event * weekly events) / 7
#
# Models and calibration live in one file: models/relief_model.joblib
BUNDLE = load_bundle()

CALIBRATION = BUNDLE["calibration"]

if not CALIBRATION:
    raise RuntimeError(
        "모델 파일에 보정값이 없습니다. "
        "python -m backend.calibrate 로 생성하세요."
    )

MODELS = {}

for hub, entry in BUNDLE["hubs"].items():

    MODELS[hub] = {
        "model": entry["model"],
        "features": list(entry["model"].feature_names_in_),

        **CALIBRATION["hubs"][hub],
    }


# --------------------------------------------------
# Request structure
# --------------------------------------------------
class ConflictRow(BaseModel):
    events: float = 0
    # explosive / civilian are accepted for the UI but not used:
    # the models have no feature for them, and adding them did not
    # improve the calibration fit (see backend/calibrate.py).
    explosive: float = 0
    civilian: float = 0
    deaths: float = 0


class PredictionRequest(BaseModel):
    reference_date: str
    # 3-hub total, [이번주, 1주 전, ... 7주 전]
    inflow: list[float]
    # optional per-hub weekly inflow in the same order.
    # When given, it is used instead of splitting the total.
    inflow_by_hub: dict[str, list[float]] | None = None
    conflict: list[ConflictRow] = []
    use_conflict: bool = True


# --------------------------------------------------
# Helpers
# --------------------------------------------------
def weekly_to_daily(values):
    """
    UI:
    [기준 주, 1주 전]

    Model:
    oldest -> newest daily values
    """

    daily = []

    for weekly_value in reversed(values[:2]):
        daily_value = float(weekly_value) / 7

        daily.extend([daily_value] * 7)

    return daily


def hub_weekly_inflow(request, hub, info):

    if request.inflow_by_hub is not None:
        return request.inflow_by_hub[hub]

    return [value * info["share"] for value in request.inflow]


def build_conflict_history(request, info):
    """
    Returns 28 daily values (oldest -> newest) for
    conflict_intensity and conflict_severity.
    """

    if request.use_conflict:
        # UI order is newest first; model needs oldest -> newest
        weeks = [
            (float(row.events), float(row.deaths))
            for row in reversed(request.conflict[:4])
        ]
    else:
        # no conflict information: assume a typical recent week
        weeks = [(
            CALIBRATION["typical_weekly_events"],
            CALIBRATION["typical_weekly_deaths"],
        )] * 4

    intensity = []
    severity = []

    for events, deaths in weeks:

        i = info["intensity_per_event"] * events / 7

        s = (
            info["severity_per_death"] * deaths
            + info["severity_per_event"] * events
        ) / 7

        intensity.extend([i] * 7)

        severity.extend([s] * 7)

    return intensity, severity


def inverse_target(value):
    """
    Stored models output log1p(person count).
    Convert back to person count.
    """

    return max(math.expm1(min(float(value), 20.0)), 0.0)


def build_feature_row(
    info,
    forecast_date,
    target_history,
    intensity_history,
    severity_history,
):

    days_since_war_start = (forecast_date - WAR_START).days

    # Histories end the day before forecast_date. In training the conflict
    # features are same-day values, so today's level is assumed to persist.
    intensity_today = intensity_history[-1]
    severity_today = severity_history[-1]

    # conflict_*_lagged = value `lag` days before forecast_date
    lag_index = -max(info["conflict_lag_days"], 1)

    row = {
        "conflict_intensity":
            intensity_today,

        "conflict_severity":
            severity_today,

        "conflict_intensity_lagged":
            intensity_history[lag_index],

        "conflict_severity_lagged":
            severity_history[lag_index],

        "nearest_dist_km":
            info["nearest_dist_km"],

        # training: rolling 7 days including the same day
        "conflict_intensity_rollmean_7":
            float(np.mean(intensity_history[-6:] + [intensity_today])),

        "conflict_severity_rollmean_7":
            float(np.mean(severity_history[-6:] + [severity_today])),

        "dow":
            forecast_date.weekday(),

        "month":
            forecast_date.month,

        "days_since_war_start":
            max(days_since_war_start, 0),

        "is_early_war":
            int(0 <= days_since_war_start <= EARLY_WAR_WINDOW_DAYS),

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
            float(np.mean(target_history[-7:])),

        "target_rollmean_14":
            float(np.mean(target_history[-14:])),

        # training: pandas rolling std (ddof=1)
        "target_rollstd_7":
            float(np.std(target_history[-7:], ddof=1)),

        "target_rollstd_14":
            float(np.std(target_history[-14:], ddof=1)),
    }

    return pd.DataFrame(
        [[row[f] for f in info["features"]]],
        columns=info["features"],
    )


def predict_hub(
    hub,
    info,
    request,
    reference_date,
):

    model = info["model"]

    # 2 weekly totals -> 14 daily observations
    target_history = weekly_to_daily(
        hub_weekly_inflow(request, hub, info)
    )

    intensity_history, severity_history = (
        build_conflict_history(request, info)
    )

    daily_predictions = []

    # input weeks end on reference_date + 6
    forecast_start = reference_date + timedelta(days=7)

    for step in range(28):

        forecast_date = forecast_start + timedelta(days=step)

        X = build_feature_row(
            info,
            forecast_date,
            target_history,
            intensity_history,
            severity_history,
        )

        today = inverse_target(model.predict(X)[0])

        daily_predictions.append(today)

        # recursive forecast
        target_history.append(today)

        # future conflict = latest observed level
        intensity_history.append(intensity_history[-1])

        severity_history.append(severity_history[-1])

    return [
        sum(daily_predictions[week * 7:(week + 1) * 7])
        for week in range(4)
    ]


def validate_prediction_request(request):

    if len(request.inflow) != 2:
        raise HTTPException(
            status_code=400,
            detail="최근 2주 유입량이 필요합니다.",
        )

    if any(not math.isfinite(v) or v < 0 for v in request.inflow[:2]):
        raise HTTPException(
            status_code=400,
            detail="유입량은 0 이상의 숫자여야 합니다.",
        )

    if request.inflow_by_hub is not None:

        if set(request.inflow_by_hub) != set(MODELS):
            raise HTTPException(
                status_code=400,
                detail=(
                    "구호소별 유입량은 "
                    f"{', '.join(MODELS)} 모두 필요합니다."
                ),
            )

        for hub, values in request.inflow_by_hub.items():

            if len(values) != 2 or any(
                not math.isfinite(v) or v < 0 for v in values[:2]
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"{hub} 의 최근 2주 유입량(0 이상)이 필요합니다.",
                )

    if request.use_conflict:

        if len(request.conflict) < 4:
            raise HTTPException(
                status_code=400,
                detail="최근 4주 분쟁정보가 필요합니다.",
            )

        for row in request.conflict[:4]:

            values = [row.events, row.explosive, row.civilian, row.deaths]

            if any(not math.isfinite(v) or v < 0 for v in values):
                raise HTTPException(
                    status_code=400,
                    detail="분쟁정보는 0 이상의 숫자여야 합니다.",
                )

    try:
        return datetime.strptime(request.reference_date, "%Y-%m-%d")

    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="reference_date 형식은 YYYY-MM-DD 여야 합니다.",
        )

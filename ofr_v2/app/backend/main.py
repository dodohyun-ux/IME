"""Poland Relief 백엔드.

실행(앱 루트에서): uvicorn backend.main:app --host 0.0.0.0 --port 8000
환경변수 ALLOWED_ORIGINS: 쉼표로 구분한 프론트 주소 목록(기본값은 로컬 개발 주소와 배포 주소).
"""
import json
import math
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

import hashlib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal

from backend.optimization import (
    InputValidationError,
    OptimizationError,
    optimize_relief_plan,
)
from backend import relief_forecast as forecaster
HORIZONS = [1, 2, 3, 4]
HUBS = ["medyka", "dorohusk", "korczowa"]

DEFAULT_ORIGINS = [
    "http://localhost:8443",
    "http://127.0.0.1:8443",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://ime-olive.vercel.app",
]
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", ",".join(DEFAULT_ORIGINS)).split(",") if o.strip()
]

app = FastAPI(title="Poland Relief API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# 데이터·모델 로딩
# --------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parents[1]
WEEKLY = pd.read_csv(ROOT_DIR / "data" / "weekly.csv", parse_dates=["week"], index_col="week")
BUNDLE = forecaster.BUNDLE
CALIBRATION = forecaster.CALIBRATION
MODEL_SHA256 = hashlib.sha256((ROOT_DIR / "models/relief_model.joblib").read_bytes()).hexdigest()

HISTORY_WEEKS = 2
# 기준 주 범위: 학습 시작 주부터 분석 범위 마지막 주까지.
FIRST_REFERENCE = pd.Timestamp("2022-06-06")  # 학습 시작 주. 그 전 급증기는 모델 범위 밖
_today = datetime.now(ZoneInfo("Europe/Warsaw")).date()
LAST_REFERENCE = max(WEEKLY.index[-1], pd.Timestamp(_today - timedelta(days=_today.weekday() + 7)))
REGIME_NOTE = (
    "새 예측모델은 최근 주간 유입을 일별 평균으로 변환해 28일을 재귀 예측합니다. "
    "유입 특징은 최근 14일(최근 2주)까지 사용합니다. "
    "분쟁 특징은 기준 주 수준과 1~2일 시차·7일 평균이며, 미래 분쟁 수준은 기준 주 수준이 유지된다고 가정합니다. "
    "실제 미래 예측 정확도는 별도 검증이 필요합니다."
)


def _reference_week(reference_date: str) -> pd.Timestamp:
    try:
        ref = pd.Timestamp(datetime.strptime(reference_date, "%Y-%m-%d"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="reference_date는 YYYY-MM-DD 형식이어야 합니다.") from exc
    if ref.weekday() != 0:
        raise HTTPException(status_code=400, detail="reference_date는 월요일이어야 합니다.")
    if ref < FIRST_REFERENCE or ref > LAST_REFERENCE:
        raise HTTPException(status_code=400, detail=f"기준 주는 {FIRST_REFERENCE.date()} ~ {LAST_REFERENCE.date()} 범위의 완료된 주여야 합니다.")
    return ref


def _history_at(ref: pd.Timestamp) -> dict:
    weeks = [ref - pd.Timedelta(weeks=k) for k in range(HISTORY_WEEKS)]
    return {hub: [float(WEEKLY.at[w, hub]) if w in WEEKLY.index and pd.notna(WEEKLY.at[w, hub]) else None
                  for w in weeks] for hub in HUBS}


def _actuals_at(ref: pd.Timestamp) -> dict:
    return {hub: [float(WEEKLY.at[ref + pd.Timedelta(weeks=h), hub])
                  if ref + pd.Timedelta(weeks=h) in WEEKLY.index else None for h in HORIZONS] for hub in HUBS}


@app.get("/")
def root():
    return {"message": "Poland Relief backend 정상 작동"}


@app.get("/health")
def health():
    return {"status": "ok", "model_available": True, "forecast_mode": "relief_model_live",
            "model_sha256": MODEL_SHA256, "model_format": BUNDLE["format"],
            "declared_training_end": str(forecaster.TRAINING_END.date())}


@app.get("/meta")
def meta():
    return {"hubs": HUBS, "first_reference": str(FIRST_REFERENCE.date()),
            "last_reference": str(LAST_REFERENCE.date()), "last_dataset_reference": str(WEEKLY.index[-1].date()),
            "accuracy": None, "regime_note": REGIME_NOTE, "model_sha256": MODEL_SHA256,
            "forecast_model": "relief_model", "effective_inflow_history_weeks": 2, "effective_conflict_history_weeks": 1,
            "interval_basis": CALIBRATION.get("interval_basis")}


@app.get("/history")
def history(reference_date: str):
    ref = _reference_week(reference_date)
    values = _history_at(ref)
    return {"reference_date": reference_date,
            "weeks": [str((ref - pd.Timedelta(weeks=k)).date()) for k in range(HISTORY_WEEKS)],
            "hub_inflow": values,
            "warning": "저장 데이터가 없는 주는 빈칸입니다. 실제 유입량을 직접 입력해주세요."
            if any(v is None for row in values.values() for v in row) else None}


class ConflictRow(BaseModel):
    model_config = {'extra': 'forbid', 'strict': True, 'allow_inf_nan': False}
    events: float = Field(default=0, ge=0)
    deaths: float = Field(default=0, ge=0)


class PredictionRequest(BaseModel):
    model_config = {'extra': 'forbid', 'strict': True, 'allow_inf_nan': False}
    reference_date: str
    hub_inflow: dict[str, list[float]] | None = None
    conflict: list[ConflictRow] | None = None


@app.post("/predict")
def predict(request: PredictionRequest):
    ref = _reference_week(request.reference_date)
    values = request.hub_inflow if request.hub_inflow is not None else _history_at(ref)
    if set(values) != set(HUBS):
        raise HTTPException(status_code=400, detail="medyka, dorohusk, korczowa 모두 입력해주세요.")
    for hub, row in values.items():
        if len(row) != HISTORY_WEEKS or any(v is None or not math.isfinite(v) or v < 0 for v in row):
            raise HTTPException(status_code=400, detail=f"{hub}의 기준 주 포함 최근 2주 실제 유입량(0 이상의 유한 숫자)이 필요합니다.")
    if request.conflict is not None and len(request.conflict) not in (1, 4):
        raise HTTPException(status_code=400, detail="분쟁정보는 기준 주 1개를 입력해주세요. 기존 4주 요청도 호환됩니다.")
    # Keep the supplied forecaster's feature formulas and four-row internal contract.
    # Its 1/2-day lag and 7-day window see only the reference week; older rows do not affect inference.
    conflict_rows = ([request.conflict[0]] * 4 if request.conflict is not None and len(request.conflict) == 1
                     else request.conflict)
    team_request = forecaster.PredictionRequest(
        reference_date=request.reference_date, inflow=[sum(values[h][i] for h in HUBS) for i in range(HISTORY_WEEKS)],
        inflow_by_hub=values, use_conflict=request.conflict is not None,
        conflict=[row.model_dump() for row in conflict_rows] if conflict_rows is not None else [])
    forecaster.validate_prediction_request(team_request)
    stored = _history_at(ref)
    complete_stored = all(v is not None for row in stored.values() for v in row)
    edited = complete_stored and any(values[h][k] != stored[h][k] for h in HUBS for k in range(HISTORY_WEEKS))
    raw = {hub: forecaster.predict_hub(hub, info, team_request, ref.to_pydatetime())
           for hub, info in forecaster.MODELS.items()}
    if any(not math.isfinite(v) or v < 0 for row in raw.values() for v in row):
        raise HTTPException(status_code=422, detail="예측 모델이 유효하지 않은 결과를 반환했습니다.")
    per_hub = {hub: [round(v) for v in row] for hub, row in raw.items()}
    total = [sum(per_hub[hub][i] for hub in HUBS) for i in range(4)]
    ratios = CALIBRATION.get("interval_log_ratio")
    intervals = [{"low": max(0, round(total[i] * math.exp(ratios[str(i+1)][0]))),
                  "high": round(total[i] * math.exp(ratios[str(i+1)][1]))} if ratios else None for i in range(4)]
    warnings = [REGIME_NOTE]
    warnings.append("입력한 기준 주 분쟁 사건 수·사망자 수를 반영했습니다." if request.conflict is not None
                    else "분쟁 입력이 없어 번들의 전형적 분쟁 수준을 가정했습니다.")
    if ref + pd.Timedelta(days=34) > pd.Timestamp(forecaster.TRAINING_END):
        warnings.append(f"제공 백엔드에 명시된 학습 종료일 {forecaster.TRAINING_END:%Y-%m-%d} 이후의 예측입니다. 학습 기간은 번들 자체에서 독립 확인되지 않았습니다.")
    if ratios:
        warnings.append("80% 구간은 팀이 제공한 총 유입 백테스트 잔차 보정값입니다. 구호소별 구간·새 모델 WAPE는 제공되지 않았습니다.")
    return {**{f"week{i+1}": v for i, v in enumerate(total)},
            "intervals": intervals, "hub_forecast": per_hub,
            "hub_intervals": {hub: [None]*4 for hub in HUBS}, "hub_actual": None if edited else _actuals_at(ref),
            "source": "relief_model_edited" if edited else "relief_model", "accuracy": None, "warning": " ".join(warnings),
            "input_provenance": {"reference_date": request.reference_date, "hub_inflow": values,
                                 "order": "reference_week_first", "history_weeks": HISTORY_WEEKS,
                                 "input_origin": "dataset_edit" if edited else "dataset_match" if complete_stored else "user_supplied",
                                 "effective_inflow_history_weeks": 2,
                                 "effective_conflict_history_weeks": 1,
                                 "conflict": [row.model_dump() for row in request.conflict] if request.conflict is not None else None,
                                 "forecast_dates": [str((ref + pd.Timedelta(weeks=h)).date()) for h in HORIZONS],
                                 "conflict_mode": "user_supplied" if request.conflict is not None else "bundle_typical_assumption"},
            "model_sha256": MODEL_SHA256,
            "forecast_method": "daily recursive 28 days, sum each 7 days"}


class TransportControls(BaseModel):
    model_config = {'extra': 'forbid', 'strict': True}
    speed_kph: float | None = Field(default=None,ge=30,le=90,allow_inf_nan=False)
    fixed_trip_cost: float | None = Field(default=None,ge=0,allow_inf_nan=False)
    cost_per_km: float | None = Field(default=None,ge=0,allow_inf_nan=False)
    cost_per_hour: float | None = Field(default=None,ge=0,allow_inf_nan=False)
    minimum_trip_cost: float | None = Field(default=None,ge=0,allow_inf_nan=False)
    overnight_cost: float | None = Field(default=None,ge=0,allow_inf_nan=False)
    allow_overnight_return: bool | None = Field(default=None,strict=True)
    assumed_intermediate_rest: bool | None = Field(default=None,strict=True)


class RoadPlanningRequest(BaseModel):
    model_config = {'extra': 'forbid', 'strict': True}
    warehouse_id: Literal['przemysl-lwowska-36', 'przemysl-wodna-11']
    truck_count: int = Field(ge=1, le=3, strict=True)
    reference_date: str
    transport_controls: TransportControls | None = None


@app.get('/road-options')
def road_options():
    from backend.road_planner import road_options as options
    return options()


@app.on_event("startup")
def warm_road_templates():
    # Parse the saved road files in the background so the first road plan is not slow.
    import threading
    from backend.road_planner import warm_geometry_cache
    threading.Thread(target=warm_geometry_cache, daemon=True).start()


class OptimizeRequest(BaseModel):
    model_config = {'extra': 'forbid', 'strict': True, 'allow_inf_nan': False}
    # JSON week keys are strings. Preserve them until the optimizer checks for
    # duplicate normalized weeks (e.g. "1" and "01") instead of overwriting.
    ml_forecast: dict[str, dict[str, float]]

    selected_site: str
    utilization_rate: float
    stay_days: int

    initial_inventory: dict[str, dict[str, float]]
    weekly_supply: dict[str, dict[str, float]]
    unit_cost: dict[str, float]

    total_budget: float

    warehouse_capacity_m3: dict[str, float]
    item_volume_m3: dict[str, float]
    priority: str = "fairness"
    logistics: dict[str, Any] | None = None
    road_planning: RoadPlanningRequest | None = None


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
        "priority": request.priority,
    }
    try:
        logistics, road_information = request.logistics, None
        if request.road_planning is not None:
            from backend.road_planner import build_ui_logistics
            logistics, road_information = build_ui_logistics(logistics, request.road_planning.model_dump(exclude_none=True), request.selected_site)
        result = optimize_relief_plan(
            ml_forecast=request.ml_forecast,
            user_input=user_input,
            item_volume_m3=request.item_volume_m3,
            logistics=logistics,
        )
        if road_information is not None:
            result['road_scenario'] = road_information
        return result
    except InputValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OptimizationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        print("OPTIMIZATION ERROR:", repr(e))
        raise HTTPException(status_code=500, detail=str(e))


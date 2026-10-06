"""T3/T4: 주간 예측 후보 모델과 구간 보정.

표기: 기준 주 t = 가장 최근에 끝난 주(앱의 '이번 주'). h = 1..4 주 뒤를 예측한다.
모든 모델은 t 주까지의 값만 사용한다(누수 없음).
"""
from datetime import date
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

HUBS = ['medyka', 'dorohusk', 'korczowa']
HORIZONS = [1, 2, 3, 4]
QUANTILES = (0.1, 0.5, 0.9)
TRAIN_START = pd.Timestamp('2022-06-06')  # 개전 직후 급증기(2022-03~05)는 동역학이 달라 학습에서 제외

EASTER = {  # (가톨릭, 정교회)
    2022: ('2022-04-17', '2022-04-24'), 2023: ('2023-04-09', '2023-04-16'),
    2024: ('2024-03-31', '2024-05-05'), 2025: ('2025-04-20', '2025-04-20'),
    2026: ('2026-04-05', '2026-04-12'),
}


# ---------------------------------------------------------------- 기준선
def naive_last(y: pd.Series, t: int, h: int) -> float:
    return float(y.iloc[t])


def wavg3(y: pd.Series, t: int) -> float:
    """최근 3주 가중평균(3:2:1)."""
    return float((3 * y.iloc[t] + 2 * y.iloc[t - 1] + y.iloc[t - 2]) / 6)


def seasonal(y: pd.Series, t: int, h: int) -> float:
    """계절 기준선: 최근 3주 가중평균 × 작년 같은 시기의 증감률.
    작년 목표 주는 앞뒤 1주를 포함한 3주 평균으로 잡음을 줄인다."""
    if t - 54 < 0:
        return wavg3(y, t)
    base_ly = wavg3(y, t - 52)
    j = t + h - 52
    target_ly = float(y.iloc[j - 1:j + 2].mean())
    if base_ly <= 0:
        return wavg3(y, t)
    return wavg3(y, t) * target_ly / base_ly


# ---------------------------------------------------------------- 캘린더 피처
def _easter_days(d: pd.Timestamp) -> tuple[int, int]:
    cat, ort = (pd.Timestamp(x) for x in EASTER[d.year])
    mid = d + pd.Timedelta(days=3)
    return (mid - cat).days, (mid - ort).days


def calendar_features(week: pd.Timestamp) -> dict:
    days = pd.date_range(week, periods=7)
    md = {(x.month, x.day) for x in days}
    woy = week.isocalendar().week
    ec, eo = _easter_days(week)
    return {
        'woy_sin': np.sin(2 * np.pi * woy / 52.18), 'woy_cos': np.cos(2 * np.pi * woy / 52.18),
        'has_dec25': int((12, 25) in md), 'has_jan1': int((1, 1) in md), 'has_jan7': int((1, 7) in md),
        'easter_cat_days': float(np.clip(ec, -21, 21)), 'easter_ort_days': float(np.clip(eo, -21, 21)),
        'days_to_sep1': float(np.clip((pd.Timestamp(week.year, 9, 1) - week).days, -30, 60)),
    }


# ---------------------------------------------------------------- 직접 다중시점 GBM
FEATURES = ['h', 'hub_medyka', 'hub_dorohusk', 'hub_korczowa', 'log_level',
            'd1', 'd2', 'd3', 'dev4', 'dev8', 'vol8',
            'ly_ratio', 'ly_ratio_h', 'ly_level_ratio',
            'woy_sin', 'woy_cos', 'has_dec25', 'has_jan1', 'has_jan7',
            'easter_cat_days', 'easter_ort_days', 'days_to_sep1']
CONFLICT_FEATURES = ['log_events', 'log_deaths', 'events_chg4']


def _log(x):
    return np.log1p(np.maximum(x, 0))


def make_row(y: pd.Series, t: int, h: int, hub: str, weeks: pd.DatetimeIndex,
             conflict: pd.DataFrame | None = None) -> dict:
    ly = _log(y.values)
    r = {'h': h, 'log_level': ly[t]}
    for k in HUBS:
        r[f'hub_{k}'] = int(k == hub)
    r['d1'], r['d2'], r['d3'] = ly[t] - ly[t - 1], ly[t] - ly[t - 2], ly[t] - ly[t - 3]
    r['dev4'] = ly[t] - ly[t - 3:t + 1].mean()
    r['dev8'] = ly[t] - ly[t - 7:t + 1].mean()
    r['vol8'] = np.std(np.diff(ly[t - 8:t + 1]), ddof=1)
    if t - 54 >= 0:
        base_ly = np.log1p(wavg3(y, t - 52))
        j = t + h - 52
        r['ly_ratio'] = np.log1p(float(y.iloc[j - 1:j + 2].mean())) - base_ly   # 작년 같은 시기 증감(로그)
        r['ly_ratio_h'] = ly[j] - ly[t - 52]
        r['ly_level_ratio'] = np.log1p(wavg3(y, t)) - base_ly                    # 전년 대비 수준
    else:
        r['ly_ratio'] = r['ly_ratio_h'] = r['ly_level_ratio'] = np.nan
    r.update(calendar_features(weeks[t] + pd.Timedelta(weeks=h)))  # 데이터 끝을 넘는 주도 계산 가능
    if conflict is not None:
        ev = conflict['events'].values
        de = conflict['deaths'].values
        r['log_events'] = _log(ev[t])
        r['log_deaths'] = _log(de[t])
        r['events_chg4'] = _log(ev[t]) - _log(np.nanmean(ev[t - 3:t + 1]))
    return r


class DirectGBM:
    """3개 구호소·4개 시점을 한 모델로 학습. 타깃 = log(y[t+h]) - log(y[t])."""

    def __init__(self, use_conflict=False, params=None, drop=()):
        self.use_conflict = use_conflict
        self.params = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                           min_samples_leaf=20, l2_regularization=1.0)
        if params:
            self.params.update(params)
        self.features = [f for f in FEATURES + (CONFLICT_FEATURES if use_conflict else []) if f not in drop]

    def training_frame(self, W: pd.DataFrame, t_origin: int) -> pd.DataFrame:
        """기준 주 t_origin 시점에 관측된 (t, h) 쌍만 사용: t + h <= t_origin."""
        rows = []
        weeks = W.index
        start = max(8, weeks.get_indexer([TRAIN_START], method='bfill')[0])
        conf = W[['events', 'deaths']] if self.use_conflict else None
        for hub in HUBS:
            y = W[hub]
            for t in range(start, t_origin):
                for h in HORIZONS:
                    if t + h > t_origin:
                        continue
                    if self.use_conflict and np.isnan(W['events'].iloc[t]):
                        continue
                    r = make_row(y, t, h, hub, weeks, conf)
                    r['target'] = _log(y.iloc[t + h]) - _log(y.iloc[t])
                    rows.append(r)
        return pd.DataFrame(rows)

    def fit(self, W: pd.DataFrame, t_origin: int):
        df = self.training_frame(W, t_origin)
        X, yv = df[self.features], df['target']
        self.models = {q: HistGradientBoostingRegressor(loss='quantile', quantile=q, random_state=0,
                                                         **self.params).fit(X, yv) for q in QUANTILES}
        return self

    def predict(self, W: pd.DataFrame, t: int) -> dict:
        """{hub: {h: {q: 값}}}"""
        conf = W[['events', 'deaths']] if self.use_conflict else None
        out = {}
        for hub in HUBS:
            y = W[hub]
            rows = [make_row(y, t, h, hub, W.index, conf) for h in HORIZONS]
            X = pd.DataFrame(rows)[self.features]
            preds = {q: self.models[q].predict(X) for q in QUANTILES}
            out[hub] = {}
            for i, h in enumerate(HORIZONS):
                qs = sorted(preds[q][i] for q in QUANTILES)  # 분위수 교차 방지
                out[hub][h] = {q: float(np.expm1(_log(y.iloc[t]) + v)) for q, v in zip(QUANTILES, qs)}
        return out


# ---------------------------------------------------------------- 구간 보정
def conformal_interval(point: float, past_log_resid: np.ndarray, alpha=0.2, min_n=20):
    """로그 잔차(실제 − 예측)의 경험 분위수로 80% 구간을 만든다(과거 잔차만 사용)."""
    r = past_log_resid[~np.isnan(past_log_resid)]
    if len(r) < min_n:
        return np.nan, np.nan
    lo_q, hi_q = np.quantile(r, [alpha / 2, 1 - alpha / 2])
    lp = np.log1p(point)
    return float(np.expm1(lp + lo_q)), float(np.expm1(lp + hi_q))


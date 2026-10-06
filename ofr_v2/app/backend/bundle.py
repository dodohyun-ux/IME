"""
예측에 필요한 모든 것을 models/relief_model.joblib 파일 하나로 관리합니다.

    {
      "format": "poland-relief-bundle/1",
      "created": "...",
      "sklearn_version": "...",
      "hubs": {"medyka": {"crossing": ..., "model": 중앙값 모델}, ...},
      "calibration": {...}   # backend/calibrate.py, backend/backtest.py 가 갱신
    }

학습된 지점별 모델(.joblib)에서 새로 묶을 때만 이 스크립트를 실행합니다.
(모델을 재학습했을 때)

사용법 (poland_relief_app 폴더에서):
    python -m backend.bundle model_sources
    python -m backend.bundle model_sources --calibration model_sources/calibration.json

묶은 뒤에는 보정값을 다시 만드세요:
    python -m backend.calibrate 분쟁데이터.csv 폴란드국경통과-일일.xlsx
    python -m backend.backtest 분쟁데이터.csv 폴란드국경통과-일일.xlsx --write-intervals
"""

from pathlib import Path
from datetime import datetime
import argparse
import json
import sys

import joblib
import sklearn


# sklearn joblib compatibility
try:
    import sklearn._loss._loss as sklearn_loss
    sys.modules["_loss"] = sklearn_loss
except Exception:
    pass


ROOT_DIR = Path(__file__).resolve().parents[1]
BUNDLE_FILE = ROOT_DIR / "models" / "relief_model.joblib"

BUNDLE_FORMAT = "poland-relief-bundle/1"

HUB_CROSSINGS = {
    "medyka": "Medyka – Szeginie",
    "dorohusk": "Dorohusk – Jagodzin",
    "korczowa": "Korczowa – Krakowiec",
}

HUB_MODEL_FILES = {
    "medyka": "model_Medyka_-_Szeginie.joblib",
    "dorohusk": "model_Dorohusk_-_Jagodzin.joblib",
    "korczowa": "model_Korczowa_-_Krakowiec.joblib",
}


def load_bundle(path=BUNDLE_FILE):

    if not path.exists():
        raise RuntimeError(
            f"모델 파일을 찾을 수 없습니다: {path} "
            "(python -m backend.bundle 로 생성)"
        )

    bundle = joblib.load(path)

    if bundle.get("format") != BUNDLE_FORMAT:
        raise RuntimeError(f"지원하지 않는 모델 파일 형식입니다: {path}")

    return bundle


def save_bundle(bundle, path=BUNDLE_FILE):

    bundle["updated"] = datetime.now().isoformat(timespec="seconds")

    joblib.dump(bundle, path, compress=3)


def update_calibration(changes, drop=()):
    """번들 안의 calibration 일부만 갱신"""

    bundle = load_bundle()

    calibration = dict(bundle.get("calibration") or {})

    for key in drop:
        calibration.pop(key, None)

    calibration.update(changes)

    bundle["calibration"] = calibration

    save_bundle(bundle)


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "models_dir",
        help="지점별 학습 모델(.joblib)이 있는 폴더",
    )
    parser.add_argument(
        "--calibration",
        help="함께 넣을 calibration.json (없으면 calibrate.py 로 따로 생성)",
    )
    args = parser.parse_args()

    hubs = {}

    for hub, filename in HUB_MODEL_FILES.items():

        quantile_models = joblib.load(Path(args.models_dir) / filename)

        # 예측구간은 백테스트 오차로 만들므로 중앙값 모델만 사용
        hubs[hub] = {
            "crossing": HUB_CROSSINGS[hub],
            "model": quantile_models[0.5],
        }

    calibration = None

    if args.calibration:
        calibration = json.loads(
            Path(args.calibration).read_text(encoding="utf-8")
        )

    bundle = {
        "format": BUNDLE_FORMAT,
        "created": datetime.now().isoformat(timespec="seconds"),
        "sklearn_version": sklearn.__version__,
        "hubs": hubs,
        "calibration": calibration,
    }

    BUNDLE_FILE.parent.mkdir(exist_ok=True)
    save_bundle(bundle)

    print("저장:", BUNDLE_FILE, f"({BUNDLE_FILE.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()

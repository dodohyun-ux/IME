# SETUP

2026-10-06 활성 예측 모델은 `ofr_v2/app/models/relief_model.joblib`입니다.
먼저 `python scripts/verify_forecast_bundle.py`로 실제 객체(해시)를 확인합니다.
`weekly_gbm.joblib`는 새 앱 실행에 필요하지 않습니다. 기존 `verify_repository.py`는
과거 모든 자산의 보존 여부를 검사하므로 현재 활성 모델 점검과 구분합니다.
UI·API 입력은 기준 주 포함 정확히 2주입니다. 오래된 8주 API 요청은 거절됩니다.
UI는 기준 주 분쟁 사건 수·사망자 수도 함께 입력해야 예측이 가능합니다.
분쟁은 우크라이나 전체 주간 합계이며 모르는 값은 빈칸으로 둡니다. 예시 버튼은 두 값도 채웁니다.
CSV 업로드 대신 데이터 입력 화면의 `예시 값 입력` → `향후 4주 유입량 예측`을 누릅니다.
구호품 계획 화면에서 `예시 값 입력` → `최적화 결과 확인`을 누르면 추가 입력 없이 시연됩니다.
예시는 가상 값이며 실제 운영 자료로 사용하지 않습니다. 직접 입력도 가능합니다.
실행/연결 검증은 `python scripts/smoke_backend.py`와
`python scripts/validate_forecast_integration.py --output ofr_v2/results/two_week_validation_20261006/integration`입니다.
회고 예측 평가: `python scripts/validate_two_week_forecast.py`.
고정 배차 스트레스: 연결 검증 후 `python scripts/validate_fixed_dispatch_sensitivity.py`.
현재 결과와 한계는 `ofr_v2/results/two_week_validation_20261006/검증보고서.md`를 참고하세요.

## 필수 도구

- Git 2.x
- Git LFS
- Python 3.11 이상 권장
- Node.js 20 이상 및 npm

학습된 joblib 모델은 scikit-learn 1.8.0으로 저장됐다. `ofr_v2/app/requirements.txt`가
해당 버전을 고정한다.

## 저장소 받기

```bash
git lfs install
git clone https://github.com/qkrrbeh071/refugee_project.git
cd refugee_project
git lfs pull
python3 scripts/verify_forecast_bundle.py
```

Private 저장소이므로 GitHub 인증이 필요하다. LFS 객체를 받지 않으면 ZIP, joblib,
XLSX, 대용량 ACLED CSV가 작은 포인터 파일로 남고 앱이 실행되지 않는다.

## 백엔드 환경

```bash
cd ofr_v2/app
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

확인:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/meta
```

다른 프론트 도메인을 허용하려면 쉼표로 구분한다.

```bash
export ALLOWED_ORIGINS="http://localhost:5173,https://frontend.example.com"
```

## 프론트엔드 환경

```bash
cd ofr_v2/app/frontend
npm ci
cp .env.example .env.local
```

`.env.local`:

```dotenv
VITE_API_BASE=http://127.0.0.1:8000
```

실행과 빌드:

```bash
npm run dev
npm run build
```

`.env.local`은 Git에 포함되지 않는다. 새 변수가 필요하면 비밀값 없이
`.env.example`도 함께 갱신한다.

## 저장 결과 확인

긴 재학습 없이 현재 결과를 확인할 수 있다.

```bash
cat ofr_v2/results/validation_metrics.txt
cat ofr_v2/results/holdout_metrics.txt
sed -n '1,220p' ofr_v2/results/model_selection.md
```

## 교체 이전 주간 연구 파이프라인 재실행

아래 파이프라인은 과거 주간 모델용입니다. 제공된 새 relief_model을 재학습하는 코드가 아닙니다.
`ofr_v2`에서 실행한다.

```bash
python3 pipeline/backtest.py
python3 pipeline/evaluate.py validation
python3 pipeline/evaluate.py holdout
python3 pipeline/run_simulation.py
python3 pipeline/train_final.py
```

백테스트는 수십 분 걸릴 수 있다. `evaluate.py holdout` 결과를 보고 모델 구조나
하이퍼파라미터를 바꾸지 않는다.

## 원천 데이터부터 다시 만들기

루트의 `폴란드국경통과-일일.xlsx`와 `분쟁데이터 (2).csv`가 Git LFS에서
내려받아졌는지 확인한 뒤 다음을 실행한다.

```bash
cd ofr_v2
python3 pipeline/data.py
```

파일 해시는 `ASSET_INVENTORY.md`에 있다. 공식 출처, 다운로드 날짜,
라이선스는 아직 불완전하므로 확인 후 인벤토리를 보완한다.

## AI 오케스트레이터

특정 개발 작업을 4역할 워크플로로 실행하려면 `TASK.md`에 목표와 합격 기준을
작성하고 깨끗한 Git 상태에서 다음을 실행한다.

```bash
python3 orchestrator.py
```

`orchestrator_config.json`에서 역할, 제한시간, 검증 명령을 설정한다. 역할 실행 중에는
`AGENTS.md`/`CLAUDE.md`에 적힌 보호 경로를 수정하지 않는다.


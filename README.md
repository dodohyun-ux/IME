# 최신 최종 최적화 모델·연결 백엔드 — 2026-10-07

현재 저장소의 구호품 조달·재고·리드타임·유통기한·폐기·도로 경로·차량 배차 엔진과
이를 UI에 연결하는 FastAPI 소스입니다. 공식 도로 원자료, 근거 문서, 검증 코드/결과를 포함합니다.
팀원 제공 relief_model.joblib는 연결 실행에 필요한 의존성으로 원본 그대로 포함했습니다.
이번 내보내기에서 예측 가중치·추론식·최적화 수식을 변경하거나 재학습하지 않았습니다.
BACKEND_VERSION.json / BACKEND_manifest.json에 기준 커밋과 파일 SHA256을 기록했습니다.

## 설치 (Python 3.11 이상 권장)

이 README가 있는 REFUGEE_FINAL_20261007 폴더에서 PowerShell로 실행합니다.
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r ofr_v2/app/requirements.txt
.\.venv\Scripts\python.exe -m pip install pytest httpx
.\.venv\Scripts\python.exe scripts/verify_forecast_bundle.py
```
모델은 scikit-learn 1.8.0으로 저장돼 requirements.txt가 해당 버전을 고정합니다.

## API 실행

```powershell
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:ALLOWED_ORIGINS='http://127.0.0.1:8443,http://localhost:8443'
Set-Location ofr_v2/app
..\..\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
UI ZIP을 동일한 공통 폴더에 풀고 UI_README.md대로 별도 터미널에서 UI를 실행합니다.
http://127.0.0.1:8000/health 및 /docs 로 API를 확인할 수 있습니다.

## 최적화만 사용

```python
from optimization import optimize_relief_plan, example_inputs
forecast, inputs, volumes = example_inputs()
result = optimize_relief_plan(forecast, inputs, volumes)
```
운영 입력 계약은 코드/예제 JSON을 참고하세요.
도로 배차 예제는 아래 검증 스크립트 또는 ofr_v2/examples/road_network_request.json입니다.
출력 truck_plan에 차량·품목별 적재·왕복 경로·시간·비용이 포함됩니다.

## 전달본 실행 검사 (공통 폴더에서)

```powershell
.\.venv\Scripts\python.exe scripts/smoke_backend.py
.\.venv\Scripts\python.exe scripts/verify_road_network.py
.\.venv\Scripts\python.exe scripts/verify_poland_facility_routes.py
.\.venv\Scripts\python.exe -m pytest ofr_v2/tests -q
```
UI가 없는 경우 마지막 명령은 Python 검사만 수행하며 Node UI 검사는 UI ZIP에 있습니다.

## 증거와 범위

최적화 최신 검토는 ofr_v2/results/final_review_20261006/의 optimizer/transport 및 FINAL_REVIEW.md,
최신 UI·분쟁 연결은 ofr_v2/results/conflict_ui_20261007/report.md를 읽으세요.
모델 검증 124/124, 운송 시나리오 24/24는 선언된 조건의 계산 검증입니다.
실제 운송 기록은 0건이고 operational_ready=false입니다.
단일 창고와 선택 구호소 한 곳의 계획이며 세 구호소 공유 자원을 동시에 최적화하지 않습니다.
최적성은 수집한 도로와 생성한 후보 경로·출발 시각 안에서의 결과입니다.
전국 도로·실시간 교통·시설 현재 운영/통행 적합성·실제 배송 시간/지급비용은 검증되지 않았습니다.
과거 WAPE 20.15% 평가는 분쟁을 전형적 상수로 둔 회고평가이며 새 실측 분쟁 입력의 정확도는 아닙니다.
과거 결과 폴더는 날짜별 증거이며 모두 현재 엔진의 성적표로 해석하면 안 됩니다.
입력은 유입 2주 + 기준 주 분쟁 1주이고 미래 분쟁은 기준 주 수준이 유지된다고 가정합니다.

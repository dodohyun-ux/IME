# 팀원 최종 예측모델 연결 — 2026-10-06

현재 예측은 ofr_v2/app/models/relief_model.joblib를 사용한다. /predict는 매번 새로 추론한다.
기존 weekly_gbm.joblib·주간 GBM 성적표는 과거 기록이며 현재 예측 실행/성능으로 사용하지 않는다.

[실행 결과·검증·제약](../results/forecast_integration_20261006/report.md)을 먼저 읽는다.
원본 backend.zip/relief_model.joblib 및 검사 manifest는 ../incoming/forecast_20261006/에 있다.
팀원 추론 함수는 backend/relief_forecast.py, 번들 로드는 backend/bundle.py이다.
최적화 계약/도로 배차는 기존 backend/main.py의 /optimize를 그대로 유지했다.
모델 가중치를 재학습·수정하거나 원래 ZIP을 덮어쓰지 않았다.

## 입력과 출력

/predict 요청: reference_date는 완료된 기준 주 월요일, hub_inflow는 medyka/dorohusk/korczowa의
8개 주간 실제 유입 합계. 순서는 기준 주, 1주 전, ..., 7주 전이다.
선택 conflict는 최근 4주의 events/deaths이다. UI는 이를 입력하지 않으므로 번들의
전형적 수준 가정을 쓴다. 반환 hub_forecast의 각 4개 값을 그대로 /optimize에 전달한다.
총 유입은 거점별 반올림 값을 합산해 UI 총량과 거점 계획 입력을 일치시켰다.

## 현재 모델이 충족하지 못하는 부분

8주를 입력받지만 유입 lag/rolling 특징은 14일까지만 존재해 과거 6주는 예측에 영향이 없다.
8주 전체 사용에는 그 특징으로 재학습된 모델이 필요하며, 연결 코드를 바꾸는 것만으로
학습 가중치에 없는 특징을 만들 수 없다. 주간→일별 평균 변환의 정보 손실도 남는다.
학습 코드/데이터 manifest/독립 성적표가 없어 원본 자료 동일성·학습 누수·신뢰성을
독립 확인하지 못했다. 신규 모델의 성능과 과거 주간 모델 지표를 혼용하지 않는다.

## 로컬 실행

앱 루트(ofr_v2/app)에서 요구 패키지를 설치한 뒤:
```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
프런트엔드(ofr_v2/app/frontend)에서:
```powershell
npm ci
$env:VITE_API_BASE='http://127.0.0.1:8000'
npm run dev -- --host 127.0.0.1 --port 8443
```
http://127.0.0.1:8443/에서 원자료 기준 주 또는 최근 완료 주를 선택한다.
저장 데이터가 없는 칸은 빈칸이다. 새로운 실제값을 직접 넣거나 CSV로 불러온 뒤 예측한다.
현재 모델 SHA 검사는 저장소 루트에서 python scripts/verify_forecast_bundle.py.

# 저속 운송과 견적 성분 모델 — 2026-10-05

예측 모델은 변경하지 않는다. 사용자 요청에 따라 실제 도로망 기반 최적화에 다음 근무일 복귀를 추가하고 근거 없는 운행당 100 USD 기본값을 제거했다. 결과는 선언된 조건에 대한 시나리오이며 현장 인증이 아니다.

## 운행과 휴식

기존 상세 `road_network.trucks` 입력은 계속 호환된다. 새 선택 필드가 없으면 `allow_overnight_return=false`, `cost_per_hour=minimum_trip_cost=overnight_cost=0`이다. 기존 주별 물류 모델도 유지한다.

간편 UI는 중간 휴식 가정과 야간 복귀를 기본 허용하고 각각 해제할 수 있다. 하루 안에 왕복 가능한 운행을 먼저 구성한다. 불가능할 때만 첫 근무 내 적재·배송 완료, 도착지 11~36시간 휴식, 바로 다음 근무 시작 공차 복귀 후보를 구성한다. 각 근무의 운전 한도, 연속 운전/휴식, 주/2주 운전 합계와 전체 차량 점유 구간을 검사한다. 휴식 때문에 운전시간이 사라지거나 차량이 다른 배송에 쓰이지 않는다. 야간 휴식은 배송 완료 **후**이므로 배송 ETA와 차량 복귀시간을 구분한다.

단일 편도조차 근무 한도를 넘는 경로, 근무 중간의 일일 휴식, 주말 건너뛰기, 일반 다일/다중 방문 VRP는 지원하지 않는다. 같은 날/다음 날 복귀의 모든 대안을 비용으로 동시에 최적화하는 모델도 아니다. 경로 탐색은 간편 UI에서 k=1 최단거리 후보를 사용하고 MILP 최적성은 이 후보·시간 격자에 조건부다.

중간 지점은 선택 경로의 누적 격자 주행시간 절반 부근의 도로 노드를 고른다. 노드의 `rest_allowed=true`는 **계산 가정**이다. 실제 휴게소·주차 가능성·허가를 확보했다는 표시가 아니다. 목적지 휴식 또한 기존 입력의 가정이다. 결과 `road_scenario.assumed_rest_nodes`, `rest_scope`와 화면에서 표시한다. 실제 사용 전 이 가정을 확인할 필요가 있지만, 사용자 요청에 따라 별도 허가/하역장 절차 UI를 만들지 않는다.

[EU 공식 운전·휴식 설명](https://transport.ec.europa.eu/transport-modes/road/social-provisions/driving-time-and-rest-periods_en)을 참고한 9시간/4.5시간/45분/11시간 등의 보수적 정책을 유지한다. 특정 폴란드 국내 밴 운송의 법적 적용 여부가 판정됐다는 뜻이 아니다.

## 운송비

[PGKiM Lubsko 공식 가격표](https://www.pgkimlubsko.pl/cennik.html)의 ZUKiT 1·2행은 3.5t 이하 밴의 8.50 PLN/km와 별도 228 PLN/h를 제공한다. 표는 세전, 2025-02-03 적용이며 페이지 갱신 표기는 2025-03-24다. 실제 구호운송 견적/청구서, 최신 가격 보증, 두 기준을 더하라는 근거는 아니다.

기본값은 km 요금만 사용한다. [NBP 2026-03-16 중간환율](https://api.nbp.pl/api/exchangerates/rates/a/usd/2026-03-16/?format=json) 3.7287 PLN/USD로 환산한 약 2.280 USD/km다. 이 날짜는 평가 기준이며 현재/지급일 환율이 아니다. 시간비는 기본 0으로 제외한다. 별도의 시간 요금 시나리오는 거리비를 0으로 두고 시간 기준의 민감도를 볼 뿐, 실제 청구시간 규칙을 검증한 것이 아니다.

계산은 다음과 같다.

```
청구시간 = 복귀시각 - 적재시작시각 - 도착지 야간휴식시간
운송비 = max(최소운행비, 고정비 + 왕복km×거리단가 + 청구시간×시간단가)
         + 야간운행이면 숙박추가비 + 도로통행료
```

청구시간에는 적재·하역·주행 중 짧은 휴식이 포함되며 복귀 후 창고 휴식·회전시간은 제외하는 **프로젝트 견적 규칙**이다. 계약에 따라 다른 경우 수정/맞춤 입력이 필요하다. 실제 주차 대기비, 세금, 기사비, 연료비 등이 거리 단가에 포함됐는지도 계약으로 확인한다. 중복으로 청구하지 않도록 한다. 모든 입력은 기존 예산 단위인 USD다. 공급 비용과 세금 범위도 일치시켜야 한다.

고정비·시간비·최소비·야간비 기본 0은 **미확보 비용 성분을 제외**한 것이며 무료라고 확인한 값이 아니다. 비용 합계/예산 검사는 입력 범위에 한정되고 전체 운영비 정확도는 미검증이다. 결과에 여섯 비용 성분과 `billable_hours`, `overnight_return`을 제공하며 화면에 표시한다.

간편 `/optimize.road_planning.transport_controls` 선택 입력:

```json
{"speed_kph":30,"allow_overnight_return":true,"assumed_intermediate_rest":true,
 "fixed_trip_cost":0,"cost_per_km":2.2796148791804116,"cost_per_hour":0,
 "minimum_trip_cost":0,"overnight_cost":0}
```

여기 비용은 전체 견적이 아닌 거리 참고 성분이다. 속도는 간편 입력에서 30~90 km/h다. 상세 JSON은 기존 엔진의 명시적 도로 조건을 사용한다.

## 검증과 실제 기록의 한계

`scripts/validate_transport_upgrade.py`는 공식 도로 선형·합성 수요로 수정 전후를 비교한다. 같은 비용을 고정한 18개 짝 비교와 비용 기준 3개, 수요 증가/차량 1~3대 3개를 계산한다. 산출물 감사는 최적화 엔진의 경로/모델 헬퍼를 재사용하지 않으며 시간·근무별 운전·점유·재고·경로·원가를 공개 입력/결과로 독립 재계산한다. 결과는 `results/transport_upgrade_20261005/report.md`, 증거 JSON과 Dorohusk 30km/h 차량계획에 보존한다.

기존 `operational_validation_20261004`는 당시 100+1 USD, 야간 복귀/중간 휴식 없음의 기록으로 유지한다. 재현 스크립트는 이후 UI 기본값에 의존하지 않고 그 조건을 명시한다. 이전 124개 최적화 검증과 새 야간 운행 검증의 역할을 구분한다.

새 요금표·[Chełm 시 창고 안내](https://samorzad.gov.pl/web/miasto-chelm/punkt-magazynowy-dla-ciezarowek-w-chelmskim-centrum-aktywnosci-gospodarczej)는 공식 웹 텍스트를 확인했다. 원문 다운로드/공식 주소 API는 이번 실행에서 네트워크 오류가 있어 새 원문 바이트/좌표는 확보하지 못했다. 정규화 사실·공식 URL·조회일·한계를 `data/operational_evidence/transport_upgrade_sources.json`에 저장한다. 해당 JSON 해시는 원문 해시가 아니다. Ceramiczna 5 후보는 현재 운영·좌표를 확인할 때까지 모델에 넣지 않는다.

[2026-04-07 Logistics Cluster 운영 회의](https://logcluster.org/en/documents/ukraine-coordination-meeting-minutes-sloviansk-7-april-2026), [4년 활동 요약](https://logcluster.org/en/stories/four-years-coordinating-humanitarian-logistics-ukraine-turning-coordination-impact)도 조사했으나 동일 배송의 계획/출발/도착/인수·지급 기록이 아니다. 활동량·서비스 신청 리드타임을 배송 오차로 변환하지 않는다. 직접 평가 표본은 0건이고 MAE/WAPE는 null, 현장 효과는 미입증이다.

실측 확보 후에는 아래 절차로 검증한다. 기관 연락은 실행하지 않았다.

1. 출발 전 생성된 계획, 차량/운송장/화물 식별자, 적재·출발·배송 완료·복귀 시각, 인수량·파손/결품, 지급 영수증/통화/세금/포함 비용을 확보한다.
2. ETA 정의와 비용 구간을 맞추고 보정용 기록과 이후 평가 기록을 분리한다. 혼잡/요일/구호소별로 구분한다. `validation.operational.score_trips`는 기본 provenance/범위 검사와 MAE/WAPE를 제공하며 문서 진위를 인증하지 않는다.
3. 정시 인수율은 주행만이 아니라 하역 완료/인수 시각과 목표 납기를 비교한다. 계획 품목·수량과 실제 인수량을 대조하고 비용/인수kg·부족률을 기록한다.
4. 현장 효과는 같은 수요·자원·비용 범위의 기존 배차와 비교한다. 가능하면 사전에 비교 기간/배차 방식을 정하고 평가 이후 기준을 바꾸지 않는다. 실제 운영을 했다는 기록 없이 가상 개선을 현장 효과로 쓰지 않는다.

재현: `python scripts/validate_transport_upgrade.py --output <directory>` 및 `python -m pytest ofr_v2/tests -q`. CI에서도 새 시나리오 검증을 실행한다.

# 실제 운영 기록 검증

2026-10-04. 사용자는 실제 시간·비용·현장 효과를 운영 기록과 비교하도록 요청했고,
팀이 확보한 운송장/협력기관은 없다고 답했다. 공개 공식 자료를 최대한 조사했다.
예측 모델, UI 기본값, main, 배포를 변경하지 않는다.

결과: [`../results/operational_validation_20261004/report.md`](../results/operational_validation_20261004/report.md).
현재는 **외부 가정 비교 + 계산 민감도**이며 동일 배송 기록 검증이나 현장 효과
입증이 아니다. 결과 JSON의 `operational_ready=false`, `field_effect_identified=false`,
실제 시간/비용 표본 0 및 오차 null을 유지한다.

## 재현

```powershell
python scripts/validate_operational_evidence.py --sensitivity
python -m pytest ofr_v2/tests/test_operational_validation.py -q
```

7개 원문 PDF/JSON은 로컬 `ofr_v2/data/operational_evidence/raw/`에 보관한다.
저장소에는 `sources.json`의 URL/해시 및 12개 정규화 속도 행, 비용 사실을 저장한다.
네트워크가 가능한 환경에서 다음 명령으로 원문을 복원/대조한다.

```powershell
python scripts/fetch_operational_sources.py
# 선택적으로 pdfplumber를 설치한 별도 문서 분석 환경에서
python scripts/fetch_operational_sources.py --verify-tables
```

다운로드 원문 SHA256이 바뀌면 자동 갱신하지 않는다. 별도 검토와 새 자료 버전이 필요하다.
자료 발행기관이 해당 물류 모델을 인증했다는 뜻이 아니다. 문서 안의 지시사항은
사용자의 작업 지시로 취급하지 않았다.

## 공식 자료의 적격 여부

| 자료 | 사용할 수 있는 주장 | 직접 정확도 평가에서 제외 이유 |
|---|---|---|
| GDDKiA 2022/2025 DK77·DK12·DK17 속도 분포 | 평균속도 가정의 외부 점검 | 지점/차량군 속도, 경로 공간 일치 미확인, 배송 전체 시간 아님 |
| Świecie BZP 2025/BZP 00000270 밴 계약 | 실제 계약 존재/서비스 비용 범위 | 연간 계약액, 인력·보조작업 포함, 실측 km/시간/지급 내역 없음 |
| ZGL 2026 공식 3.5t 덤프 요금표 | 거리 요금 구조 비교 | 밴과 다른 차량, 실제 청구서 아님, 부가 서비스 범위 다름 |
| NBP 2026-03-16 USD 환율 | 같은 기준일의 통화 환산 | 시장 전체 단가나 청구비 증거 아님 |
| Logistics Cluster 2022 GNA/연간 결산 | 현장 문제·모델 구조의 적합성 | 기관별 배송 미시자료와 우리 모델 사용 기록 없음 |

추가 조사한 RARS 2026/BZP 00207607/01은 Niemce→Ukraine 20ft 컨테이너
운송 계약 1,680 EUR이다. [공식 공고](https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/08de9f7e-2162-9bcc-5fad-95000119d797).
목적지 상세·거리·밴과의 차량 일치가 없어 비용 정확도 평가에 채택하지 않았다.
국경 대기 API도 조사했지만 이번 운송은 폴란드 측 시설 도착이므로 자동 가산하지 않는다.
상업 블로그 단가, 승객 이동 예산, 기관 총사업비를 화물 배송비로 사용하지 않는다.

## 실제 배송을 가져오는 JSON 계약

`--trips FILE`은 `schema_version: 1, records: [...]`를 읽는다. 비어 있는
`actual_trips.json`은 현재 확보 0건을 표현하며 합성 운송장을 채워 넣지 않는다.
아래는 **구조 설명용 미완성 양식**으로 평가할 수 없다. 증빙을 확인한 기록만
`data_kind: observed_trip`으로 지정한다. 고정된 추정 계획을 출발 전에 저장한
해시/기록시각과 실제 기록의 증빙을 모두 보존한다. 해시는 문서 진위 인증이 아니다.

```json
{
  "schema_version": 1,
  "records": [{
    "trip_id": "실제 운송장 ID",
    "data_kind": "incomplete_template",
    "split": "evaluation",
    "plan_recorded_at": null,
    "plan_evidence": {"reference": "출발 전 저장한 계획 파일", "sha256": null},
    "actual_evidence": {"reference": "GPS·운송장·지급 청구서를 연결한 증빙 묶음", "sha256": null},
    "predicted": {
      "origin_id": null, "destination_id": null,
      "vehicle_id": null, "cargo_manifest_id": null,
      "departure_at": null, "arrival_at": null,
      "time_scope": "departure_to_arrival",
      "transport_cost": null, "currency": "USD",
      "tax_basis": null, "cost_scope": "round_trip_transport"
    },
    "actual": {
      "origin_id": null, "destination_id": null,
      "vehicle_id": null, "cargo_manifest_id": null,
      "departure_at": null, "arrival_at": null,
      "time_scope": "departure_to_arrival",
      "transport_cost": null, "currency": "USD",
      "tax_basis": null, "cost_scope": "round_trip_transport",
      "cost_evidence_kind": "paid_invoice"
    }
  }]
}
```

주소의 물리적 시설 ID를 계획/운영 로그에 매핑한다. 그래프 노드 이름만 같거나
국경 이름이 같은 것으로 동일 배송을 인정하지 않는다. 화물 명세 ID는 품목·수량과
포장 중량을 연결해야 한다. `truck_plan`의 departure/arrival/transport_cost를 추정
측에 옮기고 실제 GPS·수령/청구서에서 실측 측을 채운다. 시간대가 필수다.
UTC와 Europe/Warsaw의 여름시간 차이는 날짜별로 변환해야 한다.

비용은 양쪽 모두 같은 세전 또는 세후 기준, USD, 왕복 운송만 포함한다.
PLN/EUR 청구서는 해당 청구일 또는 사전 합의한 기준일 공식 환율로 USD 환산하고
원화폐·날짜·환율·세금·환산 과정을 증빙 묶음에 보관한다. 이번 요금표 환율을
다른 날짜의 실제 청구서에 자동 사용하지 않는다. 물품 구매비를 배송비에 섞지 않는다.

```powershell
python scripts/validate_operational_evidence.py --trips 실제기록.json --output 별도평가폴더
```

시간과 비용 적격 여부는 별도로 판정한다. 비용 자료가 없더라도 유효한 시간 기록은
평가할 수 있다. 제외 이유와 분모를 함께 보고한다. 빈 표본의 MAE/WAPE는 null이다.
실측 0인 비용 표본은 MAE에 포함하지만 전체 실측 비용 합이 0이면 WAPE는 null이다.
평가 기간은 보정 기간과 분리해야 하며 `split` 표기는 데이터 관리자가 실제 분리를
확인해야 한다. 현재 코드는 기록의 선언을 검사하며 독립 현장 감사자를 대신하지 않는다.

## 실제 효과 검증의 다음 단계

보고서 5절의 계획을 따른다. 동일 조건의 과거 재생, shadow mode, 가능하면 무작위
교차 적용 순서로 진행한다. 실패·취소·부족·폐기도 포함한다. OTIF의 완전 납품 여부와
수령 마감은 현재 시간/비용 채점기의 입력이 아니므로 운송장 수령 기록으로 별도 확인한다.
기관이 없는 현 상태에서는 효과의 비교군·관측 결과가 없어 인과 효과를 계산할 수 없다.
누락한 지표를 합성 출력으로 대체하여 현장 성과로 표시하지 않는다.

# 운송·리드타임·유통기한 제약 (2026-10-02)

2026-10-03 추가: 사용자의 새 지시로 기존 디자인을 유지한 UI 연결을 구현했다.
[도로망 UI 연결](road_ui_integration.md)에 입력·기본값 출처·API·호환·검증을 기록했다.
아래 모델만/새 UI 대기 문장은 당시 구현 범위이며 배포·최종 발표는 계속 별도다.

## 도로망 모델 추가 안내 (2026-10-02)

이 문서의 주 버킷/승인 노선 모델은 그대로 유지한다.
`logistics.road_network`를 사용하는 별도 입력 모드는 분 슬롯, 개별 트럭 화물,
모든 단순 왕복 경로·출발 슬롯을 함께 최적화한다. 이 경우 루트의
`vehicles/routes/corridors`를 생략한다. 정확한 계약과 시간/FEFO 해석은
[도로망 최적화 사양](road_network_optimization.md)을 따른다.

현재 `ofr_v2`의 선택 구호소 MILP에 물류 확장을 추가했다. 기존 수요식과
공정성/효율 우선순위를 유지하며 `logistics`를 제공하면 새로운 제약을 함께 푼다.
이 문서는 구현 사양이며 현장 수치가 검증됐다는 의미는 아니다.

## 공식 출처와 반영 범위

아래 출처는 2026-10-02에 직접 확인했다. WFP Logistics Cluster의 LOG는
인도주의 물류 운영 지침이며 폴란드 시설별 실측 자료가 아니다.

| 출처 | 확인한 내용 | 구현 연결 |
|---|---|---|
| [WFP Logistics Cluster — Unique Concepts to Road Transportation](https://log.logcluster.org/en/unique-concepts-road-transportation), Body and Size | 차량 총중량은 차량 자체 중량을 포함한다. 적재중량은 제조사 규격 및 현지 제한을 따른다. 부피가 먼저 제한될 수 있다. | 포장 포함 kg/단위, m³/단위와 차량별 실제 적재중량·부피를 각각 제한 |
| [WFP Logistics Cluster — Sending Goods by Road](https://log.logcluster.org/en/sending-goods-road), Route Planning and Scheduling | 차량 용량, 운행 시간, 도로 적합성, 하역 및 도착시설 운영시간을 검토한다. | 사전 승인 노선 선택, 주별 허용 출발 횟수·중량·부피, 왕복 중 차량 공유 제한 |
| [WFP Logistics Cluster — Procurement](https://log.logcluster.org/en/procurement), Common Terms | 리드타임은 조달 착수에서 배송까지 걸리는 시간이다. | 공급업체 준비기간과 출발 이후 운송·대기·하역을 중복 없이 분리 입력 |
| [WFP Logistics Cluster — Defining When to Order](https://log.logcluster.org/en/defining-when-order) | 주문 결정에 수요, 리드타임, 현재 재고와 주문·운송 중 재고를 고려한다. | 이전에 발주·운송 예약된 파이프라인 배치와 신규 주문 분리 |
| [WFP Logistics Cluster — Physical Storage Guidelines](https://log.logcluster.org/en/physical-storage-guidelines), Expiration Management / Damaged Items | 기한이 있는 물품은 FEFO, 만료품은 분리하고 출고를 막는다. 손실과 처리량을 장부에 반영한다. | 배치별 FEFO, 만료 즉시 지급 금지, 격리 재고·폐기량·비용과 공간 추적 |
| [European Commission — Weights and dimensions](https://transport.ec.europa.eu/transport-modes/road/weights-and-dimensions_en) | EU 차량 중량·규격은 Directive 96/53/EC와 개정 법령의 적용을 받는다. | 법정 총중량을 화물 적재중량으로 대입하지 않는다. 실제 차량·노선에 적합한 유효 payload를 입력 |
| [European Commission — Driving time and rest periods](https://transport.ec.europa.eu/transport-modes/road/social-provisions/driving-time-and-rest-periods_en) | 운전·휴식 규칙과 예외가 운행 일정에 영향을 준다. | 편도·왕복 소요일수는 휴식·대기·하역을 포함하는 승인된 일정이어야 함. 주간 모델은 시간별 운전자 규칙을 직접 검증하지 않음 |
| [폴란드 KAS / Straż Graniczna — 우크라이나 화물차 통관 배치](https://granica.gov.pl/j/index.php/899-zmiany-organizacyjne-odpraw-pojazdow-w-ruchu-towarowym-w-przejsciach-granicznych-z-ukraina), 게시 2022-08-25, 갱신 2026-06-18 | Medyka·Korczowa·Dorohusk 등 통관 지점별로 차량 총중량 범주의 조건이 있다. | 실제 국제운송이면 허용된 차량·노선을 먼저 확인. 폴란드 내 구호소 배송에 국경 조건을 자동 적용하지 않음 |

공식 자료에서 구호 기관에 할당된 주별 통과 횟수, 차량 재고, 계약 리드타임,
제품 배치 만료일, 폐기비를 얻지는 못했다. 이를 실제값처럼 만들어 넣지 않았다.
`example_logistics()`와 예제 JSON의 모든 수치는 **합성 시험값**이다.
실제 운영 입력의 근거는 차량등록/제조사 규격, 승인 운행표·통과 슬롯,
발주서·계약·입고 이력, 제품 라벨·재고 장부, 처리업체 계약이다.

## 시간 기준

- 원점은 다음 계획 1주 시작이며 기존 API의 예측 주차 1..4를 사용한다.
- 주 시작에 주문하면 준비 완료 출발 주 `d = o + ceil(procurement_days / 7)`.
- 사용 가능한 도착 주 `a = d + ceil(transit_days / 7)`.
- 양수 지연은 다음 버킷까지 보수적으로 넘긴다. 당일 직접 수령만 0일로
  입력한다. 예를 들어 조달 1일 + 운송 1일은 총 2주 버킷 이동이다.
  짧은 실제 지연에서는 이 방식이 과도하게 보수적일 수 있으므로 일별
  상세 배차로 사용해서는 안 된다. 정확한 주내 사용 시점에는 일별 확장이 필요하다.
- 신규 구매의 `shelf_life_days`는 **공급업체 출발 시 남은 기한**이다.
  첫 사용불가 주 `e = d + floor(shelf_life_days / 7)`;
  배치는 `a <= w < e`에서만 사용한다. 도착 주 전체를 보장하지 못하면
  신규 주문 후보에서 제외한다. 운송기간 때문에 제품 기한이 다시 시작되지 않는다.
- `initial_lots` / `pipeline_lots`의 `expiry_week`는 **첫 사용불가 주**다.
  1은 이미 사용불가, 2는 1주에만 사용 가능하다. 실제 만료가 주 중간이면
  해당 주부터 사용불가로 보수적으로 매핑한다. `null`은 기한 없는 제품이다.
- 준비가 완료되면 공급업체에서 바로 출발한다. 공급업체 창고 비축·출발
  연기는 이번 모델 범위에 포함되지 않는다.
- 계획 종료 뒤 도착하는 신규 주문은 생성하지 않는다. 파이프라인 입력은
  도착 주가 계획 안에 있는 건만 받으며 이후 도착은 별도 장부에서 유지한다.

## 수식

`q[i,o,r]`: 품목 i를 주문 주 o에 구매해 노선 r로 운송하는 양.
`n[r,d]`: 노선 r에서 출발 주 d에 출발하는 차량 수(정수).
`y[b,w], I[b,w]`: 배치 b의 주 w 지급량과 사용가능 기말재고.
`U[i,w]`: 부족량. `E[i,w]`: 당주 신규 만료량.
`Q[i,w]`: 격리 기말재고, `Z[i,w]`: 실제 처리 예정 폐기량.

1. **조달 한도**: `sum_r q[i,o,r] <= weekly_supply[i,o]`.
   확장 모드의 공급 한도는 **주문 주 공급업체 할당량**이다. 도착 주 한도가
   아니다. 동일 공급량을 여러 노선에서 중복 사용하지 않는다.
2. **차량 용량**: 출발 주별 `sum_i weight[i]*q <= payload[vehicle]*n`,
   `sum_i volume[i]*q <= volume[vehicle]*n`.
3. **노선·통과 용량**: 주별 차량 수, 화물 kg, 화물 m³ 상한을 각각 적용.
   공유 corridor는 `crossing_week = d + ceil(corridor_delay_days/7)`에
   도달하는 모든 노선의 차량 수 합을 `corridor_slots[crossing_week]`로 제한한다.
   출발 주와 통과 주를 혼동하지 않는다. 통과 지연은 편도기간 이내여야 한다.
   폐쇄 주의 허용 차량 수는 0. 품목 취급이 허용된 노선만 후보로 생성한다.
4. **차량 중복 사용 금지**: 출발 주 d부터
   `max(1, ceil(round_trip_days/7))`주 동안 해당 차량을 점유한다.
   같은 차량 유형을 쓰는 모든 노선의 진행 중 운행 합이 가용 차량 수 이하다.
   주내 여러 회전은 허용하지 않는 보수적인 차량-주 계획이다.
5. **수요와 배치 흐름**: `sum_b y[b,w] + U[i,w] = demand[i,w]`,
   `I[b,w] = I[b,w-1] + arrival[b,w] - y[b,w]`.
   배치 도착 전 및 만료 이후에는 지급변수를 만들지 않는다.
6. **FEFO**: 더 늦게 만료하는 배치를 쓰려면 현재 사용 가능한 더 일찍
   만료하는 모든 배치의 기말재고가 0이어야 한다. 이진변수와 배치 공급량
   상한으로 구현한다. 같은 만료일은 동순위, 기한 없는 배치는 마지막이다.
7. **격리와 폐기**: `Q[i,w] = Q[i,w-1] + E[i,w] - Z[i,w]`,
   `Z[i,w] <= disposal_capacity[i,w]`. 만료량을 자동 지급·소실 처리하지 않는다.
   폐기량은 계획이며 현장 승인 및 실제 장부 갱신을 대체하지 않는다.
8. **창고**: 만료품 분리·처리 후, 당주 입고 직후, 배급 전에
   사용가능 재고 + 남아 있는 격리 재고의 총부피가 창고용량 이하.
   전주 재고는 이미 용량 안에 있으며 당주 폐기는 입고 전에 수행하는 일정이다.
9. **예산**: 신규 구매비 + 차량 출발별 운송비 + 단위별 폐기비의 합이 총예산 이하.
   구매·운송을 이미 결제하고 예약한 pipeline은 다시 비용·차량에 청구하지 않는다.
   가용 차량과 corridor 슬롯은 해당 선예약을 뺀 **추가 가용량**으로 입력한다.

식량·위생키트·담요의 구매·지급·재고·격리·폐기는 정수, 물은 연속 L이다.
단위가 다른 부족량은 기존 품목별 총수요로 정규화한다.
목적함수 순서는 공정성 최대부족률(공정성 모드), 정규화 부족량,
총비용, 동률일 때 만료/격리량, 마지막으로 불필요한 차량 수다.
이전 목적값을 제약으로 고정한다. 설정한 MIP gap 허용오차 안에서 솔버가
최적 상태(status 0)로 보고한 해만 사용하며 단계별 실제 gap을 결과에 기록한다.
정수 반올림 뒤 모든 수식·상한·목적값 고정을 다시 검사한다.

## API와 화면

`POST /optimize`의 기존 필드에 `logistics` 객체를 추가한다. 생략 시 기존 계산을
유지하며 물류 제약이 활성화됐다고 표시하지 않는다. `optimization.py`의
`optimize_relief_plan(..., logistics=...)`도 동일하게 사용할 수 있다.
전체 계약은 `ofr_v2/examples/logistics_request.json`에 있다.

구호품 계획 화면에서 제약을 켜면 포장중량, 조달일수, 기한, 차량, 편도·왕복,
운송비, 주별 차량·통과 수, 폐기비·한도를 입력할 수 있다. 직접 입력 화면은
단일 노선과 품목별 단일 재고기한을 가정한다. 복수 배치/노선/파이프라인은
상세 `logistics` JSON을 가져온다(전체 요청이 아닌 logistics 객체).

결과의 `recommended_shipment`는 **도착량**이다. 신규 `recommended_order`와
`dispatched`는 주문 주·출발 주의 양이다. `order_plan`, `transport_plan`,
`lot_plan`, `expired_quantity`, `disposed_quantity`, `quarantined_inventory`를
함께 보고해야 한다. `total_procurement_cost`는 구매비만,
`total_cost`는 구매+운송+폐기비이며 잔여예산도 총비용 기준이다.

## 검증과 남은 범위

`python -m pytest ofr_v2/tests -q`로 느슨한 제약에서 기존 해와 동등함,
중량/부피 제한, 공유 차량·통과용량, 왕복 점유, 두 리드타임, 기한이 운송 중
끝나는 주문 제외, FEFO, 만료·격리·폐기 흐름, 비용과 API 전달을 검증한다.
예제 결과는 합성 시나리오의 제약 검증이며 예측 정확도나 실제 성과가 아니다.

단일 구호소/승인된 직접 노선 범위이며 도로망 경로 탐색, 일별 운전자 배차,
냉장·온도 이탈, 다구호소 중앙 자원 공유, 확률적 지연, 계획 이후 말기재고의
사용가치/미래수요는 별도 확장 대상이다. 별도 모델 간 최적화 결과를 합산해
중앙 자원을 이중 사용해서는 안 된다. 실제 법률·차축별 제한과 통관 허용
여부는 노선 승인 과정에서 확인한다.

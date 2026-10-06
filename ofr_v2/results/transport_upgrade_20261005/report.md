# Dorohusk 저속 운송조건·비용 모델 수정 검증

검증일: 2026-10-05. 실제 도로 선형 + 합성 수요. 예측 모델 수정·추론·학습 없음.

물리·비용 독립 감사 24/24 통과. 검증 중 자산 해시 유지: True.

## 비교 조건과 결과

창고 Lwowska 36, 차량 1대, 매주 구호 이용자 30명/체류 1일의 합성 수요를 사용했다. 짝 비교는 속도·비용(100 USD+1 USD/km)·도로·차량·공급·예산·출발 후보를 같게 유지하고 다음 근무일 복귀 및 중간 휴식 노드 가정만 변경했다. 비용 현실화 효과와 운송 설계 효과를 섞지 않았다.

| 도착지 | 속도 | 설계 | 운행 | 야간 복귀 | 수요 충족 % | 운송 USD | 물리 감사 |
|---|---:|---|---:|---:|---:|---:|---|
| Medyka | 60 | legacy | 2 | 0 | 100.00 | 241.08 | pass |
| Medyka | 60 | overnight-with-assumed-rest | 2 | 0 | 100.00 | 241.08 | pass |
| Medyka | 45 | legacy | 2 | 0 | 100.00 | 241.08 | pass |
| Medyka | 45 | overnight-with-assumed-rest | 2 | 0 | 100.00 | 241.08 | pass |
| Medyka | 30 | legacy | 2 | 0 | 100.00 | 241.08 | pass |
| Medyka | 30 | overnight-with-assumed-rest | 2 | 0 | 100.00 | 241.08 | pass |
| Korczowa | 60 | legacy | 2 | 0 | 100.00 | 340.60 | pass |
| Korczowa | 60 | overnight-with-assumed-rest | 2 | 0 | 100.00 | 340.60 | pass |
| Korczowa | 45 | legacy | 2 | 0 | 100.00 | 340.60 | pass |
| Korczowa | 45 | overnight-with-assumed-rest | 2 | 0 | 100.00 | 340.60 | pass |
| Korczowa | 30 | legacy | 2 | 0 | 100.00 | 340.60 | pass |
| Korczowa | 30 | overnight-with-assumed-rest | 2 | 0 | 100.00 | 340.60 | pass |
| Dorohusk | 60 | legacy | 2 | 0 | 100.00 | 1019.77 | pass |
| Dorohusk | 60 | overnight-with-assumed-rest | 2 | 0 | 100.00 | 1019.77 | pass |
| Dorohusk | 45 | legacy | 0 | 0 | 0.00 | 0.00 | pass |
| Dorohusk | 45 | overnight-with-assumed-rest | 2 | 2 | 100.00 | 1019.77 | pass |
| Dorohusk | 30 | legacy | 0 | 0 | 0.00 | 0.00 | pass |
| Dorohusk | 30 | overnight-with-assumed-rest | 2 | 2 | 100.00 | 1019.77 | pass |
| Dorohusk | 30 | public-distance-component | 2 | 2 | 100.00 | 1868.76 | pass |
| Dorohusk | 30 | public-hour-rate-scenario | 2 | 2 | 100.00 | 2163.26 | pass |
| Dorohusk | 30 | synthetic-extras-stress | 2 | 2 | 100.00 | 2089.52 | pass |
| Dorohusk | 30 | high-demand-1-vans | 8 | 8 | 55.20 | 7475.05 | pass |
| Dorohusk | 30 | high-demand-2-vans | 15 | 15 | 100.00 | 14015.73 | pass |
| Dorohusk | 30 | high-demand-3-vans | 15 | 15 | 100.00 | 14015.73 | pass |

충족률은 품목별 총수요로 정규화한 미충족률의 평균을 100에서 뺀 값이다. 감사 통과와 전량 배송은 다르다. high-demand는 매주 250명, 차량 1~3대 조건으로 자원 부족을 노출한다.

## 적용한 운송조건

하루 안에 왕복 가능한 운행을 우선 사용한다. 불가능하면 출고·배송은 첫 근무, 도착지 휴식 11~36시간, 공차 복귀는 바로 다음 근무로 제한한다. 각 근무의 주행 9시간, 연속 주행 4.5시간/휴식 45분, 주·2주 주행 한도, 차량 복귀 전 재사용 금지와 재고 기한·예산은 그대로 검사한다. [EU 공식 설명](https://transport.ec.europa.eu/transport-modes/road/social-provisions/driving-time-and-rest-periods_en)을 참고한 보수적 정책이며 이 국내 밴 운행에 모든 조항이 법적으로 적용된다는 판단은 아니다. 중간 휴식은 선택 경로의 누적 반올림 주행시간 절반에 가까운 도로 노드의 시나리오 가정이다. 실제 시설·허가를 확인한 지점이 아니며 가정을 끄면 운행이 다시 불가능할 수 있다. 주말을 건너뛰는 대기, 편도 자체가 근무 한도를 넘는 경로, 일반 다일 VRP는 지원하지 않는다. 경로 최적성은 k=1 최단거리 후보와 시간 격자에 조건부다.

## 비용의 근거와 한계

근거 없는 고정 100 USD 기본값을 제거하고 [PGKiM Lubsko 공식 요금표](https://www.pgkimlubsko.pl/cennik.html)의 3.5t 이하 밴 세전 8.50 PLN/km (2025-02-03 적용)를 거리 성분 참고값으로 사용했다. [NBP 2026-03-16 환율](https://api.nbp.pl/api/exchangerates/rates/a/usd/2026-03-16/?format=json) 3.7287 PLN/USD로 환산한 약 2.280 USD/km다. 이 환율은 날짜가 지정된 평가 기준이다. 별도 228 PLN/h는 같은 요금표의 시간 기준이며 거리비에 자동 합산할 근거가 없어 시간 기준 시나리오에서만 사용했다. 상하차 포함 여부·야간 대기·최소요금·거리 기점·최신 가격·계약 조건은 이 자료로 확정되지 않는다.

`max(최소 운행비, 고정비+왕복거리×km단가+청구시간×시간단가)+야간 추가비+통행료`를 계산한다. 청구시간은 적재 시작~복귀에서 도착지 야간 휴식을 제외하며 복귀 후 창고 휴식/회전은 제외하는 프로젝트 규칙이다. 공개 시간 요금표의 실제 청구 규칙으로 검증된 것은 아니다. 추가 비용 기본 0은 제외 항목이라는 뜻이며 무료라는 증거가 아니다. synthetic-extras-stress의 25 USD 고정/2 USD 시간/100 USD 최소/50 USD 야간은 수학 검증용 가상 견적이다. 세금·숙박·기사·기타 비용과 공급업체 USD 비용의 세금 범위도 견적에 맞춰 일치시켜야 한다. 어느 결과도 실제 지급액 오차나 절감액으로 해석할 수 없다.

## 실측 검증 상태

실제 배송시간 대응 표본 0건, 지급비용 대응 표본 0건. MAE/WAPE는 계산 불가(null). 현장 효과 미입증.

추가 조사한 [Logistics Cluster 2026-04-07 현장 회의](https://logcluster.org/en/documents/ukraine-coordination-meeting-minutes-sloviansk-7-april-2026)와 [4년 운영 요약](https://logcluster.org/en/stories/four-years-coordinating-humanitarian-logistics-ukraine-turning-coordination-impact)은 누적 활동·운영 지침이며 동일 배송의 출발/도착/인수/지급액을 제공하지 않는다. 국경 너머 우크라이나 컨보이의 신청 리드타임을 폴란드 국내 주행시간으로 대입하지 않았다. [Chełm 시 공식 창고 안내](https://samorzad.gov.pl/web/miasto-chelm/punkt-magazynowy-dla-ciezarowek-w-chelmskim-centrum-aktywnosci-gospodarczej)의 Ceramiczna 5 후보는 현재 운영·좌표·실제 도로 연결을 확보하지 못해 모델에 넣지 않았다.

원문 다운로드/주소 API는 이번 실행에서 네트워크 오류로 실패했다. 새 요금표의 정규화 사실·웹 검토일·URL을 `transport_upgrade_sources.json`에 기록했고 원문 바이트 SHA 확보를 주장하지 않는다. 기존 NBP 원문 해시와 공식 도로 스냅샷은 보존했다.

실측 채점기는 출발 전 계획·운송장/차량/화물/구간·시간대·지급 증빙과 비용 범위를 대조한다. 운영 기록이 없는 상태에서는 이 검사 구현과 합성 검증으로 실제 정확도를 증명할 수 없다. 인수 기록의 시간·물량과 기존 배차 방식의 비교가 있어야 정시 인수율·비용/인수량·부족률 개선을 평가할 수 있다. 공개 집계로 현장 효과를 추정하거나 기록을 만들어 넣지 않았다.

## 재현

`python scripts/validate_transport_upgrade.py --output <directory>`

`python -m pytest ofr_v2/tests/test_transport_upgrade.py -q`

코드와 독립 감사는 야간 휴식 누락·잘못된 위치/길이·근무 밖 복귀·중복 차량 사용·주행 한도·예산·비용 성분 오류를 검사한다. `dorohusk_30_truck_schedule.json`에 차량별 물품 수량·출발/배송/복귀·실제 도로 edge 경로·가정 휴식·비용 성분을 저장했다. 운영 인증 자료가 아닌 재현 가능한 시나리오 산출물이다.

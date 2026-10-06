# 실제 폴란드 도로 데이터 연결과 검증 범위

자료 확인일/구현일: 2026-10-02. 사용자가 승인한 범위는 최적화 모델, 실제
도로 입력 연결, 창고 후보 조사다. 새 지도 화면·발표자료·배포·실제 배차는 대기한다.

사용자의 명시적 재개 요청으로 실패 구간을 세분해 공식 RoadLink 원문 106개를
추가 확보했다. manifest에는 원문 문서 241개와 미취득 작은 타일 34개가 남는다.
**두 창고 후보에서 Medyka·Korczowa·Dorohusk 모두까지 선형 경로가 연결됐다.**
최신 지역 자료와 주소별 연결 상태는 `validation.json` 및
`facility_validation.json`이 기준이다. 도로 취득은 다시 수동 실행으로 설정했다.

Dorohusk 회랑을 포함한 선택 지역의 중복 제거 RoadLink는 122,931개다.
주소 사이 단순 경로에 필요한 그래프는 71,938노드 / 195,160방향 간선이다.
이는 전국 도로망이나 현재 트럭 통행이 검증된 그래프가 아니다. 미취득 타일은
연결을 막지는 않지만 다른 경로의 누락·최적성에 영향을 줄 수 있다. 원문 feature의
2015~2023년 버전과 2026년 수집일을 구분한다.

| 창고 후보 | Medyka 293 | Korczowa 155 | Dorohusk-Osada, Parkowa 5 |
|---|---:|---:|---:|
| Lwowska 36 | 10.269 km | 35.151 km | 204.943 km |
| Wodna 11 | 13.124 km | 37.239 km | 204.560 km |

위 값은 확보한 끝점 연결/양방향 가정 그래프의 최단 선형 거리다. 실제 트럭
출입구까지의 접근 구간, 일방통행, 중량 제한을 검증한 운행 거리가 아니다.

## 구현 결과

`app/backend/poland_roads.py`는 GUGiK/Geoportal 공식 INSPIRE WFS에서 받은
RoadLink 원문을 읽고 출처·해시·좌표·도로 선형을 보존한다. `road_network.py`는
이 그래프에서 개별 트럭의 적재·출발·복귀·경로를 공동 결정한다. 결과의
`outbound_geometry`/`return_geometry`에는 원본 도로 feature ID와 좌표가 남는다.
연결되지 않은 출발·도착지를 직선으로 잇거나, 서버 실패 때 가짜 도로로 대체하지 않는다.

최초 확보한 Medyka 주변 원문에는 **실제 RoadLink 2,040개**가 있다. 끝 좌표를
연결한 시나리오 그래프는 노드 1,717개, 방향 간선 4,078개다. 폐곡선 1개를 제외했다.
연결 성분은 1,193 / 518 / 2 / 2 / 2개 노드다. 양방향 간선은 시험 가정이다.
받은 날짜는 2026-10-02이지만 feature 버전 시각은 **2019-06-10 ~ 2022-12-02**다.
다운로드 시각을 도로 갱신 시각으로 해석하지 않는다.

추가 수집의 성공/실패 지역과 구간 수는 `data/roads/raw/acquisition.json`과
`data/roads/validation.json`을 기준으로 확인한다. 지역별 bbox를 타일로 나누고
한도 5,000개에 도달한 응답은 다시 분할한다. 겹치는 feature를 ID로 중복 제거하며,
동일 ID의 선형이 다르면 중단한다. 실패 타일은 `errors`로 보존한다. 이는 특정
지역의 다운로드 범위이며 **전국 도로망이나 모든 창고–구호소 회랑을 뜻하지 않는다**.

## 공식 출처와 자료에 없는 값

| 기관/공식 자료 | 확보한 근거 | 한계 |
|---|---|---|
| [GUGiK INSPIRE 서비스 목록](https://www.geoportal.gov.pl/pl/usluga/uslugi-inspire/) | 교통망 WFS 서비스 주소 | 목록에 있다고 모든 차량 제한이 제공되는 것은 아님 |
| [GUGiK BDOT10k 안내](https://www.geoportal.gov.pl/pl/dane/baza-danych-obiektow-topograficznych-bdot10k/) | 공식 지형 벡터 자료의 교통망·다운로드 안내 | 지형 선형은 운행 승인/실시간 교통 자료가 아님 |
| [INSPIRE Transport Networks](https://knowledge-base.inspire.ec.europa.eu/transport-networks_en) | 교통망 데이터 체계 | 서비스별 실제 필드 채움 상태를 확인해야 함 |
| [GUGiK UUG 공식 설명서](https://www.geoportal.gov.pl/wp-media/2023/10/PodstawoweUslugiDanychPrzestrzennychDlaSystemowInformatycznychPanstw-ver.-1.12.pdf) | 주소점 검색, CS92 좌표 응답 | 주소점은 차량 출입구/하역장과 다를 수 있음 |
| [GDDKiA 도로정보](https://www.gov.pl/web/gddkia/msbd), [도로 장애 XML 안내](https://www.gov.pl/web/gddkia/dane-xml) | 향후 운영 상태/장애 자료의 공식 연결점 | 이번 snapshot에는 실시간 장애·통행 승인을 연결하지 않음 |

정확한 요청 URL, SHA256, 수집 시각은 manifest에 기록한다. 공개 원문을
GitHub 검증 환경에서 받아 압축/base64 텍스트로 보존했다. 원문을 복원한 뒤
SHA256을 확인하므로 XML 전체를 중복 저장할 필요가 없다. 압축 파일은 사진 지도나
임의 제작한 경로가 아니다. 실제 공식 도로 선형의 원문이다.

현재 응답에서 `startNode`·`endNode`는 `other:unpopulated`다. 일방통행, 차량별
접근 금지, 높이·총중량·축중, 속도, 통행료, 승인 휴식 시설을 확인할 수 없다.
source road 이름도 현재 가져오기에서는 조회하지 않아 RoadLink ID로 표시한다.
도로 폭이나 차로 수만으로 허용 트럭 폭/중량을 추정하지 않는다.

## 좌표·연결·시간 검증

- WFS 1.1에서 EPSG:4326으로 요청한 원문 WKT는 **위도, 경도** 순서다.
  결과 좌표는 GeoJSON 규칙의 **경도, 위도**로 바꾼다. 폴란드 밖으로 나오는
  축 순서, 홀수/3차원 좌표, 잘못된 XML, feature 개수 불일치와 해시 불일치를 거부한다.
- 거리에는 pyproj의 WGS84 타원체를 사용해 선형의 모든 꺾임을 합산한다.
  출발점–도착점 직선 거리로 운송비를 계산하지 않는다.
- 같은 끝 좌표만 연결한다. 선 내부의 교차, 입체 교차, 근접한 끝점은 자동 연결하지
  않는다. 실제 연결인데 좌표가 다르면 단절로 남을 수 있으므로 현장/도로 기관의
  교차로 검증이 필요하다. 정확히 겹친 끝점도 운행 가능성을 인증하지는 않는다.
- 주소점은 기존 도로 끝점에만 붙이며 최대 거리(기본 500m)를 넘으면 거부한다.
  붙인 거리와 미확인 시설 진입을 diagnostics에 기록한다. 그 틈을 가짜 진입로로 만들지 않는다.
- 실제 도로 시나리오는 5초 슬롯으로 구간별 시간을 올림한다. 적재·하역·휴식·조달도
  같은 슬롯을 사용한다. `unrounded_driving_minutes`와 `time_rounding_added_minutes`를
  함께 출력한다. 이 보정은 시간 이산화 오차를 줄이는 것이며 **실제 속도 검증은 아니다**.

실제 최초 도로망의 60개 구간 왕복 검증 경로에서 40km/h라는 **시험 가정**의
운전 시간은 약 51.96분이다. 1분 슬롯에서는 144분, 5초 슬롯에서는 57분이다.
이 경로의 출발/도착은 연결 성분의 시험용 도로 끝점이며 실제 창고/구호소로 표시하지 않는다.

## 창고와 도착 시설 후보

시설 목록은 `data/roads/facilities.json`에 주소·기관·출처·확인 상태를 보존했다.
주소가 공개되어 있다는 사실과 2026년에 우리 차량/물품을 받아준다는 사실은 다르다.
현재 사용 가능한 수용량·계약·운영시간을 확인하지 못했으므로 확정 운영 창고로 선택하지 않는다.

| 후보 | 공식 근거 | 검토 판단 |
|---|---|---|
| Przemyśl, Lwowska 36, 전 Tesco 시립 구호물품 창고 | [Przemyśl 시청, 2022-03-25 갱신](https://przemysl.pl/64115/pomagamy-uchodzcom-z-ukrainy-aktualizacja.html) | 우선 연락/현장 검토 후보. Medyka·Korczowa와 같은 지역이라는 지리적 판단이며 물류 성능 비교 결과가 아님 |
| Przemyśl, Wodna 11, 시청 건물의 시립 구호물품 창고 | [같은 시청 공지](https://przemysl.pl/64115/pomagamy-uchodzcom-z-ukrainy-aktualizacja.html) | 두 번째 후보. 도심 차량 접근·하역/적치 용량 미확인 |
| WFP/Logistics Cluster Rzeszów 공용 창고 서비스 | [2022-08-17 공식 회의록](https://s3.eu-west-1.amazonaws.com/logcluster-web-prod-files/public/2022-08/Logistics%20Cluster_Ukraine_Kyiv_Coordination%20Meeting_220817.pdf) | 2022-08-31 서비스 종료 공지가 있어 가용 후보에서 제외 |

사용자가 지정한 세 거점은 모델의 `Medyka`, `Korczowa`, `Dorohusk`로 유지한다.
과거 공식 접수소 주소는 다음과 같으며 현재 시설과 하역장으로 확정하지 않는다.

- Medyka: [Medyka 지방정부](https://samorzad.gov.pl/web/gmina-medyka/akcja-pomocy-dla-osob-objetych-konfliktem-na-terytorium-ukrainy)는 체육관 **Medyka 293**을 기재한다.
  [다른 공식 안내](https://torun.praca.gov.pl/documents/1790411/17410339/Wersja%2Bpo%2Bangielsku.pdf/5cb0f36e-2b71-49e3-aeb2-dc872e9efa38?t=1646226842000)는 285를 기재해 충돌을 기록했다.
- Korczowa: [Jarosław 고용청](https://jaroslaw.praca.gov.pl/rynek-pracy/aktualnosci/aktualnosc/-/asset_publisher/5CI48Qxw9jwJ/content/id/17346376/pop_up)은 마을회관 **Korczowa 155**를 기재한다.
  [폴란드 인권위원회 방문 기록](https://bip.brpo.gov.pl/pl/content/RPO-wizyty-przy-granicy-polsko-ukraina)은 별도 Hala Kijowska 접수소를 구분한다.
- Dorohusk: [Kraśnik 지방정부 공식 안내](https://samorzad.gov.pl/web/powiat-krasnicki/pomoc-dla-obywateli-ukrainy---informacje---)의
  **Parkowa 5, Dorohusk-Osada**는 역사적 접수소 주소다.

국경 도로 통과 지점, 마을 접수소, 난민 센터와 물품 하역장은 같은 목적지가 아니다.
주소가 충돌하거나 공식 주소 서비스가 실패하면 좌표를 임의 작성하지 않는다.
UUG 응답의 도시·번지·도로명을 확인하고 EPSG:2180에서 WGS84로 변환하는 기능을
구현했다. 매칭되지 않는 후보는 요청 생성 단계에서 중단한다.

현재 활동 근거가 더 최근인 **식량 조달/유통 협력 후보**도 별도로 조사했다.
[Podkarpacki Bank Żywności 공식 공지](https://www.rzeszow.bankizywnosci.pl/)는
Rzeszów **Konopnickiej 18**에서 2026년 9월 식량 배분을 공지하고, 같은 장소를
이전 공지에서 식량 창고로 설명한다. 이 기관은 [2025년 Rzeszów 시 지원 결과](https://erzeszow.pl/1059-konkursy/116471-wyniki-otwartego-konkursu-ofert-na-realizacje-zadania-publicznego-w-2025-roku-pnzapewnienie-dostaw-zywnosci-dla-rodzin-najubozszych.html)에도
식량 지원 수행기관으로 나온다. **사무소 Rynek 17과 물류/배분 장소를 구분**한다.
[Lublin 식량은행의 공식 2025년 프로그램](https://bankzywnoscilublin.pl/popz/fepz2025/)은
Chełm **Kolejowa 8의 MOPR**을 지역 식량 인수/배분 협력기관으로 기재한다.
둘 다 물·담요·위생키트 전체를 맡는 운영 창고로 확정하지 않으며, 기존 사업용
식량을 우리 사업으로 전용할 수 있다고 가정하지 않는다. 구호물품 종류·계약·창고
수용량·시설 접근을 확인한 뒤 모델에 넣을 조달/협력 후보로만 보존한다.

## 모델 입력/최적성

가져오기 결과는 `data_kind="official_geometry_scenario"`다. 선형은 원자료지만
양방향·속도·통행 한도·통행료·운영창·차량·시설 값은 가정이다. `geography`가 각각의
검증 상태와 가정을 출력한다. 이를 `operational`로 이름만 바꿔도 미검증 플래그가
남으면 거부한다. 솔버는 현장 운행 안전을 인증하지 않으며 `operational_ready=false`다.

대형 그래프에서는 각 차량의 빈 중량·높이·폭·차종·통행 가능 입력을 먼저 적용한
후 거리/이동시간/비용 기준의 Yen 상위 k 단순 경로를 찾는다. 평행 도로 간선 ID와
양 방향을 유지한다. 후보 합집합에 대해 기존 적재·재고·납기·FEFO·폐기·예산·기사
휴식·왕복·차량 점유 제약을 **같은 MILP**로 푼다. 현재 importer 기본은 기준당 k=2,
거리와 이동시간 기준이다.

Spur 탐색은 역방향 최단거리 하한을 재사용하는 A*로 가속한다. Yen이 간선/노드를
제외해도 이 하한은 유지되며 소규모 완전 탐색과 결과 비용을 비교했다. importer의
대칭 그래프는 출발–도착 성분과 단순 경로에 필요한 가지를 남긴다. 새 연결이나
가짜 휴식 시설을 만들지 않는다. 시설 후보별 최단 선형 경로 검증은
`scripts/verify_poland_facility_routes.py`로 재현하며 운행 승인과 구분한다.

MILP가 최적이라고 확인해도 **주어진 후보·지역·차량·출발 격자 안에서만** 최적이다.
다른 도로/시각에 더 좋은 적재·폐쇄 우회가 있을 수 있다. 전국 최적성이나 세 구호소
동시 공유차량 최적성을 주장하지 않는다. 기존 소규모 기본 모드는 모든 단순 경로를
계속 열거한다. 신규 모드·후보 수·탐색 범위는 `model_info.path_search`에 기록한다.

명시적 대형 후보 모드는 노드 100,000 / 방향 간선 250,000 / 좌표점 합계
5,000,000 / 출처 256개 / k≤8을 상한으로 한다. 소규모 기본 모드 상한은 유지한다.
후보 4,096 / 발주 변수 1,024 / 운전 슬롯 합계 2,000,000 등의 별도 상한이 있다.
한도 초과는 오류로 중단한다. 조용히 일부를 버리고 전역 최적이라고 표시하지 않는다.

## 실행과 재현

```text
python -m pip install -r ofr_v2/app/requirements.txt
python -m pytest ofr_v2/tests -q
python scripts/verify_road_network.py
python scripts/verify_poland_roads.py --output ofr_v2/data/roads/validation.json
```

`scripts/fetch_poland_roads.py`와 전용 GitHub Actions 작업은 공식 사이트에서만
취득한다. 작업은 모델 배포/배차를 수행하지 않는다. 원문·manifest를 artifact로
보존하고 공개 원문만 로그에서 복구할 수 있게 기록한다. 서비스 장애가 있어도
성공한 타일을 보존하며 미취득 타일을 명시한다.

`scripts/build_poland_road_request.py`는 기존 요청의 명시적 차량/재고/수요 설정,
창고·도착 후보 ID, 도로 운행 가정 JSON을 받아 실제 도로 시나리오 요청과
diagnostics를 만든다. 공식 주소점/연결 범위가 없으면 실패하며, 원거리 후보를
가까운 도로에 억지로 붙이지 않는다. 실제 창고가 정해지면 그 창고를 포함하는
완전한 도로 회랑과 승인 진입로를 추가 취득해야 한다.

도착지 휴식은 기본 금지다. `--destination-rest-permission`은 명시적 **시나리오
가정**으로만 허용하며 주소·하역 시간을 기사 휴식으로 자동 취급하지 않는다.
왕복 전체를 미리 살펴 연속 운전 한도 전에 도달 가능한 허용 노드에 휴식을 넣는다.
도로 시간 창을 맞추기 위한 모든 선택적 휴식 시점은 열거하지 않는다.

Dorohusk 실제 선형 통합 검증은 시험 차량·수요·60km/h 속도와 목적지 휴식 허용을
명시한 경우 적재·출발·도착·복귀 계획을 계산한다. 동일 입력에서 목적지 휴식을
금지하면 연속 운전 한도로 해당 운행을 거부한다. 60km/h를 현실 주행 속도로
확인한 것이 아니며 휴식 허용도 운영기관 승인 자료가 필요하다.

검증은 합성 반례, 소규모 완전 탐색 대비 Yen 결과, 원문 해시·좌표 축·연결 성분,
실제 선형을 쓰는 적재/왕복/시간표 통합 검증을 포함한다. 시설 현장 도착 시각이나
구호기관 운송 실적과 비교한 외부 검증은 아직 없다.

"""Official external benchmarks and optional re-optimization sensitivity.

python scripts/validate_operational_evidence.py [--sensitivity] [--trips FILE]
No public benchmark in this dataset is a matched shipment log or paid invoice.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ofr_v2'))
sys.path.insert(0,str(ROOT/'scripts'))
from validation.operational import quantile_bin, score_trips

DATA = ROOT/'ofr_v2/data/operational_evidence'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def benchmarks():
    observations = read(DATA/'speed_observations.json')['observations']
    speed = []
    for row in observations:
        percentages = row['percentages']
        speed.append(dict(year=row['year'],station=row['station'],road=row['road'],
                          vehicle_class=row['vehicle_class'],source_id=row['source_id'],pdf_page=row['pdf_page'],
                          median_bin_kph=quantile_bin(percentages,.5),p10_bin_kph=quantile_bin(percentages,.1),
                          p90_bin_kph=quantile_bin(percentages,.9),below_60_pct=round(sum(percentages[:4]),2),
                          route_matched=False,whole_trip_eta_validation=False))
    ref = read(DATA/'cost_references.json')
    fx = ref['fx']['rates'][0]['mid']
    # Preserve the dated 2026-10-04 baseline independently of later UI presets.
    preset = dict(fixed_trip_cost=100,cost_per_km=1)
    distances = read(ROOT/'ofr_v2/data/roads/facility_validation.json')['routes']
    cost = []
    for route in distances:
        km = 2*route['shortest_scenario_distance_km']
        model_usd = preset['fixed_trip_cost']+preset['cost_per_km']*km
        net = round(math.ceil(km)*ref['tariff']['net_per_started_km'],2)
        gross = round(math.ceil(km)*ref['tariff']['gross_per_started_km'],2)
        cost.append(dict(warehouse=route['warehouse'],destination=route['destination'],round_trip_km=km,
                         model_transport_usd=model_usd,tariff_component_net_pln=net,
                         tariff_component_gross_pln=gross,model_over_tariff_net_ratio=model_usd*fx/net,
                         model_over_tariff_gross_ratio=model_usd*fx/gross,observed_cost=False,
                         tariff_source='zgl_tariff_2026',fx_source='nbp_usd_20260316'))
    return dict(speed_benchmarks=speed,cost_benchmarks=cost,fx=ref['fx'],
                public_sources=read(DATA/'sources.json'),matched_public_trips=0,
                speed_row_count=len(speed),independent_observed_delivery_count=0)


def sensitivity():
    # Fixed synthetic demand; geometry and declared UI conditions are reused.
    # Published tariffs are parameter scenarios, not calibrated van invoices.
    from validate_optimizer import fixture, solve, frozen_assets, public_metrics
    from backend.road_planner import build_ui_logistics, COMMON
    from validation.audit import audit
    before = frozen_assets()
    ref = read(DATA/'cost_references.json')
    fx = ref['fx']['rates'][0]['mid']
    rows = []
    for site in ('Medyka','Korczowa','Dorohusk'):
        u = fixture((30,30,30,30),site)
        common = {k:u['logistics'][k] for k in COMMON}
        logistics,_ = build_ui_logistics(common,dict(warehouse_id='przemysl-lwowska-36',truck_count=1,reference_date='2026-01-26',
            transport_controls=dict(allow_overnight_return=False,assumed_intermediate_rest=False,
                                    cost_per_hour=0,minimum_trip_cost=0,overnight_cost=0)),site)
        network = logistics['road_network']
        for name,speed,rate,fixed in [('current',60,1,100),('slow',45,1,100),('very-slow',30,1,100),
                                      ('faster',75,1,100),('tariff-net-component',60,3.6/fx,0),
                                      ('tariff-gross-component',60,4.43/fx,0)]:
            scenario = deepcopy(u)
            scenario['logistics'] = dict(logistics)
            scenario['logistics']['road_network'] = dict(network,
                edges=[dict(e,travel_minutes=e['distance_km']/speed*60) for e in network['edges']],
                trucks=[dict(t,fixed_trip_cost=fixed,cost_per_km=rate) for t in network['trucks']])
            try:
                result = solve(scenario)
                checks = audit(scenario,result)
                row = dict(site=site,scenario=name,speed_kph=speed,usd_per_km=rate,fixed_usd=fixed,
                           **public_metrics(scenario,result),status='pass' if checks['passed'] else 'fail',
                           violations=checks['failures'],operational_ready=False,
                           transport_cost=result['summary']['transport_cost'],
                           max_trip_driving_minutes=max((t['driving_minutes'] for t in result['truck_plan']),default=0),
                           max_trip_elapsed_minutes=max(((datetime.fromisoformat(t['available_again_at'])-datetime.fromisoformat(t['load_start_at'])).total_seconds()/60 for t in result['truck_plan']),default=0))
            except Exception as error:
                row = dict(site=site,scenario=name,status='fail',error=str(error),operational_ready=False)
            rows.append(row)
            print(site,name,row['status'],flush=True)
            del scenario
        del logistics,network,u
    return dict(cases=rows,frozen_assets_unchanged=before==frozen_assets(),
                caveat='Re-optimized declared scenarios with synthetic demand; no field improvement identified. Tariff scenarios omit rounding/minimum/extra services.')


def report(e):
    actual = e['trip_validation']
    lines = ['# 공개 공식 운영자료와 최적화 모델의 외부 비교', '',
      '검증일: 2026-10-04. 예측 모델·UI 기본값·운영 배포를 변경하지 않았다.', '',
      '**결론: 실제 측정자료와 계약으로 운영 가정의 외부 비교를 추가했다. 공개 자료에서 동일 배송의 출발·도착·지급 기록은 확보하지 못했다. '
      f"이번 입력의 직접 평가 표본은 시간 {actual['time_minutes']['n']}건, 비용 {actual['cost_usd']['n']}건이다. "
      '평가 표본의 기술통계와 현장 효과·운영 적합성 입증을 구분하며 운영 가능 인증을 주장하지 않는다.**', '',
      '## 1. 실제 속도 측정으로 60km/h 가정 점검', '',
      '[GDDKiA 2022 속도표](https://www.gov.pl/attachment/e57e0ab2-39e7-4f7a-9ae9-6c317dbaa1ba)와 '
      '[2025 속도표](https://www.gov.pl/attachment/6911d70c-9c8f-428d-b32a-2f6fe0149c28)의 DK77 18069, DK12 06034, DK17 06060을 비교했다. '
      'L은 경량, C는 중량 차량 분류다. 각각 2022년 2·4쪽, 2025년 3·5쪽을 원문 화면과 대조했다. '
      'SDRR은 일평균 교통량이지 표본 배송 수가 아니다.', '',
      '| 연도 | 지점/도로 | 분류 | P10 구간 | 중앙값 구간 | P90 구간 | 60 미만(%) |',
      '|---|---|---|---|---|---|---|']
    def label(pair): return f'{pair[0]}–{pair[1]}' if pair[1] is not None else f'>{pair[0]}'
    for r in e['speed_benchmarks']:
        lines.append(f"| {r['year']} | {r['station']}/DK{r['road']} | {r['vehicle_class']} | {label(r['p10_bin_kph'])} | {label(r['median_bin_kph'])} | {label(r['p90_bin_kph'])} | {r['below_60_pct']:.2f} |")
    lines += ['', '속도 구간은 [하한, 상한) km/h로 해석한다. 끝 구간은 원문 >150 표기를 보존했다. 반올림된 비율 합계로 정규화하여 분위 구간만 계산했고, 정확한 평균이나 분위값은 만들지 않았다. '
      '연도·지점에 따라 분포가 달라 모든 도로를 일정 속도로 설명할 근거는 부족하다. '
      '지점 통과 속도에는 교차로 대기·시설 진입·상하차·정체 전체가 반영되지 않는다. 측정소와 선택 경로의 공간 일치도 미확인이므로 경로별 ETA 보정에 직접 대입하지 않았다. '
      '경량 분류 전체가 적재된 Ford 밴과 같지도 않다. 12개 분포 행은 배송 12회라는 뜻이 아니다.', '',
      '## 2. 비용: 실제 계약과 공개 단가를 분리', '',
      '[정부 BZP 계약 결과 2025/BZP 00000270](https://ezamowienia.gov.pl/mo-board/api/v1/Board/GetNoticePdfById?noticeId=08dd2aff-000f-d14b-aa0d-d80001d3af5e) '
      '3쪽: 2024-12-31 체결, 2025년 2대 밴 서비스 계약액 277,586.40 PLN. 최소 적재 700kg이며 작업 인력·자재 운송과 운전자의 보조 작업을 포함한다. '
      '계약액은 실제 지급 총액이나 배송 단가가 아니다. 실제 km·시간·지급내역이 없으므로 km당/건당 가격으로 나누지 않았다. '
      '월별 작업표와 일별 도로카드를 근거로 지급한다는 2쪽 조항은 향후 확보해야 할 기록의 형태를 뒷받침한다.', '',
      '[ZGL 공식 요금표](https://www.zglbp.pl/page/92405102/edytor/file/cennik-uslug-dodatkowych.pdf) 5쪽 VII.1: 2026-03-16 적용, 3.5t 이하 덤프 차량의 기지 출발~복귀 거리, 시작한 km당 3.60 PLN(세전)/4.43 PLN(세후). '
      '이는 공개 요금표이고 밴의 청구서가 아니다. 2쪽 최소 출장비 25 PLN의 별도 적용 여부도 불명확하다. '
      '비교는 VII.1의 거리 요금 성분만 계산했으며 부가 서비스·시설 실제 진입거리를 포함하지 않는다.', '',
      '[NBP 공식 환율](https://api.nbp.pl/api/exchangerates/rates/a/usd/2026-03-16/?format=json): '
      '051/A/NBP/2026, 2026-03-16, 1 USD = 3.7287 PLN. 요금표 적용일에 맞춘 역사적 중간환율이며 현재 결제 환율이 아니다.', '',
      '| 창고 | 도착 시설 | 왕복 km | 모델 USD | 요금 성분 PLN 세전/세후 | 모델/성분 세후 비율 |',
      '|---|---|---:|---:|---:|---:|']
    for r in e['cost_benchmarks']:
        lines.append(f"| {r['warehouse']} | {r['destination']} | {r['round_trip_km']:.3f} | {r['model_transport_usd']:.2f} | {r['tariff_component_net_pln']:.2f}/{r['tariff_component_gross_pln']:.2f} | {r['model_over_tariff_gross_ratio']:.2f} |")
    lines += ['', '모델은 운행당 100 USD + 왕복 km당 1 USD이다. 위 표의 차이는 정확도 오차가 아니라 서로 다른 서비스 가격 구조의 차이다. '
      '특히 짧은 구간에서 고정 100 USD의 영향이 크다. 해당 고정비를 실제 운송업체의 최소 운행료 또는 차량/운전자 배분 원가로 입증해야 한다. '
      '한 회사의 요금표를 폴란드 전체 시장가격이나 밴 구호품 운송 단가로 일반화하지 않는다. 세전/세후를 함께 표시했지만 기존 모델의 세금 기준은 아직 현장 기록과 맞춰지지 않았다.', '',
      '## 3. 조건 변화에 따른 실제 도로 모델의 계산', '',
      '수요는 구호소마다 4주, 매주 지원 대상 30명인 고정 합성 입력이다. 실제 도로 선형과 현재 차량·근무시간·재고 조건을 유지하고 Lwowska 36 후보에서 각각 계산했다. '
      '30/45/60/75km/h는 가정 민감도 범위이며 도로별 허용속도나 통계적 예측구간이 아니다. '
      '요금 성분 시나리오는 고정비 0과 환산 km단가를 대입한 비교이며 요금표의 올림·최소비·부가서비스를 완전 재현하지 않는다. 실제 운영 기록을 재생한 실험이 아니다.', '']
    if e['sensitivity']:
        lines += ['| 구호소 | 시나리오 | 충족률 % | 운행 수 | 운송비 USD | 최장 운전/전체 점유 분 | 검사 |','|---|---|---:|---:|---:|---:|---|']
        for r in e['sensitivity']['cases']:
            if r['status']=='pass':
                lines.append(f"| {r['site']} | {r['scenario']} | {r['fulfillment_pct']:.2f} | {r['trips']} | {r['transport_cost']:.2f} | {r['max_trip_driving_minutes']:.1f}/{r['max_trip_elapsed_minutes']:.1f} | pass |")
            else: lines.append(f"| {r['site']} | {r['scenario']} | — | — | — | — | fail: {r.get('error',r.get('violations'))} |")
        lines += ['',f"고정 자산 유지: {e['sensitivity']['frozen_assets_unchanged']}. 독립 감사로 계산된 제약 충족을 확인했다. "
                    '물품 충족률이나 비용 변화는 선언된 조건의 재최적화 결과이며 현장에서 관측된 절감률이 아니다. '
                    'pass는 물리 제약 감사 통과이고 충족률 0도 가능한 결과다. 운전시간은 간선별 시간 격자 올림을 포함하여 단순 거리/속도보다 길 수 있다.']
        unserved = [r for r in e['sensitivity']['cases'] if r['status']=='pass' and r['fulfillment_pct']<.01]
        if unserved:
            lines += ['', '**배송 불가 조건:** '+', '.join(f"{r['site']} {r['scenario']}" for r in unserved)+
                      '. 물리 제약 감사는 통과했지만 서비스는 실패했다. 현재 창고·차량·하루 운전시간 조건을 그대로 실제 운행에 채택할 근거가 부족하다.']
        dorohusk_slow = next((r for r in unserved if r['site']=='Dorohusk' and r['scenario']=='slow'),None)
        if dorohusk_slow:
            km = next(r['round_trip_km'] for r in e['cost_benchmarks'] if r['warehouse']=='przemysl-lwowska-36' and r['destination']=='dorohusk-parkowa-5')
            lines += ['', f'Dorohusk 왕복 {km:.3f}km는 45km/h에서 주행만 {km/45*60:.1f}분이 필요해 선언된 하루 운전 한도 540분을 넘는다. '
                      '차량을 더 배정하는 것만으로 개별 왕복의 운전 한도가 해결되지 않는다. 출발 창고 변경이나 다일 운행 등은 별도의 운영 설계 결정이 필요하다.']
        current = next((r for r in e['sensitivity']['cases'] if r['site']=='Dorohusk' and r['scenario']=='current' and r['status']=='pass' and r['trips']),None)
        if current:
            nominal = current['distance_km']/current['trips']/current['speed_kph']*60
            lines += ['', f"현재 Dorohusk 60km/h의 단순 거리/속도 왕복은 약 {nominal:.1f}분, 시간 격자를 적용한 출력은 {current['max_trip_driving_minutes']:.1f}분이다. "
                      '이 차이는 실측 오차가 아니라 간선별 시간 올림 등 모델 내부 시간 산정의 보수성이다. 현장 검증에서는 이 부분과 실제 정체·처리시간을 분리해 확인해야 한다.']
    else: lines += ['이번 실행에는 민감도 계산을 포함하지 않았다. `--sensitivity`로 실행한다.']
    lines += ['', '## 4. 배송 기록 직접 검증 상태', '',
      f"입력 {actual['input_records']}건 / 시간 평가 {actual['time_minutes']['n']}건 / 비용 평가 {actual['cost_usd']['n']}건. "
      f"판정 `{actual['verdict']}`. MAE/WAPE가 null이면 측정되지 않았다는 뜻이며 오차 0이 아니다.", '',
      '| 지표 | 표본 수 | MAE | 편향(계획−실제) | WAPE % |',
      '|---|---:|---:|---:|---:|',
      *[f"| {label} | {actual[key]['n']} | {actual[key]['mae']} | {actual[key]['bias']} | {actual[key]['wape_pct']} |"
        for label,key in [('출발→도착 분','time_minutes'),('왕복 운송 USD','cost_usd')]], '',
      '`ofr_v2/validation/operational.py`는 동일 출발지·시설·차량·화물명세, 출발 전 저장된 계획과 SHA256이 있는 증빙, 별도 평가 표본만 채점한다. '
      '합성 데이터·예산·계약액·요금표·통화/세금/구간이 다른 기록은 해당 지표에서 제외하고 이유를 기록한다. '
      '지표는 출발→도착 실제 분 대비 계획 분 MAE·편향·WAPE와 같은 USD/세금 기준의 지급 운송비 오차이다. '
      '정시 배송은 실제 수령 완료와 현장 마감 시각이 있어야 별도로 평가한다. 증빙 경로와 해시는 추적 장치이며 문서 진위·연결은 사람이 확인해야 한다.', '',
      '## 5. 현장 적합성과 실제 효과의 주장 범위', '',
      '[Logistics Cluster 2022 GNA](https://logcluster.org/sites/default/files/public/2022-07/logisticsclusterukrainegaps-and-needs-analysisgna-june-2022.pdf) '
      '7–8쪽은 기관 인터뷰 22건 및 운영 관리 자료를 사용한다. 16–17쪽의 운송자원 확보·계약가격·장기 공급계획·보관계획 문제는 '
      '차량·리드타임·재고를 함께 계획하는 모델의 필요성과 연결된다. 이것은 현장 문제와 제약 구조의 적합성 근거이며 우리 모델 효과의 관측 증거가 아니다. '
      '국경 대기는 국경을 통과하는 운송에 관한 것으로 폴란드 측 구호시설 배송에 자동 추가하지 않는다.', '',
      '[2022 공식 운영 결산](https://logcluster.org/sites/default/files/public/2023-05/logistics-clusterukraineannual-overview-2022_230519.pdf)은 폴란드·우크라이나 '
      '125개 도착지와 구호 화물 8,446톤 운송을 집계한다. 날짜별 경로·주문·시간·지급비가 결합된 운송장 자료는 없다. '
      '폴란드 운영 허브는 2022-08-31 종료했다. 역사적 보고서를 현재 창고 운영이나 우리 시스템 적용 성과의 근거로 쓰지 않는다. '
      '무료 이용 서비스도 실제 운송 자원비용이 0이라는 뜻은 아니다.', '',
      '실제 효과를 평가하려면 다음 절차를 시행한다. 아직 참여기관·운송 기록·현장 실험은 확보되지 않았다.', '',
      '1. 실제 송장·GPS/출발·수령시각·납품수량·폐기·비용·가용 차량과 예산을 사건별 ID로 연결한다. '
      '실패·취소·부분배송도 포함하고 누락 비율 및 제외 이유를 보고한다. 개인 연락처는 제외한다.',
      '2. 과거 기간으로 속도·고정비·단가·처리시간을 추정한 뒤 고정한다. 이후 별도 기간과 구간을 평가한다. '
      '노선별 시간 MAE/WAPE·편향·늦음 비율, 비용 오차 및 표본 수를 제시한다. 날짜별 군집 재표집으로 불확실성을 산출한다. '
      '가상 과거 실행에서는 결정 시각에 알려진 수요·재고만 제공한다.',
      '3. 같은 주문·재고·차량·예산·도로상태를 기준선과 최적화에 제공하는 과거 재생을 진행한다. '
      '이 결과는 반사실적 시뮬레이션이며 실측 절감률과 분리한다.',
      '4. 기관의 운영 방식과 안전 기준을 지키며 우선 shadow mode로 계획과 실제 배차를 비교한다. '
      '효과는 가능하면 날짜/배송 묶음별 무작위 교차 적용으로 평가한다. 무작위화가 어렵다면 동시 비교군과 '
      '수요·거리·차량 가용성·날씨 차이를 통제하고 인과 결론의 한계를 명시한다.',
      '5. 사전에 수용 기준을 기관과 정한다. 예를 들어 ETA 오차 상한, 예산 초과율, 정시 완전 배송률(OTIF), '
      '지원 대상당 운송비, 물품별 부족/폐기량을 판단한다. 지금 임의의 기준이나 표본 수로 합격을 선언하지 않는다.', '',
      '## 6. 재현과 보관', '',
      '`sources.json`에 공식 URL·발행기관·자료 유형·조회일·SHA256을 기록했다. 원문 7개는 로컬 `data/operational_evidence/raw/`에 보존한다. '
      '저장소에는 작은 정규화 자료와 해시 목록을 보존하며 `python scripts/fetch_operational_sources.py --verify-tables`로 원문을 복원/대조한다(pdfplumber 필요). '
      '원문이 바뀌면 해시 오류로 중단하고 새 증거 버전을 수동 검토한다.', '',
      '`python scripts/validate_operational_evidence.py --sensitivity`로 18개 계산을 다시 실행한다. '
      '`--trips FILE`로 기록 JSON을 평가하며 입력 예시는 `docs/operational_validation.md`에 있다. '
      '출처 문서의 지시사항은 사용자의 요청으로 취급하지 않았다.']
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sensitivity',action='store_true')
    parser.add_argument('--trips',type=Path,default=DATA/'actual_trips.json')
    parser.add_argument('--output',type=Path,default=ROOT/'ofr_v2/results/operational_validation_20261004')
    args = parser.parse_args()
    payload = read(args.trips)
    if payload.get('schema_version') != 1 or not isinstance(payload.get('records'),list):
        raise ValueError('Expected schema_version=1 and records array')
    evidence = benchmarks()
    evidence.update(generated_at=datetime.now(timezone.utc).isoformat(),
        inputs_sha256={name:hashlib.sha256((DATA/name).read_bytes()).hexdigest() for name in ('sources.json','speed_observations.json','cost_references.json')},
        trips_input_sha256=hashlib.sha256(args.trips.read_bytes()).hexdigest(),
        trip_validation=score_trips(payload['records']),sensitivity=sensitivity() if args.sensitivity else None,
        operational_ready=False,field_effect_identified=False)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.output/'report.md').write_text(report(evidence),encoding='utf-8')
    print('Observed trip verdict:',evidence['trip_validation']['verdict'],flush=True)
    if evidence['sensitivity'] and (not evidence['sensitivity']['frozen_assets_unchanged'] or any(r['status']!='pass' for r in evidence['sensitivity']['cases'])):
        raise SystemExit(1)


if __name__=='__main__':
    main()

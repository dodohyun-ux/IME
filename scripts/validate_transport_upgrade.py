"""Paired actual-road / synthetic-demand regression; never claim observed savings."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from validate_optimizer import fixture, solve, public_metrics, frozen_assets
from backend.road_planner import build_ui_logistics, COMMON
from validation.audit import audit
from validation.operational import score_trips


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'ofr_v2/results/transport_upgrade_20261005')
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=True)
    before=frozen_assets(); rows=[]; failures=[]; schedules=[]
    for site in ('Medyka','Korczowa','Dorohusk'):
        for speed in (60,45,30):
            # Hold cost, demand, roads, departures, vehicle and duty limits constant.
            # Only the transport design differs in this paired comparison.
            for design in ('legacy','overnight-with-assumed-rest'):
                u=fixture((30,30,30,30),site)
                controls=dict(speed_kph=speed,fixed_trip_cost=100,cost_per_km=1,cost_per_hour=0,
                              overnight_cost=0,minimum_trip_cost=0,
                              allow_overnight_return=design!='legacy',assumed_intermediate_rest=design!='legacy')
                l,info=build_ui_logistics({k:u['logistics'][k] for k in COMMON},
                    dict(warehouse_id='przemysl-lwowska-36',truck_count=1,reference_date='2026-01-26',transport_controls=controls),site)
                u['logistics']=l
                row,schedule=evaluate(u,info,site,speed,design)
                rows.append(row)
                if row['status']!='pass': failures.append(row)
                if design!='legacy' and row.get('fulfillment_pct',0)<100-1e-5: failures.append(dict(service_failure=row))
                if site=='Dorohusk' and speed==30 and design!='legacy': schedules=schedule
                del u,l
    # Public tariff bases and a deliberately synthetic extras stress. They are
    # not paid invoice observations and are not used to estimate prediction error.
    for mode in ('public-distance-component','public-hour-rate-scenario','synthetic-extras-stress'):
        u=fixture((30,30,30,30),'Dorohusk')
        controls=dict(speed_kph=30)
        if mode=='public-hour-rate-scenario': controls.update(cost_per_km=0,cost_per_hour=228/3.7287)
        if mode=='synthetic-extras-stress': controls.update(fixed_trip_cost=25,cost_per_hour=2,minimum_trip_cost=100,overnight_cost=50)
        l,info=build_ui_logistics({k:u['logistics'][k] for k in COMMON},
            dict(warehouse_id='przemysl-lwowska-36',truck_count=1,reference_date='2026-01-26',transport_controls=controls),'Dorohusk')
        u['logistics']=l; row,schedule=evaluate(u,info,'Dorohusk',30,mode); rows.append(row)
        if mode=='public-distance-component':
            # Export the revised default cost, not the held-cost legacy pair.
            schedules=schedule
        if row['status']!='pass': failures.append(row)
        del u,l
    # Higher demand tests capacity limits; shortage is reported, not labelled
    # a service success simply because constraints are satisfied.
    for fleet in (1,2,3):
        u=fixture((250,250,250,250),'Dorohusk')
        l,info=build_ui_logistics({k:u['logistics'][k] for k in COMMON},
            dict(warehouse_id='przemysl-lwowska-36',truck_count=fleet,reference_date='2026-01-26',transport_controls=dict(speed_kph=30)),'Dorohusk')
        u['logistics']=l; row,_=evaluate(u,info,'Dorohusk',30,f'high-demand-{fleet}-vans'); rows.append(row)
        if row['status']!='pass': failures.append(row)
        del u,l
    sources=ROOT/'ofr_v2/data/operational_evidence/transport_upgrade_sources.json'
    actual=ROOT/'ofr_v2/data/operational_evidence/actual_trips.json'
    evidence=dict(generated_at=datetime.now(timezone.utc).isoformat(),cases=rows,failures=failures,
                  physical_passed=sum(r['status']=='pass' for r in rows),case_count=len(rows),
                  frozen_assets_unchanged=before==frozen_assets(),frozen_assets=before,
                  source_facts=json.loads(sources.read_text(encoding='utf-8')),
                  source_facts_sha256=hashlib.sha256(sources.read_bytes()).hexdigest(),
                  operating_record_sha256=hashlib.sha256(actual.read_bytes()).hexdigest(),
                  trip_validation=score_trips(json.loads(actual.read_text(encoding='utf-8'))['records']),
                  operational_ready=False,field_effect_identified=False)
    if not evidence['frozen_assets_unchanged']: failures.append(dict(error='Assets changed during validation'))
    (args.output/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.output/'dorohusk_30_truck_schedule.json').write_text(json.dumps(schedules,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.output/'report.md').write_text(report(evidence),encoding='utf-8')
    print(f"Completed {len(rows)} cases; {len(failures)} failures; no observed operating trips.",flush=True)
    return int(bool(failures))


def evaluate(u,info,site,speed,design):
    try:
        r=solve(u); a=audit(u,r)
        row=dict(site=site,speed_kph=speed,design=design,**public_metrics(u,r),
                 transport_cost_usd=r['summary']['transport_cost'],physical_checks=a['total_checks'],
                 status='pass' if a['passed'] else 'fail',violations=a['failures'],
                 overnight_trips=sum(p['overnight_return'] for p in r['truck_plan']),
                 max_round_trip_driving_minutes=max((p['driving_minutes'] for p in r['truck_plan']),default=0),
                 assumed_rest_nodes=info['assumed_rest_nodes'],transport_controls=info['transport_controls'],
                 observed_delivery=False,all_in_cost_validated=False)
        schedules=[]
        for p in r['truck_plan']:
            fields=('trip_id','truck_id','cargo','cargo_units','departure_at','arrival_at','delivery_complete_at',
                    'return_at','available_again_at','round_trip_distance_km','driving_minutes',
                    'billable_hours','transport_cost','cost_breakdown','outbound_edges','return_edges')
            schedules.append(dict({k:p[k] for k in fields},
                                  rest_events=[e for e in p['timeline'] if e['kind'] in ('break','daily_rest')],
                                  warehouse_id=info['warehouse_id'],destination_site=site,
                                  assumed_rest_nodes=info['assumed_rest_nodes']))
    except Exception as error:
        row=dict(site=site,speed_kph=speed,design=design,status='fail',error=str(error)); schedules=[]
    print(site,speed,design,row['status'],row.get('fulfillment_pct'),flush=True)
    return row,schedules


def report(e):
    lines=['# Dorohusk 저속 운송조건·비용 모델 수정 검증', '',
           '검증일: 2026-10-05. 실제 도로 선형 + 합성 수요. 예측 모델 수정·추론·학습 없음.', '',
           f"물리·비용 독립 감사 {e['physical_passed']}/{e['case_count']} 통과. 검증 중 자산 해시 유지: {e['frozen_assets_unchanged']}.", '',
           '## 비교 조건과 결과', '',
           '창고 Lwowska 36, 차량 1대, 매주 구호 이용자 30명/체류 1일의 합성 수요를 사용했다. '
           '짝 비교는 속도·비용(100 USD+1 USD/km)·도로·차량·공급·예산·출발 후보를 같게 유지하고 '
           '다음 근무일 복귀 및 중간 휴식 노드 가정만 변경했다. 비용 현실화 효과와 운송 설계 효과를 섞지 않았다.', '',
           '| 도착지 | 속도 | 설계 | 운행 | 야간 복귀 | 수요 충족 % | 운송 USD | 물리 감사 |',
           '|---|---:|---|---:|---:|---:|---:|---|']
    for r in e['cases']:
        if r['status']=='pass': lines.append(f"| {r['site']} | {r['speed_kph']} | {r['design']} | {r['trips']} | {r['overnight_trips']} | {r['fulfillment_pct']:.2f} | {r['transport_cost_usd']:.2f} | pass |")
        else: lines.append(f"| {r['site']} | {r['speed_kph']} | {r['design']} | | | | | FAIL {r.get('error',r.get('violations'))} |")
    lines += ['', '충족률은 품목별 총수요로 정규화한 미충족률의 평균을 100에서 뺀 값이다. 감사 통과와 전량 배송은 다르다. '
              'high-demand는 매주 250명, 차량 1~3대 조건으로 자원 부족을 노출한다.', '',
              '## 적용한 운송조건', '',
              '하루 안에 왕복 가능한 운행을 우선 사용한다. 불가능하면 출고·배송은 첫 근무, 도착지 휴식 11~36시간, '
              '공차 복귀는 바로 다음 근무로 제한한다. 각 근무의 주행 9시간, 연속 주행 4.5시간/휴식 45분, '
              '주·2주 주행 한도, 차량 복귀 전 재사용 금지와 재고 기한·예산은 그대로 검사한다. '
              '[EU 공식 설명](https://transport.ec.europa.eu/transport-modes/road/social-provisions/driving-time-and-rest-periods_en)을 '
              '참고한 보수적 정책이며 이 국내 밴 운행에 모든 조항이 법적으로 적용된다는 판단은 아니다. '
              '중간 휴식은 선택 경로의 누적 반올림 주행시간 절반에 가까운 도로 노드의 시나리오 가정이다. '
              '실제 시설·허가를 확인한 지점이 아니며 가정을 끄면 운행이 다시 불가능할 수 있다. '
              '주말을 건너뛰는 대기, 편도 자체가 근무 한도를 넘는 경로, 일반 다일 VRP는 지원하지 않는다. '
              '경로 최적성은 k=1 최단거리 후보와 시간 격자에 조건부다.', '',
              '## 비용의 근거와 한계', '',
              '근거 없는 고정 100 USD 기본값을 제거하고 '
              '[PGKiM Lubsko 공식 요금표](https://www.pgkimlubsko.pl/cennik.html)의 3.5t 이하 밴 세전 8.50 PLN/km '
              '(2025-02-03 적용)를 거리 성분 참고값으로 사용했다. '
              '[NBP 2026-03-16 환율](https://api.nbp.pl/api/exchangerates/rates/a/usd/2026-03-16/?format=json) '
              '3.7287 PLN/USD로 환산한 약 2.280 USD/km다. 이 환율은 날짜가 지정된 평가 기준이다. '
              '별도 228 PLN/h는 같은 요금표의 시간 기준이며 거리비에 자동 합산할 근거가 없어 시간 기준 시나리오에서만 사용했다. '
              '상하차 포함 여부·야간 대기·최소요금·거리 기점·최신 가격·계약 조건은 이 자료로 확정되지 않는다.', '',
              '`max(최소 운행비, 고정비+왕복거리×km단가+청구시간×시간단가)+야간 추가비+통행료`를 계산한다. '
              '청구시간은 적재 시작~복귀에서 도착지 야간 휴식을 제외하며 복귀 후 창고 휴식/회전은 제외하는 프로젝트 규칙이다. '
              '공개 시간 요금표의 실제 청구 규칙으로 검증된 것은 아니다. 추가 비용 기본 0은 제외 항목이라는 뜻이며 무료라는 증거가 아니다. '
              'synthetic-extras-stress의 25 USD 고정/2 USD 시간/100 USD 최소/50 USD 야간은 수학 검증용 가상 견적이다. '
              '세금·숙박·기사·기타 비용과 공급업체 USD 비용의 세금 범위도 견적에 맞춰 일치시켜야 한다. '
              '어느 결과도 실제 지급액 오차나 절감액으로 해석할 수 없다.', '',
              '## 실측 검증 상태', '',
              f"실제 배송시간 대응 표본 {e['trip_validation']['time_minutes']['n']}건, 지급비용 대응 표본 {e['trip_validation']['cost_usd']['n']}건. MAE/WAPE는 계산 불가(null). 현장 효과 미입증.", '',
              '추가 조사한 [Logistics Cluster 2026-04-07 현장 회의](https://logcluster.org/en/documents/ukraine-coordination-meeting-minutes-sloviansk-7-april-2026)와 '
              '[4년 운영 요약](https://logcluster.org/en/stories/four-years-coordinating-humanitarian-logistics-ukraine-turning-coordination-impact)은 '
              '누적 활동·운영 지침이며 동일 배송의 출발/도착/인수/지급액을 제공하지 않는다. '
              '국경 너머 우크라이나 컨보이의 신청 리드타임을 폴란드 국내 주행시간으로 대입하지 않았다. '
              '[Chełm 시 공식 창고 안내](https://samorzad.gov.pl/web/miasto-chelm/punkt-magazynowy-dla-ciezarowek-w-chelmskim-centrum-aktywnosci-gospodarczej)의 '
              'Ceramiczna 5 후보는 현재 운영·좌표·실제 도로 연결을 확보하지 못해 모델에 넣지 않았다.', '',
              '원문 다운로드/주소 API는 이번 실행에서 네트워크 오류로 실패했다. 새 요금표의 정규화 사실·웹 검토일·URL을 '
              '`transport_upgrade_sources.json`에 기록했고 원문 바이트 SHA 확보를 주장하지 않는다. 기존 NBP 원문 해시와 공식 도로 스냅샷은 보존했다.', '',
              '실측 채점기는 출발 전 계획·운송장/차량/화물/구간·시간대·지급 증빙과 비용 범위를 대조한다. '
              '운영 기록이 없는 상태에서는 이 검사 구현과 합성 검증으로 실제 정확도를 증명할 수 없다. '
              '인수 기록의 시간·물량과 기존 배차 방식의 비교가 있어야 정시 인수율·비용/인수량·부족률 개선을 평가할 수 있다. '
              '공개 집계로 현장 효과를 추정하거나 기록을 만들어 넣지 않았다.', '',
              '## 재현', '', '`python scripts/validate_transport_upgrade.py --output <directory>`', '',
              '`python -m pytest ofr_v2/tests/test_transport_upgrade.py -q`', '',
              '코드와 독립 감사는 야간 휴식 누락·잘못된 위치/길이·근무 밖 복귀·중복 차량 사용·주행 한도·예산·비용 성분 오류를 검사한다. '
              '`dorohusk_30_truck_schedule.json`에 차량별 물품 수량·출발/배송/복귀·실제 도로 edge 경로·가정 휴식·비용 성분을 저장했다. '
              '운영 인증 자료가 아닌 재현 가능한 시나리오 산출물이다.', '']
    return '\n'.join(lines)


if __name__=='__main__': raise SystemExit(main())

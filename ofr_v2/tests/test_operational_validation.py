"""Fabricated unit fixtures test scoring safeguards; they are not field evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'ofr_v2'))
sys.path.insert(0,str(ROOT/'scripts'))
from validation.operational import score_trips, quantile_bin
from validate_operational_evidence import benchmarks, report


def unit_fixture():
    common = dict(origin_id='unit-depot',destination_id='unit-site',vehicle_id='unit-van',cargo_manifest_id='unit-cargo',
                  time_scope='departure_to_arrival',currency='USD',tax_basis='net',cost_scope='round_trip_transport',
                  departure_at='2026-01-01T09:00:00+01:00')
    return dict(trip_id='unit-1',data_kind='observed_trip',split='evaluation',plan_recorded_at='2026-01-01T07:00:00Z',
        actual_evidence=dict(reference='fabricated-unit-document',sha256='a'*64),
        plan_evidence=dict(reference='fabricated-unit-plan',sha256='b'*64),
        predicted=dict(common,arrival_at='2026-01-01T10:00:00+01:00',transport_cost=100),
        actual=dict(common,arrival_at='2026-01-01T09:20:00Z',transport_cost=80,cost_evidence_kind='paid_invoice'))


def test_empty_does_not_mean_perfect_accuracy():
    r = score_trips([])
    assert r['time_minutes']==dict(n=0,mae=None,bias=None,wape_pct=None)
    assert r['cost_usd']['mae'] is None and not r['field_effect_identified'] and not r['operational_ready']


def test_timezone_and_hand_calculated_errors():
    r = score_trips([unit_fixture()])
    assert r['time_minutes']['n']==1
    assert r['time_minutes']['mae']==20 and r['time_minutes']['bias']==-20
    assert r['time_minutes']['wape_pct']==25
    assert r['cost_usd']['mae']==20 and r['cost_usd']['bias']==20 and r['cost_usd']['wape_pct']==25
    assert not r['operational_ready'] and not r['field_effect_identified']


@pytest.mark.parametrize('change', ['synthetic','late-plan','naive-timestamp','different-endpoint','different-cargo','calibration','no-proof','bad-proof'])
def test_invalid_common_evidence_is_excluded(change):
    r = unit_fixture()
    if change=='synthetic': r['data_kind']='synthetic_test'
    if change=='late-plan': r['plan_recorded_at']='2026-01-01T11:00:00+01:00'
    if change=='naive-timestamp': r['actual']['departure_at']='2026-01-01T09:00:00'
    if change=='different-endpoint': r['actual']['destination_id']='other'
    if change=='different-cargo': r['actual']['cargo_manifest_id']='other'
    if change=='calibration': r['split']='calibration'
    if change=='no-proof': del r['actual_evidence']
    if change=='bad-proof': r['actual_evidence']['sha256']='not-a-hash'
    scored = score_trips([r])
    assert scored['time_minutes']['n']==scored['cost_usd']['n']==0
    assert scored['exclusions']


@pytest.mark.parametrize('change',['award','tax','currency','scope','nan','negative','bool'])
def test_cost_incompatibility_cannot_contaminate_valid_time(change):
    r = unit_fixture()
    if change=='award': r['actual']['cost_evidence_kind']='awarded_contract'
    if change=='tax': r['actual']['tax_basis']='gross'
    if change=='currency': r['actual']['currency']='PLN'
    if change=='scope': r['actual']['cost_scope']='procurement_and_transport'
    if change=='nan': r['actual']['transport_cost']=float('nan')
    if change=='negative': r['actual']['transport_cost']=-1
    if change=='bool': r['actual']['transport_cost']=True
    scored = score_trips([r])
    assert scored['time_minutes']['n']==1 and scored['cost_usd']['n']==0
    assert scored['exclusions'][0]['metric']=='cost'


def test_duplicate_ids_and_nonobjects_not_double_counted():
    r = score_trips([unit_fixture(),unit_fixture(),None])
    assert r['cost_usd']['n']==1 and len(r['exclusions'])==2


def test_zero_actual_cost_avoids_division_by_zero():
    row = unit_fixture();row['actual']['transport_cost']=0
    r = score_trips([row])
    assert r['cost_usd']['mae']==100 and r['cost_usd']['wape_pct'] is None


def test_rounded_binned_distributions_and_open_tail():
    assert quantile_bin([0]*13+[100],.5)==(150,None)
    assert quantile_bin([100]+[0]*13,.5)==(0,30)
    with pytest.raises(ValueError): quantile_bin([1]*14,.5)


def test_pinned_public_benchmarks_are_proxies_not_delivery_accuracy():
    e = benchmarks()
    assert e['speed_row_count']==12 and e['independent_observed_delivery_count']==0
    assert all(not r['route_matched'] for r in e['speed_benchmarks'])
    station = next(r for r in e['speed_benchmarks'] if r['year']==2025 and r['station']=='18069' and r['vehicle_class']=='L')
    assert station['median_bin_kph']==(60,70) and station['below_60_pct']==22.78
    med = next(r for r in e['cost_benchmarks'] if r['warehouse']=='przemysl-lwowska-36' and r['destination']=='medyka-hall-293')
    assert med['tariff_component_net_pln']==75.6
    assert med['tariff_component_gross_pln']==93.03
    assert med['model_transport_usd']==pytest.approx(120.53805041333626)
    assert not med['observed_cost']
    assert score_trips(json.loads((ROOT/'ofr_v2/data/operational_evidence/actual_trips.json').read_text())['records'])['time_minutes']['n']==0


def test_report_uses_supplied_record_counts_and_metrics():
    e = benchmarks()
    e.update(trip_validation=score_trips([unit_fixture()]),sensitivity=None)
    text = report(e)
    assert '시간 1건, 비용 1건' in text
    assert '| 출발→도착 분 | 1 | 20.0 | -20.0 | 25.0 |' in text
    assert '이번 실행에는 민감도 계산을 포함하지 않았다' in text
    assert '배송 불가 조건:' not in text

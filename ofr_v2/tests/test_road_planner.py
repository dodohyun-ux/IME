"""UI adapters: calendar alignment, real geometry and bounded fleet, not forecast scoring."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from backend.optimization import example_inputs, optimize_relief_plan, InputValidationError
from backend.logistics import example_logistics
from backend.road_planner import COMMON, build_ui_logistics, planning_calendar, road_options


def common(site='Medyka'):
    full = example_logistics(site)
    return {k:full[k] for k in COMMON}


@pytest.mark.parametrize('reference,offset', [('2026-01-26','+01:00'), ('2026-03-23','+02:00'), ('2026-10-19','+01:00'), ('2026-03-09','+01:00'), ('2026-10-05','+02:00')])
def test_forecast_next_week_calendar_and_dst(reference, offset):
    start, days, hour = planning_calendar(reference)
    assert (start.date()-datetime.fromisoformat(reference).date()).days == 7
    assert start.isoformat().endswith(offset)
    for d in days:
        instant = start.astimezone(timezone.utc).timestamp() + hour(d,9)*3600
        local = datetime.fromtimestamp(instant,start.tzinfo)
        assert local.hour==9 and local.weekday()<5


@pytest.mark.parametrize('reference', ['2026-01-27', '2026-02-30', '2026-1-26', 'not-a-date'])
def test_calendar_rejects_bad_reference(reference):
    with pytest.raises(InputValidationError): planning_calendar(reference)


def test_preset_accounts_for_driver_without_inventing_official_payload():
    p = road_options()['preset']; v = p['vehicle']
    assert v['tare_kg']==p['published_kerb_weight_kg']+p['driver_allowance_kg']
    assert v['payload_kg']==v['max_gross_weight_kg']-v['tare_kg']==1235
    assert p['source_url'].startswith('https://www.ford.co.uk/')


def test_actual_geometry_ui_adapter_max_fleet_and_cargo_schedule():
    planning = dict(reference_date='2026-01-26',warehouse_id='przemysl-lwowska-36',truck_count=3)
    logistics, info = build_ui_logistics(common(), planning, 'Medyka')
    network=logistics['road_network']
    assert info['planning_start']=='2026-02-02T00:00:00+01:00'
    assert len(network['departure_hours'])==8
    assert len(network['trucks'])==3
    assert network['data_kind']=='official_geometry_scenario'
    forecast,user,volume=example_inputs()
    user['initial_inventory']['Medyka']={i:0 for i in volume}; logistics['initial_lots']=[]
    result=optimize_relief_plan(forecast,user,volume,logistics=logistics)
    assert result['truck_plan']
    assert not result['model_info']['operational_ready']
    assert all(t['weight_kg']<=1235+1e-6 for t in result['truck_plan'])
    assert all(datetime.fromisoformat(t['departure_at'])>=datetime.fromisoformat(info['planning_start']) for t in result['truck_plan'])
    # Request controls must not mutate the cached pair or leak into a later plan.
    one,_=build_ui_logistics(common(), dict(planning,truck_count=1,reference_date='2026-02-02'), 'Medyka')
    assert len(one['road_network']['trucks'])==1
    assert logistics['road_network']['planning_start'] != one['road_network']['planning_start']


@pytest.mark.parametrize('count', [0,4,1.5,True])
def test_bad_fleet_fails_before_geometry_loading(count):
    with pytest.raises(InputValidationError):
        build_ui_logistics(common(),dict(reference_date='2026-01-26',warehouse_id='unknown',truck_count=count),'Medyka')


def test_ui_mode_rejects_legacy_route_collision():
    with pytest.raises(InputValidationError):
        build_ui_logistics(example_logistics(),dict(reference_date='2026-01-26',warehouse_id='unknown',truck_count=1),'Medyka')

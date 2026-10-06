"""Exercise HTTP optimize wiring; forecast model loading is isolated, not scored."""
import importlib
from pathlib import Path
import sys

import joblib
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from backend.optimization import example_inputs
from backend.logistics import example_logistics
from backend.road_network import example_road_logistics


@pytest.fixture
def client():
    # Exercise current HTTP wiring with the provided bundle; this suite does not score forecasts.
    sys.modules.pop('backend.main', None)
    module = importlib.import_module('backend.main')
    return TestClient(module.app)


def request():
    forecast, user, volume = example_inputs()
    return dict(user, ml_forecast=forecast, item_volume_m3=volume)


def test_legacy_http_contract(client):
    response = client.post('/optimize', json=request())
    assert response.status_code == 200
    assert not response.json()['model_info'].get('logistics_enabled', False)


@pytest.mark.parametrize('field,value', [('stay_days', True), ('total_budget', True),
                                        ('utilization_rate', True), ('unexpected_budget', 100)])
def test_optimize_rejects_silent_scalar_coercion_and_unknown_fields(client, field, value):
    body = request(); body[field] = value
    assert client.post('/optimize', json=body).status_code == 422


@pytest.mark.parametrize('field', ['ml_forecast', 'weekly_supply'])
def test_duplicate_normalized_week_keys_are_not_silently_overwritten(client, field):
    body = request()
    group = 'Medyka' if field == 'ml_forecast' else 'water'
    body[field][group]['01'] = 999
    response = client.post('/optimize', json=body)
    assert response.status_code == 400, response.text
    assert 'duplicate' in response.json()['detail'].lower()


@pytest.mark.parametrize('controls',[{'cost_per_km':True},{'allow_overnight_return':1},{'speed_kph':29},{'unknown':1}])
def test_transport_controls_rejected_at_http_boundary(client,controls):
    body=request(); body['road_planning']=dict(warehouse_id='przemysl-lwowska-36',truck_count=1,reference_date='2026-01-26',transport_controls=controls)
    assert client.post('/optimize',json=body).status_code==422


def test_logistics_http_contract_and_cost_components(client):
    body = request(); body['logistics'] = example_logistics()
    response = client.post('/optimize', json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['model_info']['logistics_enabled']
    assert len(data['transport_plan']) == 4
    s = data['summary']
    assert s['total_cost'] == pytest.approx(s['total_procurement_cost'] + s['transport_cost'] + s['disposal_cost'])


def test_invalid_logistics_is_400(client):
    body = request(); body['logistics'] = example_logistics()
    body['logistics']['vehicles']['truck']['payload_kg'] = 0
    assert client.post('/optimize', json=body).status_code == 400


def test_closed_routes_and_no_opening_stock_produce_shortage(client):
    body = request(); body['logistics'] = example_logistics()
    body['initial_inventory']['Medyka'] = {i: 0 for i in body['item_volume_m3']}
    body['logistics']['initial_lots'] = []
    body['logistics']['routes'][0]['max_trips'] = {w:0 for w in range(1,5)}
    response = client.post('/optimize', json=body)
    assert response.status_code == 200, response.text
    assert response.json()['summary']['overall_weighted_fulfillment_rate'] == pytest.approx(0)


def road_request():
    body=request()
    body['ml_forecast']={'Medyka':{1:50,2:0,3:0,4:0}}
    body['utilization_rate']=.2; body['stay_days']=1
    body['initial_inventory']['Medyka']={i:0 for i in body['item_volume_m3']}
    body['weekly_supply']={i:{w:10 if i=='food' and w==1 else 0 for w in range(1,5)}
                           for i in body['item_volume_m3']}
    body['logistics']=example_road_logistics()
    body['logistics']['initial_lots']=[]
    return body


def test_road_network_http_returns_serializable_individual_truck_plan(client):
    response=client.post('/optimize',json=road_request())
    assert response.status_code==200,response.text
    data=response.json()
    assert data['model_info']['road_network_enabled']
    assert len(data['truck_plan'])==1
    assert data['truck_plan'][0]['cargo']['food']==10
    assert data['truck_plan'][0]['departure_at'].endswith('+00:00')


def test_invalid_road_network_http_returns_400(client):
    body=road_request()
    body['logistics']['road_network']['edges'][0]['max_height_m']=-1
    assert client.post('/optimize',json=body).status_code==400


def test_no_road_path_http_reports_shortage_without_fabricated_trip(client):
    body=road_request()
    for e in body['logistics']['road_network']['edges']: e['open_windows']=[]
    response=client.post('/optimize',json=body)
    assert response.status_code==200,response.text
    assert response.json()['truck_plan']==[]
    assert response.json()['summary']['overall_weighted_fulfillment_rate']==0


def test_road_options_and_simplified_ui_request(client):
    options=client.get('/road-options')
    assert options.status_code==200
    assert len(options.json()['warehouses'])==2
    body=road_request()
    del body['logistics']['road_network']
    body['road_planning']=dict(warehouse_id='przemysl-lwowska-36',truck_count=1,reference_date='2026-01-26')
    response=client.post('/optimize',json=body)
    assert response.status_code==200,response.text
    result=response.json()
    assert result['road_scenario']['planning_start']=='2026-02-02T00:00:00+01:00'
    assert result['road_scenario']['vehicle_preset']['vehicle']['payload_kg']==1235
    assert result['truck_plan'][0]['cargo']['food']==10
    assert result['truck_plan'][0]['outbound_geometry']


@pytest.mark.parametrize('count',[0,4,1.5,True])
def test_ui_fleet_schema_rejects_invalid_values(client,count):
    body=request()
    body['road_planning']=dict(warehouse_id='przemysl-lwowska-36',truck_count=count,reference_date='2026-01-26')
    assert client.post('/optimize',json=body).status_code==422


def test_ui_reference_and_mode_collision_fail_without_route_fallback(client):
    body=road_request(); del body['logistics']['road_network']
    body['road_planning']=dict(warehouse_id='przemysl-lwowska-36',truck_count=1,reference_date='2026-01-27')
    assert client.post('/optimize',json=body).status_code==400
    body['road_planning']['reference_date']='2026-01-26'
    body['logistics']=example_logistics()
    assert client.post('/optimize',json=body).status_code==400

@pytest.mark.parametrize('road', [False, True])
def test_efficiency_result_describes_only_executed_objectives(client, road):
    body = road_request() if road else request()
    body['priority'] = 'efficiency'
    response = client.post('/optimize', json=body)
    assert response.status_code == 200, response.text
    info = response.json()['model_info']
    assert info['priority'] == 'efficiency'
    assert 'fairness' not in info['optimization_method'].lower()
    assert 'maximum cell-level' not in info['optimization_method'].lower()
    assert 'stage_1_max_unmet_rate' not in info['stage_objectives']

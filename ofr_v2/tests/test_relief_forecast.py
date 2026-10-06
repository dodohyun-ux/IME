"""Contract and chronology checks using the actual supplied model bundle."""
from copy import deepcopy
from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from backend import main
from backend import relief_forecast as team

@pytest.fixture(scope='module')
def client():
    return TestClient(main.app)

@pytest.fixture
def body(client):
    h=client.get('/history',params={'reference_date':'2026-01-26'}).json()
    return {'reference_date':'2026-01-26','hub_inflow':h['hub_inflow']}

def test_weekly_input_is_oldest_first_daily_and_first_forecast_is_next_monday():
    daily=team.weekly_to_daily([700,1400])
    assert len(daily)==14
    assert daily[:7]==[200.0]*7 and daily[-7:]==[100.0]*7


def test_fresh_bundle_predictions_reconcile_dates_counts_and_provenance(client,body):
    r=client.post('/predict',json=body);assert r.status_code==200
    d=r.json();assert d['source']=='relief_model' and d['accuracy'] is None
    assert d['model_sha256']==main.MODEL_SHA256
    for i in range(4):assert d[f'week{i+1}']==sum(d['hub_forecast'][h][i] for h in main.HUBS)
    assert d['input_provenance']['hub_inflow']==body['hub_inflow']
    assert d['input_provenance']['forecast_dates']==['2026-02-02','2026-02-09','2026-02-16','2026-02-23']
    assert all(d['intervals'][i]['low']<=d[f'week{i+1}']<=d['intervals'][i]['high'] for i in range(4))


def test_recent_input_change_affects_own_hub_without_cross_hub_leakage(client,body):
    a=client.post('/predict',json=body).json()
    b=deepcopy(body);b['hub_inflow']['medyka'][0]*=2
    d=client.post('/predict',json=b).json()
    assert a['hub_forecast']['medyka']!=d['hub_forecast']['medyka']
    for h in ['dorohusk','korczowa']:assert a['hub_forecast'][h]==d['hub_forecast'][h]
    assert client.post('/predict',json=body).json()['hub_forecast']==a['hub_forecast']


def test_removed_hidden_history_is_rejected(client,body):
    for h in main.HUBS:body['hub_inflow'][h]+=[1000]*6
    assert client.post('/predict',json=body).status_code==400


@pytest.mark.parametrize('change',[{'reference_date':'2026-01-27'},{'reference_date':'invalid'},
    {'hub_inflow':{'medyka':[1]*2}}, {'hub_inflow':{'medyka':[True]*2,'dorohusk':[1]*2,'korczowa':[1]*2}},
    {'unexpected':1}])
def test_invalid_contracts_are_rejected(client,body,change):
    body.update(change);assert client.post('/predict',json=body).status_code in (400,422)


@pytest.mark.parametrize('values',[[1],[1]*3,[-1,1]])
def test_exact_two_nonnegative_weeks_required(client,body,values):
    body['hub_inflow']['medyka']=values
    assert client.post('/predict',json=body).status_code==400


def test_missing_later_history_is_blank_and_manual_future_reference_works(client,body):
    date=client.get('/meta').json()['last_reference']
    h=client.get('/history',params={'reference_date':date}).json()
    if date>main.WEEKLY.index[-1].strftime('%Y-%m-%d'):
        assert all(v is None for row in h['hub_inflow'].values() for v in row)
        assert client.post('/predict',json={'reference_date':date}).status_code==400
    body['reference_date']=date
    assert client.post('/predict',json=body).status_code==200


def test_supplied_conflict_accepts_reference_week_and_legacy_four_rows(client,body):
    body['conflict']=[{'events':1000,'deaths':100}]
    single=client.post('/predict',json=body);assert single.status_code==200
    data=single.json()
    assert data['input_provenance']['conflict']==body['conflict']
    assert data['input_provenance']['effective_conflict_history_weeks']==1
    assert data['input_provenance']['conflict_mode']=='user_supplied'
    assert '입력한 기준 주 분쟁 사건 수·사망자 수를 반영했습니다.' in data['warning']
    assert '현재 UI는 분쟁 정보를 입력하지 않아' not in data['warning']
    body['conflict']*=4
    legacy=client.post('/predict',json=body);assert legacy.status_code==200
    assert legacy.json()['hub_forecast']==data['hub_forecast']


def test_only_reference_conflict_changes_actual_model_predictions(client,body):
    body['conflict']=[{'events':1000,'deaths':100}]*4
    baseline=client.post('/predict',json=body).json()['hub_forecast']
    body['conflict']=[body['conflict'][0]]+[{'events':4000,'deaths':1000}]*3
    older=client.post('/predict',json=body).json()['hub_forecast']
    assert older==baseline
    body['conflict'][0]={'events':4000,'deaths':1000}
    newer=client.post('/predict',json=body).json()['hub_forecast']
    assert newer!=baseline
    assert {h:info['conflict_lag_days'] for h,info in team.MODELS.items()}=={'medyka':2,'dorohusk':1,'korczowa':2}


def test_conflict_inputs_remain_strict_and_unsupported_lengths_rejected(client,body):
    body['conflict']=[{'events':100,'deaths':100}]*4
    for n in (0,2,3,5):
        body['conflict']=[{'events':100,'deaths':100}]*n
        assert client.post('/predict',json=body).status_code==400
    for row in ({'events':-1,'deaths':100},{'events':True,'deaths':100},{'events':'100','deaths':100}):
        body['conflict']=[row]
        assert client.post('/predict',json=body).status_code==422


def test_actual_estimator_uses_recent_daily_features_and_recursive_feedback(client,body,monkeypatch):
    estimator=team.MODELS['medyka']['model'];original=estimator.predict;rows=[];outputs=[]
    def observed(X):
        rows.append(X.copy());pred=original(X);outputs.append(pred[0]);return pred
    monkeypatch.setattr(estimator,'predict',observed)
    response=client.post('/predict',json=body);assert response.status_code==200
    assert len(rows)==28
    assert rows[0]['dow'].iloc[0]==0 and rows[0]['month'].iloc[0]==2
    assert rows[0]['target_lag_1'].iloc[0]==pytest.approx(body['hub_inflow']['medyka'][0]/7)
    assert rows[0]['target_lag_14'].iloc[0]==pytest.approx(body['hub_inflow']['medyka'][1]/7)
    assert rows[1]['target_lag_1'].iloc[0]==pytest.approx(team.inverse_target(outputs[0]))


def test_target_actuals_do_not_leak_into_model_inputs(client,body,monkeypatch):
    before=client.post('/predict',json=body).json()
    changed=main.WEEKLY.copy()
    for h in main.HUBS:
        for k in range(1,5):
            week=main.pd.Timestamp(body['reference_date'])+main.pd.Timedelta(weeks=k)
            changed.at[week,h]*=10
    monkeypatch.setattr(main,'WEEKLY',changed)
    after=client.post('/predict',json=body).json()
    assert after['hub_forecast']==before['hub_forecast']
    assert after['hub_actual']!=before['hub_actual']


def test_edited_history_is_labeled_and_not_shown_as_matched_observed_validation(client,body):
    body['hub_inflow']['medyka'][0]*=2
    result=client.post('/predict',json=body).json()
    assert result['source']=='relief_model_edited' and result['hub_actual'] is None
    assert result['input_provenance']['input_origin']=='dataset_edit'


def test_two_week_contract_preserves_previously_verified_eight_week_prediction(client,body):
    response=client.post('/predict',json=body)
    assert response.json()['hub_forecast']=={'medyka':[2040,2060,2061,2063],
        'dorohusk':[1602,1605,1603,1633],'korczowa':[1364,1366,1365,1364]}
    assert response.json()['input_provenance']['history_weeks']==2

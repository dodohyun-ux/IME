"""Fresh supplied-model inference -> official-road optimizer; preserve reproducible evidence."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ofr_v2/app'))
sys.path.insert(0,str(ROOT/'ofr_v2'))
from fastapi.testclient import TestClient
from backend import main
from backend.optimization import example_inputs
from backend.logistics import example_logistics
from backend.road_planner import build_ui_logistics
from validation.audit import audit


def dump(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def forecast(client,body):
    t=time.perf_counter();response=client.post('/predict',json=body)
    assert response.status_code==200,response.text
    return response.json(),time.perf_counter()-t


def metrics(pred,actual):
    rows=[(float(p),float(a)) for p,a in zip(pred,actual) if a is not None]
    return {'n':len(rows),'mae':sum(abs(p-a) for p,a in rows)/len(rows),
            'wape_pct':100*sum(abs(p-a) for p,a in rows)/sum(a for _,a in rows)} if rows and sum(a for _,a in rows)>0 else {'n':len(rows),'mae':None,'wape_pct':None}


def main_run():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'ofr_v2/results/forecast_integration_20261006');args=parser.parse_args();out=args.output;out.mkdir(parents=True,exist_ok=True)
    model_before=hashlib.sha256((ROOT/'ofr_v2/app/models/relief_model.joblib').read_bytes()).hexdigest()
    frozen=json.loads((ROOT/'ofr_v2/results/final_review_20261006/review_checks.json').read_text(encoding='utf-8'))['source_sha256']
    engines=[f for f in frozen if '/backend/' in f and not f.endswith('/main.py')]
    assert all(hashlib.sha256((ROOT/f).read_bytes()).hexdigest()==frozen[f] for f in engines)
    client=TestClient(main.app)
    h=client.get('/history',params={'reference_date':'2026-01-26'}).json()
    body={'reference_date':'2026-01-26','hub_inflow':h['hub_inflow']}
    base,seconds=forecast(client,body);dump(out/'baseline_forecast.json',base);dump(out/'baseline_input.json',body)
    print('baseline',base['hub_forecast'],'seconds',round(seconds,3),flush=True)
    sensitivities=[]
    for hub in main.HUBS:
        for k in range(2):
            altered=deepcopy(body);altered['hub_inflow'][hub][k]*=2
            result,elapsed=forecast(client,altered)
            delta=[result['hub_forecast'][hub][i]-base['hub_forecast'][hub][i] for i in range(4)]
            other_unchanged=all(result['hub_forecast'][other]==base['hub_forecast'][other] for other in main.HUBS if other!=hub)
            assert other_unchanged
            sensitivities.append({'hub':hub,'history_index':k,'week_label':'reference' if k==0 else f'{k}_weeks_ago','original':body['hub_inflow'][hub][k],
                                  'modified':altered['hub_inflow'][hub][k],'baseline':base['hub_forecast'][hub],
                                  'modified_forecast':result['hub_forecast'][hub],'delta':delta,'other_hubs_unchanged':other_unchanged,'seconds':elapsed})
    assert any(any(row['delta']) for row in sensitivities if row['history_index']==0)
    dump(out/'history_sensitivity.json',sensitivities)
    changed_body=deepcopy(body);changed_body['hub_inflow']['medyka'][0]*=2
    changed,_=forecast(client,changed_body);dump(out/'recent_change_forecast.json',changed)
    later=deepcopy(body);later['reference_date']=client.get('/meta').json()['last_reference']
    later_result,_=forecast(client,later)
    dump(out/'later_reference_manual_scenario.json',{'input':later,'result':later_result,'synthetic_scenario':'These January observations are reused only to exercise manual-input API at a later date. They are NOT later observed inflows.'})
    operations=[]
    inventories={'Medyka':dict(water=12000,food=800,hygiene_kit=150,blanket=180),
                 'Dorohusk':dict(water=5000,food=350,hygiene_kit=80,blanket=100),
                 'Korczowa':dict(water=7000,food=450,hygiene_kit=100,blanket=120)}
    for case,pred,site in [('baseline',base,'Medyka'),('baseline',base,'Dorohusk'),('baseline',base,'Korczowa'),('recent_medyka_x2',changed,'Medyka')]:
        _,user,volume=example_inputs(site);user['initial_inventory']={site:inventories[site]};user['total_budget']=110000;user['utilization_rate']=.1;user['stay_days']=3
        logistics=example_logistics(site)
        for key in ('vehicles','routes','corridors'):logistics.pop(key)
        logistics['initial_lots']=[dict(id='opening:'+i,item=i,quantity=q,expiry_week=20 if i in ('water','food') else None) for i,q in inventories[site].items()]
        request={**user,'ml_forecast':{site:{str(i+1):v for i,v in enumerate(pred['hub_forecast'][site.lower()])}},
                 'item_volume_m3':volume,'logistics':logistics,
                 'road_planning':{'warehouse_id':'przemysl-wodna-11','truck_count':2,'reference_date':body['reference_date']}}
        started=time.perf_counter();r=client.post('/optimize',json=request);elapsed=time.perf_counter()-started
        assert r.status_code==200,r.text;result=r.json()
        assert {p['week']:p['forecast_arrivals'] for p in result['plan']}=={i+1:v for i,v in enumerate(pred['hub_forecast'][site.lower()])}
        expanded,_=build_ui_logistics(logistics,request['road_planning'],site)
        audit_input={**request,'logistics':expanded};check=audit(audit_input,result)
        assert check['passed'],check['failures']
        dump(out/(case+'_'+site+'_input.json'),request)
        dump(out/(case+'_'+site+'_result.json'),result)
        row={'case':case,'site':site,'input_forecast':pred['hub_forecast'][site.lower()],'trips':len(result['truck_plan']),
             'cost':result['summary']['total_cost'],'procurement_cost':result['summary']['total_procurement_cost'],
             'transport_cost':result['summary']['transport_cost'],'fulfillment_pct':100*result['summary']['overall_weighted_fulfillment_rate'],
             'audit':check,'elapsed_seconds':elapsed,'operational_ready':result['model_info']['operational_ready']}
        operations.append(row);print('optimizer',case,site,'trips',row['trips'],'fulfillment',round(row['fulfillment_pct'],2),'seconds',round(elapsed,2),flush=True)
    assert operations[0]['input_forecast']!=operations[-1]['input_forecast']
    assert operations[0]['cost']!=operations[-1]['cost'] or operations[0]['fulfillment_pct']!=operations[-1]['fulfillment_pct']
    actual=base['hub_actual'];points=[];observed=[];naive=[]
    for hub in main.HUBS:
        points.extend(base['hub_forecast'][hub]);observed.extend(actual[hub]);naive.extend([h['hub_inflow'][hub][0]]*4)
    sample={'scope':'one retrospective origin, 12 hub-horizon points; not an independent accuracy certificate',
            'reference_date':body['reference_date'],'model':metrics(points,observed),'last_week_naive':metrics(naive,observed),
            'interval_calibration_overlap_possible':True,'training_end_only_declared_in_team_code':True}
    dump(out/'single_origin_actual_comparison.json',sample)
    model_after=hashlib.sha256((ROOT/'ofr_v2/app/models/relief_model.joblib').read_bytes()).hexdigest()
    assert model_before==model_after
    report={'generated_at':datetime.now(timezone.utc).isoformat(),'passed':True,'model_sha256':model_after,
            'model_weights_unchanged':True,'optimizer_engine_hashes_unchanged':engines,
            'forecast_input_cases':len(sensitivities)+3,'history_sensitivity':sensitivities,'operations':operations,
            'sample_accuracy':sample,'uses_all_requested_history_weeks':True,'effective_inflow_history_weeks':2,
            'training_code_or_dataset_provenance_included':False,'matched_operating_records':0,'operational_ready':False}
    dump(out/'integration_evidence.json',report)
    print('complete',len(operations),'pipeline scenarios;',len(sensitivities),'one-week perturbations;',sample,flush=True)


if __name__=='__main__':main_run()

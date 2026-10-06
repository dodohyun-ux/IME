"""Predefined frozen-model rolling-origin assessment with two-week inputs only."""
from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ofr_v2/app'))
from backend import main
OUT=ROOT/'ofr_v2/results/two_week_validation_20261006/forecast'
PROTOCOL={'model_sha256':main.MODEL_SHA256,'weights_frozen':True,'training_end_declared':'2025-05-09',
 'primary_first_origin':'2025-05-12','primary_last_origin':'2026-01-26','input_weeks':2,'horizons':[1,2,3,4],
 'baselines':['last_week','mean_two_weeks','two_week_linear_trend_clipped_at_zero'],
 'metrics':['WAPE','MAE','RMSE','bias_pct','underprediction_fraction'],
 'bootstrap':{'method':'moving blocks of forecast origins; paired model-naive WAPE difference','block_origins':4,'replications':2000,'seed':20261006},
 'interval_scope':'total only; reported calibration period overlaps main origins; coverage descriptive',
 'later_target_check':'2026-02-23 only (last target week after stated calibration targets)',
 'not_retrained':True,'not_tuned_using_results':True,'training_dataset_provenance_independently_verified':False}

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def metric(frame,pred='prediction'):
 y=frame['actual'].to_numpy(float);p=frame[pred].to_numpy(float);err=p-y
 return {'n':len(y),'wape_pct':100*float(np.abs(err).sum()/y.sum()),'mae':float(np.abs(err).mean()),
  'rmse':float(np.sqrt(np.mean(err**2))),'bias_pct':100*float(err.sum()/y.sum()),'underprediction_fraction':float(np.mean(p<y))}

def run():
 OUT.mkdir(parents=True,exist_ok=True)
 (OUT/'protocol.json').write_text(json.dumps(PROTOCOL,ensure_ascii=False,indent=2),encoding='utf-8')
 model_path=ROOT/'ofr_v2/app/models/relief_model.joblib';before=digest(model_path)
 W=main.WEEKLY;rows=[];totals=[]
 origins=pd.date_range(PROTOCOL['primary_first_origin'],W.index[-2],freq='W-MON')
 for ref in origins:
  history={h:[float(W.at[ref,h]),float(W.at[ref-pd.Timedelta(weeks=1),h])] for h in main.HUBS}
  reply=main.predict(main.PredictionRequest(reference_date=ref.strftime('%Y-%m-%d'),hub_inflow=history))
  for horizon in main.HORIZONS:
   target=ref+pd.Timedelta(weeks=horizon)
   if target not in W.index:continue
   actual_total=0
   for hub in main.HUBS:
    latest,previous=history[hub];actual=float(W.at[target,hub]);actual_total+=actual
    rows.append({'origin':ref.strftime('%Y-%m-%d'),'target_week':target.strftime('%Y-%m-%d'),'hub':hub,'horizon':horizon,
      'input_current':latest,'input_previous':previous,'actual':actual,'prediction':reply['hub_forecast'][hub][horizon-1],
      'last_week':latest,'mean_two_weeks':(latest+previous)/2,
      'two_week_linear_trend_clipped_at_zero':max(0,latest+horizon*(latest-previous)),
      'primary':ref<=pd.Timestamp(PROTOCOL['primary_last_origin'])})
   total=reply[f'week{horizon}'];lo,hi=reply['intervals'][horizon-1].values()
   totals.append({'origin':ref.strftime('%Y-%m-%d'),'target_week':target.strftime('%Y-%m-%d'),'horizon':horizon,
    'prediction':total,'actual':actual_total,'low':lo,'high':hi,'covered':lo<=actual_total<=hi,'width':hi-lo,
    'primary':ref<=pd.Timestamp(PROTOCOL['primary_last_origin'])})
  print('origin',ref.strftime('%Y-%m-%d'),'done',flush=True)
 df=pd.DataFrame(rows);tdf=pd.DataFrame(totals);primary=df[df.primary].copy();tprimary=tdf[tdf.primary].copy()
 assert len(primary)==38*3*4 and primary.origin.nunique()==38
 assert np.isfinite(primary[['prediction','actual']].to_numpy()).all()
 assert digest(model_path)==before
 result={'protocol':PROTOCOL,'generated_at':datetime.now(timezone.utc).isoformat(),'model_weights_unchanged':True,
 'data_sha256':digest(ROOT/'ofr_v2/app/data/weekly.csv'),'primary_origins':38,'hub_horizon_points':len(primary),
 'unique_target_weeks':primary.target_week.nunique(),'primary_models':{m:metric(primary,m) for m in ['prediction']+PROTOCOL['baselines']},
 'horizons':{str(h):{m:metric(primary[primary.horizon==h],m) for m in ['prediction']+PROTOCOL['baselines']} for h in main.HORIZONS},
 'hubs':{h:{m:metric(primary[primary.hub==h],m) for m in ['prediction']+PROTOCOL['baselines']} for h in main.HUBS},
 'months':{month:{m:metric(g,m) for m in ['prediction','last_week','mean_two_weeks']} for month,g in primary.groupby(primary.origin.str[:7])}}
 contributions=[]
 for _,g in primary.groupby('origin',sort=True):
  contributions.append([np.abs(g.prediction-g.actual).sum(),np.abs(g.last_week-g.actual).sum(),g.actual.sum()])
 arr=np.array(contributions);rng=np.random.default_rng(20261006);boot=[];block=4;n=len(arr)
 for _ in range(2000):
  ix=np.concatenate([np.arange(start,start+block) for start in rng.integers(0,n-block+1,size=(n+block-1)//block)])[:n]
  a=arr[ix].sum(axis=0);boot.append(100*(a[0]-a[1])/a[2])
 result['paired_wape_difference_pct_points']=result['primary_models']['prediction']['wape_pct']-result['primary_models']['last_week']['wape_pct']
 result['paired_difference_block_bootstrap_95pct']=[float(v) for v in np.quantile(boot,[.025,.975])]
 result['intervals_descriptive']={'n':len(tprimary),'coverage_pct':100*float(tprimary.covered.mean()),'mean_width':float(tprimary.width.mean()),
   'by_horizon':{str(h):{'n':len(g),'coverage_pct':100*float(g.covered.mean()),'mean_width':float(g.width.mean())} for h,g in tprimary.groupby('horizon')}}
 latest=df[df.target_week=='2026-02-23'];lt=tdf[tdf.target_week=='2026-02-23']
 result['post_calibration_target_check']={'unique_target_weeks':1,'unique_actual_hub_counts':3,'hub_horizon_points':len(latest),
   'metrics':{m:metric(latest,m) for m in ['prediction']+PROTOCOL['baselines']},'total_forecast_count':len(lt),'total_interval_coverage_pct':100*float(lt.covered.mean())}
 df.to_csv(OUT/'forecasts.csv',index=False,encoding='utf-8-sig');tdf.to_csv(OUT/'total_intervals.csv',index=False,encoding='utf-8-sig')
 (OUT/'evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:result[k] for k in ['primary_models','paired_difference_block_bootstrap_95pct','intervals_descriptive','post_calibration_target_check']},ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':run()

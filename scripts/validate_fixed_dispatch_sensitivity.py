"""Sensitivity replay with fixed dispatches; not observed field operations."""
from pathlib import Path
from decimal import Decimal,ROUND_CEILING
import json,csv,gzip
ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'ofr_v2/results/two_week_validation_20261006/integration'
OUT=ROOT/'ofr_v2/results/two_week_validation_20261006/optimizer'
ITEMS=('water','food','hygiene_kit','blanket')
def run():
 OUT.mkdir(parents=True,exist_ok=True);rows=[];details=[]
 forecast=json.loads((FOLDER/'baseline_forecast.json').read_text(encoding='utf-8'))
 for site in ('Medyka','Dorohusk','Korczowa'):
  body=json.loads((FOLDER/f'baseline_{site}_input.json').read_text(encoding='utf-8'))
  plan_path=FOLDER/f'baseline_{site}_result.json'
  plan=json.loads(plan_path.read_text(encoding='utf-8') if plan_path.exists() else gzip.decompress(plan_path.with_suffix('.json.gz').read_bytes()).decode('utf-8'))
  assert all(l['expiry_week'] is None or l['expiry_week']>4 for l in body['logistics']['initial_lots'])
  assert all(v is None or v>=28 for v in body['logistics']['shelf_life_days'].values())
  receipts={w:{i:0.0 for i in ITEMS} for w in range(1,5)}
  for trip in plan['truck_plan']:
   for i,q in trip['cargo'].items():receipts[trip['arrival_week']][i]+=q
  nominal=[body['ml_forecast'][site][str(w)] for w in range(1,5)]
  cases=[('demand_minus_20pct',[v*.8 for v in nominal]),('nominal',nominal),('demand_plus_20pct',[v*1.2 for v in nominal]),('historical_actual_replay',forecast['hub_actual'][site.lower()])]
  planned_issue={(int(row['week']),row['item']):row['served'] for row in plan['plan']}
  for policy in ('planned_weekly_issue','serve_available'):
   for case,values in cases:
    inventory=body['initial_inventory'][site].copy();total_demand={i:0.0 for i in ITEMS};total_served=total_demand.copy();peak=0;worst=0
    for w,n in enumerate(values,1):
     people=int((Decimal(str(n))*Decimal(str(body['utilization_rate']))).to_integral_value(rounding=ROUND_CEILING))
     demand=dict(water=people*body['stay_days']*15,food=people*body['stay_days'],hygiene_kit=people,blanket=people)
     for i in ITEMS:inventory[i]+=receipts[w][i]
     peak=max(peak,sum(inventory[i]*body['item_volume_m3'][i] for i in ITEMS))
     for i in ITEMS:
      served=min(inventory[i],demand[i],planned_issue[w,i] if policy=='planned_weekly_issue' else float('inf'));inventory[i]-=served
      total_demand[i]+=demand[i];total_served[i]+=served
      worst=max(worst,(demand[i]-served)/demand[i] if demand[i] else 0)
      details.append(dict(site=site,policy=policy,case=case,week=w,item=i,demand=demand[i],receipt=receipts[w][i],served=served,ending_inventory=inventory[i],unmet=demand[i]-served))
    fulfillment=100*sum(total_served[i]/total_demand[i] for i in ITEMS if total_demand[i])/sum(v>0 for v in total_demand.values())
    if policy=='planned_weekly_issue' and case=='nominal':
     assert abs(fulfillment-100*plan['summary']['overall_weighted_fulfillment_rate'])<1e-3
     assert abs(100*worst-100*plan['summary']['max_unmet_rate'])<1e-3
    rows.append(dict(site=site,policy=policy,case=case,dispatches_fixed=len(plan['truck_plan']),planned_cost_fixed=plan['summary']['total_cost'],
        demand_fulfillment_pct=fulfillment,worst_cell_shortage_pct=100*worst,peak_inventory_m3=peak,capacity_m3=body['warehouse_capacity_m3'][site],storage_capacity_exceeded=peak>body['warehouse_capacity_m3'][site]+1e-5))
 for name,data in [('fixed_plan_stress.csv',rows),('fixed_plan_weekly_inventory.csv',details)]:
  with (OUT/name).open('w',newline='',encoding='utf-8-sig') as f:
   writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
 evidence={'cases':rows,'case_count':len(rows),'policies':{'planned_weekly_issue':'Fixed cargo/arrivals/costs and planned weekly served caps; issue at most actual demand and available stock. Nominal fulfillment and worst shortage reproduced.', 'serve_available':'Fixed dispatches, separate greedy issue rule serving available items. Does NOT preserve nominal fairness objective.'},
   'scope':'Synthetic demand multipliers and retrospective actual-demand replay with simulated delivery times. NOT field observations.',
   'expiry_assumption_checked':'Opening stock usable beyond week4; newly purchased water/food usable throughout 4-week horizon in these fixtures.',
   'warehouse_basis':'Batch all weekly receipts before issues, matching conservative weekly peak basis.', 'operational_ready':False}
 (OUT/'fixed_plan_stress.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(rows,ensure_ascii=False,indent=2))
if __name__=='__main__':run()

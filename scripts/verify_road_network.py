"""Reproducible synthetic model smoke, without forecast assets or a web UI."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ofr_v2'/'app'))
from backend.optimization import optimize_relief_plan


def main():
    body=json.loads((ROOT/'ofr_v2/examples/road_network_request.json').read_text(encoding='utf-8'))
    forecast=body.pop('ml_forecast'); volume=body.pop('item_volume_m3'); logistics=body.pop('logistics')
    result=optimize_relief_plan(forecast,body,volume,logistics=logistics)
    assert result['model_info']['road_network_enabled']
    assert result['model_info']['road_graph_data_kind']=='synthetic'
    assert len(result['truck_plan'])==1
    trip=result['truck_plan'][0]
    assert trip['cargo']['food']==10
    assert trip['outbound_edges']==['depot-north','north-site']
    assert trip['return_edges']==['site-north','north-depot']
    assert result['summary']['transport_cost']==180
    assert result['summary']['total_cost']==280
    print('Synthetic road model verified: named truck, cargo, outbound/return paths, schedule and cost.')


if __name__=='__main__':
    main()

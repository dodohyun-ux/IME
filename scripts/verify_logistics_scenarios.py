"""Generate reproducible synthetic examples; these are not field measurements."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ofr_v2' / 'app'))
from backend.optimization import example_inputs, optimize_relief_plan
from backend.logistics import example_logistics


def main():
    folder = ROOT / 'ofr_v2' / 'examples'
    folder.mkdir(exist_ok=True)
    f, u, v = example_inputs()
    l = example_logistics()
    body = dict(u, ml_forecast=f, item_volume_m3=v, logistics=l)
    (folder / 'logistics_request.json').write_text(json.dumps(body, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (folder / 'logistics_only.json').write_text(json.dumps(l, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    rows = []
    for name in ['legacy', 'logistics', 'one_week_procurement', 'route_closed', 'short_shelf_life']:
        cfg = deepcopy(l)
        if name == 'one_week_procurement': cfg['procurement_lead_days'] = {i:7 for i in v}
        if name == 'route_closed': cfg['routes'][0]['max_trips'] = {w:0 for w in range(1,5)}
        if name == 'short_shelf_life':
            cfg['shelf_life_days'].update(water=7, food=7)
            cfg['routes'][0].update(transit_days=7, round_trip_days=7)
        result = optimize_relief_plan(f, u, v, logistics=None if name=='legacy' else cfg)
        if name == 'logistics':
            (folder / 'logistics_result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        summary = result['summary']
        rows.append(dict(scenario=name, synthetic=True,
                         fulfillment_pct=100*summary['overall_weighted_fulfillment_rate'],
                         max_unmet_pct=100*summary['max_unmet_rate'],
                         total_cost=summary.get('total_cost',summary['total_procurement_cost']),
                         transport_cost=summary.get('transport_cost',0),
                         disposal_cost=summary.get('disposal_cost',0)))
    report = ROOT / 'ofr_v2' / 'results' / 'logistics_synthetic_validation.csv'
    with report.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()

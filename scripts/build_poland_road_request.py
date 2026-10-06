"""Create a geometry-backed scenario request from explicit fleet and road assumptions.

No web UI, no dispatch, no synthetic facility fallback. A candidate address may
be geocoded but is never treated as a verified loading entrance.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ofr_v2/app'))
from backend.poland_roads import load_snapshot, load_addresses, scenario_network, geocoded_address
from backend.optimization import InputValidationError


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-request',type=Path,required=True,help='Existing optimize request with explicit road_network fleet/settings')
    p.add_argument('--snapshot',type=Path,default=ROOT/'ofr_v2/data/roads/raw')
    p.add_argument('--warehouse',required=True,help='Candidate ID in facilities.json')
    p.add_argument('--destination',required=True,help='Reception candidate ID in facilities.json')
    p.add_argument('--assumptions',type=Path,required=True,help='JSON: speed_kph, gross/height/width limits and toll_per_km')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--max-snap-metres',type=float,default=500)
    p.add_argument('--regions',nargs='+',help='Explicit acquired regional/corridor coverage override')
    p.add_argument('--destination-rest-permission',action='store_true',help='Explicit scenario permission for a separate driver break at the destination; not operator approval')
    args=p.parse_args()
    registry=json.loads((ROOT/'ofr_v2/data/roads/facilities.json').read_text(encoding='utf-8'))
    def facility(kind,key):
        found=[v for v in registry[kind] if v['id']==key]
        if len(found)!=1: raise InputValidationError('Unknown facility candidate: '+key)
        return found[0]
    origin=facility('warehouse_candidates',args.warehouse)
    target=facility('destinations',args.destination)
    body=json.loads(args.base_request.read_text(encoding='utf-8'))
    if body['selected_site']!=target['site']:
        raise InputValidationError('Request site and destination must match')
    lookups=load_addresses(args.snapshot)
    def point(f):
        values=[r for r in lookups if r['query']==f['geocode_query'] and 'response' in r]
        if len(values)!=1: raise InputValidationError('Official address lookup unavailable: '+f['address'])
        return geocoded_address(values[0]['response'],f['city'],f['number'],f.get('street'))
    regions=args.regions or (['Medyka'] if target['site']=='Medyka' else (['Medyka','Korczowa'] if target['site']=='Korczowa' else ['Medyka','Korczowa','Dorohusk','DorohuskCorridor']))
    snapshot=load_snapshot(args.snapshot,regions)
    body['logistics']['road_network'],diagnostic=scenario_network(snapshot,body['logistics']['road_network'],
        point(origin),point(target),json.loads(args.assumptions.read_text(encoding='utf-8')),args.max_snap_metres,
        destination_rest_allowed=args.destination_rest_permission)
    diagnostic.update(warehouse=origin,destination_facility=target)
    if not diagnostic['connected']:
        raise InputValidationError('Acquired road coverage does not connect the candidate facilities; acquire/review the missing corridor')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(body,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    args.output.with_suffix('.diagnostics.json').write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Created actual-geometry scenario request. Review diagnostics; this is not an approved dispatch plan.')


if __name__=='__main__': main()

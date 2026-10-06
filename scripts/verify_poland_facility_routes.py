"""Audit candidate address points and actual road connectivity, never dispatch.

Physical access, inferred topology and vehicle permission remain unverified.
The shortest distance is conditional on the acquired symmetric geometry graph.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ofr_v2/app'))
from backend.poland_roads import (load_snapshot,load_addresses,endpoint_graph,
                                 geocoded_address,snap_endpoint,route_subgraph)
from backend.road_paths import shortest_paths
from backend.optimization import InputValidationError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,default=ROOT/'ofr_v2/data/roads/raw')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    registry=json.loads((ROOT/'ofr_v2/data/roads/facilities.json').read_text(encoding='utf-8'))
    records=load_addresses(args.snapshot)
    def point(f):
        values=[r for r in records if r['query']==f['geocode_query'] and 'response' in r]
        if len(values)!=1: raise InputValidationError('Exactly one official address response required')
        return geocoded_address(values[0]['response'],f['city'],f['number'],f.get('street'))
    report=dict(operational_ready=False,scope='Hash-checked official geometry; assumed symmetric endpoint topology; address points, not docks',routes=[])
    for destination in registry['destinations']:
        site=destination['site']
        regions=['Medyka'] if site=='Medyka' else ['Medyka','Korczowa']
        if site=='Dorohusk': regions+=['Dorohusk','DorohuskCorridor']
        snapshot=load_snapshot(args.snapshot,regions)
        graph=endpoint_graph(snapshot)
        for warehouse in registry['warehouse_candidates']:
            row=dict(warehouse=warehouse['id'],destination=destination['id'],regions=regions,
                     source_features=len(snapshot['links']),missing_tiles=len(snapshot['missing_tiles']))
            try:
                origin=snap_endpoint(graph,point(warehouse),500)
                target=snap_endpoint(graph,point(destination),500)
                row.update(origin=origin,destination_point=target)
                connected=any(origin['node'] in c and target['node'] in c for c in graph['components'])
                row['connected']=connected
                if connected:
                    trimmed=route_subgraph(graph,origin['node'],target['node'])
                    paths=shortest_paths(trimmed['edges'],trimmed['adjacency'],origin['node'],target['node'],
                                         lambda e:True,lambda e:e['distance_km'],1)
                    path=paths[0]
                    row.update(status='geometry_path_found',retained_nodes=len(trimmed['nodes']),
                               retained_directed_edges=len(trimmed['edges']),
                               shortest_scenario_distance_km=sum(trimmed['edges'][e]['distance_km'] for e in path),
                               source_feature_ids=[trimmed['edges'][e]['source_feature_ids'][0] for e in path])
                else:
                    row['status']='disconnected_acquired_geometry'
            except InputValidationError as error:
                row.update(status='rejected',reason=str(error))
            report['routes'].append(row)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps([{k:v for k,v in row.items() if k not in ('source_feature_ids','origin','destination_point')} for row in report['routes']],ensure_ascii=False))


if __name__=='__main__': main()

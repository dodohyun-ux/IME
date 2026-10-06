"""Verify exact official regional snapshots and report geography/topology scope."""
from pathlib import Path
import argparse
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ofr_v2/app'))
from backend.poland_roads import load_snapshot, endpoint_graph


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,default=ROOT/'ofr_v2/data/roads/raw')
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    manifest=json.loads((args.snapshot/'acquisition.json').read_text(encoding='utf-8'))
    regions=sorted({d['region'] for d in manifest['documents'] if 'region' in d})
    report=dict(publisher='GUGiK',operational_ready=False,regions={})
    for region in regions:
        snapshot=load_snapshot(args.snapshot,region); graph=endpoint_graph(snapshot)
        report['regions'][region]=dict(source_features=len(snapshot['links']),nodes=len(graph['nodes']),
            directed_scenario_edges=len(graph['edges']),component_sizes=sorted((len(c) for c in graph['components']),reverse=True),
            excluded_features=graph['excluded_feature_ids'],feature_version_range=snapshot['feature_version_range'],
            fetched_at=snapshot['fetched_at'],missing_tiles=snapshot.get('missing_tiles',[]),
            source_urls=[s['url'] for s in snapshot['sources']])
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({region:{k:v for k,v in data.items() if k!='source_urls'} for region,data in report['regions'].items()},ensure_ascii=False))


if __name__=='__main__':main()

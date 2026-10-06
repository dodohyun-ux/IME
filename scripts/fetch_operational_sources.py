"""Restore pinned official public sources, verify hashes and extracted speed rows.

Run with network access: python scripts/fetch_operational_sources.py
Optional PDF row verification: --verify-tables (requires pdfplumber).
Never silently refresh pinned evidence to a new version.
"""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]/'ofr_v2/data/operational_evidence'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-tables', action='store_true')
    args = parser.parse_args()
    raw = ROOT/'raw'
    raw.mkdir(exist_ok=True)
    for source in json.loads((ROOT/'sources.json').read_text(encoding='utf-8')):
        path = raw/source['file']
        content = path.read_bytes() if path.exists() else urllib.request.urlopen(source['url'],timeout=45).read()
        if hashlib.sha256(content).hexdigest() != source['sha256']:
            raise ValueError('Source changed; manual review required: '+source['id'])
        if not path.exists():
            path.write_bytes(content)
        print('Hash verified:',source['id'],flush=True)
    if args.verify_tables:
        import pdfplumber
        observations = json.loads((ROOT/'speed_observations.json').read_text(encoding='utf-8'))['observations']
        for row in observations:
            with pdfplumber.open(raw/(row['source_id']+'.pdf')) as doc:
                lines = doc.pages[row['pdf_page']-1].extract_text().splitlines()
            found = [k for k,line in enumerate(lines) if line.split() and line.split()[0]==row['station']]
            if len(found) != 1:
                raise ValueError('Station row ambiguous: '+row['station'])
            k = found[0]
            tokens = lines[k-1].split() if row['vehicle_class']=='L' else lines[k].split()
            tokens = tokens[tokens.index(row['vehicle_class']):]
            percentages = [float(v.replace(',','.')) for v in tokens[2 if row['year']==2025 else 1:]]
            if percentages != row['percentages']:
                raise ValueError('Extracted row differs: '+str(row))
        print('Verified speed rows:',len(observations))


if __name__ == '__main__':
    main()

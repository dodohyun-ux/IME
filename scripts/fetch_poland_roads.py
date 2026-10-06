"""Fetch public official INSPIRE road features; no substitute geometry on failure.

Service documented by https://www.geoportal.gov.pl/pl/usluga/uslugi-inspire/.
Discovery/provenance snapshot is an intermediate artifact, not an operational map.
"""
from pathlib import Path
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import time
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
ENDPOINTS=[
    'https://mapy.geoportal.gov.pl/wss/service/wfsTN/guest',
    'https://mapy.geoportal.gov.pl/wss/service/INSPIREG2/httpauth/rest/services/INSPIRE/INSPIRE_TN_TBD/GeoDataServer/exts/InspireFeatureDownload/service',
]


def fetch(url, timeout=40, attempts=3):
    req=urllib.request.Request(url,headers={'User-Agent':'OFR-research-road-import/1.0'})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req,timeout=timeout) as response:
                raw=response.read(20000001)
                if len(raw)>20000000:
                    raise ValueError('Official response exceeds bounded acquisition size')
                return raw
        except Exception:
            if attempt==attempts-1: raise
            time.sleep(2)


def emit_document(d):
    print('OFR_ROAD_DOCUMENT '+json.dumps(dict(name=d['name'],url=d['url'],
          sha256=hashlib.sha256(d['raw']).hexdigest(),base64_gzip=base64.b64encode(gzip.compress(d['raw'],mtime=0)).decode('ascii'))),flush=True)


def discover(endpoint):
    url=endpoint+'?'+urllib.parse.urlencode(dict(service='WFS',request='GetCapabilities',version='1.1.0'))
    try:
        raw=fetch(url); root=ET.fromstring(raw)
        names=[n.text for n in root.findall('.//{*}FeatureType/{*}Name')]
        if not any(n and n.split(':')[-1]=='RoadLink' for n in names):
            raise ValueError('No RoadLink feature type advertised')
        return dict(endpoint=endpoint,capabilities_url=url,names=names,raw=raw)
    except Exception as error:
        return dict(endpoint=endpoint,error=f'{type(error).__name__}: {error}')


def main():
    with ThreadPoolExecutor(max_workers=2) as executor:
        discoveries=list(executor.map(discover,ENDPOINTS))
    for d in discoveries:
        print(json.dumps({k:v for k,v in d.items() if k!='raw'},ensure_ascii=False),flush=True)
    found=next((d for d in discoveries if 'raw' in d),None)
    if found is None:
        raise RuntimeError('Official road servers unavailable; no synthetic replacement downloaded')
    documents=[dict(name='capabilities.xml',url=found['capabilities_url'],raw=found['raw'])]
    emit_document(documents[0])
    # Regional coverage, NOT all Poland. Includes Przemysl candidate warehouses.
    regions={'Medyka':(49.75,22.70,49.90,23.10),
             'Korczowa':(49.90,22.70,50.08,23.15),
             'Dorohusk':(51.08,23.35,51.25,23.88)}
    name=next(n for n in found['names'] if n.split(':')[-1]=='RoadLink')
    def tile(region, bounds, depth=0):
        bbox=','.join(f'{v:.6f}' for v in bounds)+',urn:ogc:def:crs:EPSG::4326'
        params=dict(service='WFS',request='GetFeature',version='1.1.0',typeName=name,
                    bbox=bbox,maxFeatures=5000,srsName='urn:ogc:def:crs:EPSG::4326')
        url=found['endpoint']+'?'+urllib.parse.urlencode(params)
        raw=fetch(url); root=ET.fromstring(raw)
        if root.tag.split('}')[-1]!='FeatureCollection':
            raise ValueError('Official endpoint did not return a FeatureCollection')
        count=len(root.findall('.//{*}RoadLink'))
        if count>=5000:
            if depth>=5: raise ValueError('Road response may be truncated; acquire smaller tiles')
            a,b,c,d=bounds
            return tile(region+'a',(a,b,(a+c)/2,d),depth+1)+tile(region+'b',((a+c)/2,b,c,d),depth+1)
        original=next(r for r in regions if region.startswith(r))
        return [dict(name=region+'.gml',region=original,url=url,raw=raw,bbox=bbox,count=count)]
    errors=[]
    for region,bounds in regions.items():
        a,b,c,d=bounds
        rows,cols=math.ceil((c-a)/.06),math.ceil((d-b)/.15)
        acquired=[]
        for row in range(rows):
            for col in range(cols):
                print('Fetching',region,row,col,flush=True)
                try:
                    new=tile(region+f'-{row}-{col}',
                             (a+(c-a)*row/rows,b+(d-b)*col/cols,
                              a+(c-a)*(row+1)/rows,b+(d-b)*(col+1)/cols))
                    acquired.extend(new)
                    for document in new: emit_document(document)
                except Exception as error:
                    errors.append(dict(region=region,row=row,col=col,error=f'{type(error).__name__}: {error}'))
                    print('Tile unavailable',errors[-1],flush=True)
        documents.extend(acquired)
        print(region,[(d['name'],d['count']) for d in acquired],flush=True)
    addresses=['Przemyśl, Lwowska 36','Przemyśl, Wodna 11','Medyka 293','Medyka 285',
               'Korczowa 155','Dorohusk, Parkowa 5']
    geocodes=[]
    for address in addresses:
        url='https://services.gugik.gov.pl/uug/?'+urllib.parse.urlencode(dict(request='GetAddress',address=address))
        try:
            raw=fetch(url); value=json.loads(raw)
            geocodes.append(dict(query=address,url=url,response=value))
        except Exception as error:
            geocodes.append(dict(query=address,url=url,error=f'{type(error).__name__}: {error}'))
    documents.append(dict(name='addresses.json',url='https://services.gugik.gov.pl/uug/',
                          raw=json.dumps(geocodes,ensure_ascii=False,indent=2).encode('utf-8')))
    folder=ROOT/'ofr_v2/data/roads/raw'; folder.mkdir(parents=True,exist_ok=True)
    manifest=dict(publisher='GUGiK',documentation_url='https://www.geoportal.gov.pl/pl/usluga/uslugi-inspire/',
                  fetched_at=datetime.now(timezone.utc).isoformat(),regions=regions,errors=errors,documents=[])
    for d in documents:
        (folder/d['name']).write_bytes(d['raw'])
        manifest['documents'].append({k:v for k,v in d.items() if k!='raw'} |
                                     dict(bytes=len(d['raw']),sha256=hashlib.sha256(d['raw']).hexdigest()))
    (folder/'acquisition.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    # Exact gzip-encoded response bytes for recovery from the authorized CI job.
    # Responses are public official geographic data, never credentials.
    documents.append(dict(name='acquisition.json',url=found['endpoint'],raw=(folder/'acquisition.json').read_bytes()))
    for d in documents:
        if d['name'] in ('addresses.json','acquisition.json'): emit_document(d)
    if errors: print('WARNING: regional coverage is incomplete; see manifest errors. No substitute roads.',flush=True)


def retry_missing():
    """Preserve the approved snapshot and fill only its explicitly missing tiles."""
    folder=ROOT/'ofr_v2/data/roads/raw'
    manifest=json.loads((folder/'acquisition.json').read_text(encoding='utf-8'))
    remaining=[]
    now=datetime.now(timezone.utc).isoformat()
    acquisition_tag=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    for failed in manifest.get('errors',[]):
        region,row,col=failed['region'],failed['row'],failed['col']
        a,b,c,d=manifest['regions'][region]
        rows,cols=math.ceil((c-a)/.06),math.ceil((d-b)/.15)
        bounds=failed.get('bounds',(a+(c-a)*row/rows,b+(d-b)*col/cols,
                                    a+(c-a)*(row+1)/rows,b+(d-b)*(col+1)/cols))
        x,y,z,w=bounds
        for r in range(2):
            for s in range(2):
                small=(x+(z-x)*r/2,y+(w-y)*s/2,x+(z-x)*(r+1)/2,y+(w-y)*(s+1)/2)
                name=f'{region}-{row}-{col}-retry-{acquisition_tag}-{r}-{s}.gml'
                bbox=','.join(f'{v:.6f}' for v in small)+',urn:ogc:def:crs:EPSG::4326'
                url=ENDPOINTS[0]+'?'+urllib.parse.urlencode(dict(service='WFS',request='GetFeature',version='1.1.0',
                     typeName='tn-ro:RoadLink',bbox=bbox,maxFeatures=5000,srsName='urn:ogc:def:crs:EPSG::4326'))
                try:
                    raw=fetch(url);root=ET.fromstring(raw)
                    count=len(root.findall('.//{*}RoadLink'))
                    if root.tag.split('}')[-1]!='FeatureCollection' or count>=5000:
                        raise ValueError('Incomplete/invalid road tile response')
                    doc=dict(name=name,region=region,url=url,bbox=bbox,count=count,
                             bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),retrieved_at=now)
                    if any(d['name']==name for d in manifest['documents']):
                        raise ValueError('Retry name already exists; preserve old snapshot and use unique acquisition name')
                    manifest['documents'].append(doc)
                    (folder/(name+'.base64')).write_text(base64.b64encode(gzip.compress(raw,mtime=0)).decode('ascii')+'\n',encoding='ascii')
                    emit_document(doc | dict(raw=raw))
                except Exception as error:
                    remaining.append(dict(region=region,row=row,col=col,bounds=small,error=f'{type(error).__name__}: {error}'))
                    print('Tile unavailable',remaining[-1],flush=True)
    # Use the officially documented settlement name, never a fuzzy nearby point.
    addresses=json.loads((folder/'addresses.json').read_text(encoding='utf-8'))
    address='Dorohusk-Osada, Parkowa 5'
    url='https://services.gugik.gov.pl/uug/?'+urllib.parse.urlencode(dict(request='GetAddress',address=address))
    try:
        raw=fetch(url); value=json.loads(raw)
        addresses=[r for r in addresses if r['query']!=address]+[dict(query=address,url=url,response=value)]
    except Exception as error:
        addresses.append(dict(query=address,url=url,error=f'{type(error).__name__}: {error}'))
    address_raw=json.dumps(addresses,ensure_ascii=False,indent=2).encode('utf-8')
    (folder/'addresses.json').write_bytes(address_raw)
    for doc in manifest['documents']:
        if doc['name']=='addresses.json':
            doc.update(bytes=len(address_raw),sha256=hashlib.sha256(address_raw).hexdigest(),retrieved_at=now)
    emit_document(dict(name='addresses.json',url='https://services.gugik.gov.pl/uug/',raw=address_raw))
    manifest.update(errors=remaining,last_attempt_at=datetime.now(timezone.utc).isoformat())
    raw=json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
    (folder/'acquisition.json').write_bytes(raw)
    emit_document(dict(name='acquisition.json',url=ENDPOINTS[0],raw=raw))
    print('Missing tiles after retry:',len(remaining),flush=True)


def extend_corridor(fill_only=False):
    """Acquire geographic coverage toward Dorohusk; never prescribe a road route.

    These overlapping search boxes are research coverage assumptions. All road
    lines still come exclusively from the official WFS, including failures.
    Four bounded readers avoid serial server timeouts; they do not bypass access
    restrictions. Existing raw source documents are never overwritten.
    """
    folder=ROOT/'ofr_v2/data/roads/raw'
    manifest=json.loads((folder/'acquisition.json').read_text(encoding='utf-8'))
    tag=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
    # Broad overlapping corridor: north of the already acquired Przemysl area,
    # through eastern Poland toward the separately acquired Chelm/Dorohusk area.
    centers=[22.70,22.78,22.96,23.10,23.18,23.35,23.45,23.42,23.35,
             23.29,23.27,23.25,23.23,23.25,23.23,23.27,23.37,23.45,23.45]
    pending=[]
    for row,lon in enumerate([] if fill_only else centers):
        lat=50.04+row*.06
        # Wider than the step; adjacent search boxes overlap in both axes.
        for col in range(2):
            bounds=(lat-.025,lon-.20+col*.20,lat+.085,lon+col*.20)
            pending.append(dict(region='DorohuskCorridor',row=row,col=col,bounds=bounds))
    manifest['regions']['DorohuskCorridor']=[50.015,22.50,51.205,23.65]
    # Fill original missing boxes as well, including the Lwowska warehouse area.
    old_errors=manifest.get('errors',[])
    if fill_only:
        for item in old_errors:
            a,b,c,d=item['bounds']
            for r in range(2):
                for s in range(2):
                    pending.append(item | dict(bounds=(a+(c-a)*r/2,b+(d-b)*s/2,
                                                       a+(c-a)*(r+1)/2,b+(d-b)*(s+1)/2)))
    else:
        pending.extend(old_errors)
    pending=[item | dict(acquisition_id=f'{tag}-{j}',error='Acquisition pending') for j,item in enumerate(pending)]
    manifest['errors']=list(pending)
    def acquire(item):
        bounds=item['bounds']
        bbox=','.join(f'{v:.6f}' for v in bounds)+',urn:ogc:def:crs:EPSG::4326'
        url=ENDPOINTS[0]+'?'+urllib.parse.urlencode(dict(service='WFS',request='GetFeature',version='1.1.0',
                typeName='tn-ro:RoadLink',bbox=bbox,maxFeatures=5000,srsName='urn:ogc:def:crs:EPSG::4326'))
        try:
            raw=fetch(url,timeout=15 if fill_only else 25,attempts=2); root=ET.fromstring(raw)
            count=len(root.findall('.//{*}RoadLink'))
            if root.tag.split('}')[-1]!='FeatureCollection' or count>=5000:
                raise ValueError('Incomplete/invalid tile: split coverage before reuse')
            name=f"{item['region']}-{item['row']}-{item['col']}-extend-{item['acquisition_id']}.gml"
            doc=dict(name=name,region=item['region'],url=url,bbox=bbox,count=count,
                     bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),
                     retrieved_at=datetime.now(timezone.utc).isoformat())
            return doc,raw,item['acquisition_id']
        except Exception as error:
            return item | dict(error=f'{type(error).__name__}: {error}'),None,item['acquisition_id']
    completed=0
    with ThreadPoolExecutor(max_workers=3 if fill_only else 4) as executor:
        futures=[executor.submit(acquire,item) for item in pending]
        for future in as_completed(futures):
            doc,raw,aid=future.result()
            manifest['errors']=[e for e in manifest['errors'] if e['acquisition_id']!=aid]
            if raw is None:
                manifest['errors'].append(doc); print('Tile unavailable',doc,flush=True)
            else:
                manifest['documents'].append(doc)
                (folder/(doc['name']+'.base64')).write_text(base64.b64encode(gzip.compress(raw,mtime=0)).decode('ascii')+'\n',encoding='ascii')
                emit_document(doc | dict(raw=raw))
            # Retain partial progress even if the remote job is interrupted.
            manifest['last_attempt_at']=datetime.now(timezone.utc).isoformat()
            (folder/'acquisition.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            completed+=1
            if completed%10==0:
                emit_document(dict(name='acquisition.json',url=ENDPOINTS[0],raw=(folder/'acquisition.json').read_bytes()))
    emit_document(dict(name='acquisition.json',url=ENDPOINTS[0],raw=(folder/'acquisition.json').read_bytes()))
    print('Missing research tiles:',len(manifest['errors']),flush=True)


if __name__=='__main__':
    if '--fill-corridor' in sys.argv: extend_corridor(fill_only=True)
    elif '--extend-corridor' in sys.argv: extend_corridor()
    elif '--retry-missing' in sys.argv: retry_missing()
    else: main()

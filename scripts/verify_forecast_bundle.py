"""Verify the supplied active forecast artifact without unpickling it."""
from pathlib import Path
import hashlib
ROOT=Path(__file__).resolve().parents[1]
MODEL=ROOT/'ofr_v2/app/models/relief_model.joblib'
EXPECTED='87c8953c7bd6abe5406c0513f23243cebdc305771681a33a488b4e17fbb606aa'
if not MODEL.is_file():
    raise SystemExit('Missing active relief_model.joblib. Obtain the supplied bundle or Git LFS object.')
if MODEL.stat().st_size<200 and MODEL.read_bytes().startswith(b'version https://git-lfs'):
    raise SystemExit('Active model is an LFS pointer. Download its object with git lfs pull.')
with MODEL.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
if actual!=EXPECTED:raise SystemExit(f'Forecast bundle checksum mismatch: {actual}')
print('Active supplied forecast bundle verified: '+actual)

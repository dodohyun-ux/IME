"""호스팅용 진입점: API와 빌드된 화면(frontend/dist)을 한 서버에서 제공한다.

backend/main.py 는 수정하지 않고 그대로 불러온다.
- /predict, /optimize, /meta ... : 기존 API
- /                              : 화면(index.html)

실행 (ofr_v2/app 폴더에서):
    uvicorn serve:app --host 0.0.0.0 --port 8000
"""
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from backend.main import app

DIST = Path(__file__).resolve().parent / "frontend" / "dist"

if DIST.is_dir():
    # 화면을 '/'에서 보여주기 위해 API 안내용 '/' 경로만 뺀다(/health 로 상태 확인 가능)
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/"]
    # API 경로가 먼저 매칭되고, 나머지 요청은 화면 파일로 처리된다
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")

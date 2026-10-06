# OFR 통합본 호스팅 안내 (2026-10-07)

`최적화모델_백엔드_FINAL_20261007.zip`과 `UI_FINAL_20261007.zip`을 하나로 합친 폴더입니다.
두 ZIP의 파일을 수정 없이 합쳤고(겹치는 파일 없음, 514개), 호스팅용 파일 4개만 추가했습니다.

| 추가 파일 | 역할 |
|---|---|
| `ofr_v2/app/serve.py` | API와 화면을 **한 서버**에서 제공하는 진입점 (`backend/main.py`는 그대로 불러옴) |
| `Dockerfile` | 화면 빌드(Node 22) + API(Python 3.12)를 한 컨테이너로 만드는 설정 |
| `.dockerignore` | 서버 실행에 필요 없는 검증 결과·문서·테스트를 이미지에서 제외 |
| `HOSTING.md` | 이 안내 |

배포하면 주소 하나(`https://...`)로 화면과 API가 함께 열립니다.
화면은 같은 서버의 API를 상대 경로로 호출하도록 빌드되므로 주소를 따로 설정할 필요가 없습니다.

## 방법 1. Render에 배포 (무료, 추천)

1. 이 폴더를 GitHub 저장소에 올립니다(비공개 가능). 100MB가 넘는 파일은 없습니다.
2. https://render.com 로그인 → **New + → Web Service** → 저장소 선택.
3. Runtime은 **Docker**가 자동 선택됩니다. 다른 설정은 기본값 그대로 **Create Web Service**.
4. 첫 빌드는 5~10분 걸립니다. 완료되면 `https://<이름>.onrender.com` 으로 접속합니다.
5. 확인: `https://<이름>.onrender.com/health` 가 `{"status":"ok", ...}` 를 반환하면 정상입니다.

무료 인스턴스는 15분 동안 접속이 없으면 잠들고, 다시 접속하면 깨어나는 데 30초~1분 걸립니다.
**시연 직전에 한 번 접속해 깨워 두세요.** 무료 메모리(512MB)에서 최적화가 느리거나 중단되면
유료 인스턴스로 올리거나 아래 방법 2(노트북에서 실행)를 사용하세요.

다른 Docker 지원 서비스(Railway, Fly.io, Google Cloud Run 등)도 같은 `Dockerfile`로 배포할 수 있습니다.
서비스가 주는 `PORT` 환경변수를 자동으로 사용합니다.

## 방법 2. 내 컴퓨터에서 Docker로 실행

Docker Desktop 설치 후 이 폴더에서:
```powershell
docker build -t ofr .
docker run -p 8000:8000 ofr
```
http://localhost:8000 에 접속합니다.

## 방법 3. Docker 없이 실행 (개발용, 터미널 2개)

`README.md`(백엔드)와 `UI_README.md`(화면)의 안내를 따릅니다.
화면을 빌드해서 한 서버로 띄우려면:
```powershell
cd ofr_v2/app/frontend
npm ci
$env:VITE_API_BASE='.'
npm run build
cd ..
..\..\.venv\Scripts\python.exe -m uvicorn serve:app --host 127.0.0.1 --port 8000
```

## 확인한 것과 하지 못한 것

- 확인: `serve.py`로 띄운 서버에서 `/` 화면 파일 제공, `/health`, `/meta`, `/history`, `/predict`, `/road-options`
  정상 응답. 기준 주 2026-01-26, 분쟁 1,000건/100명 예측 합계 4,982 / 5,057 / 5,066 / 5,085명.
  (테스트용 화면 파일로 확인)
- 확인하지 못함: 작성 PC에 Node.js와 Docker가 없어 **실제 화면 빌드와 Docker 이미지 빌드는 실행하지 못했습니다.**
  처음 배포할 때 빌드 로그에 오류가 없는지 확인하고, 화면에서 예시 값 입력 → 예측 → 최적화까지 한 번 눌러 보세요.
- 지도 배경(OpenStreetMap 타일)은 인터넷 연결이 필요합니다.
- 연구용 시연 시스템이며 현장 운영 성능은 검증되지 않았습니다(백엔드 README의 '증거와 범위' 참고).

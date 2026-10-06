# Vercel 배포 안내 (화면: https://ime-olive.vercel.app)

## 구성

```
브라우저 ──> https://ime-olive.vercel.app        (Vercel: React/Vite 화면)
               └─ /api/*  ──프록시──>  백엔드 서버 (Render 등: FastAPI + 예측 모델 + 최적화)
```

백엔드(Python, scikit-learn·scipy·도로 자료 51MB, 최적화 계산)는 Vercel 서버리스 함수의
용량·실행 시간 제한에 맞지 않아 **별도 서버**에 올립니다. `HOSTING.md`의 방법 1(Render, Docker)로
먼저 백엔드를 배포하고, 받은 주소(예: `https://ofr-backend.onrender.com`)를 아래에 넣습니다.

화면 코드 위치: `ofr_v2/app/frontend` (Vercel의 Root Directory로 지정)

---

## 1. 설정 파일

### vercel.json (`ofr_v2/app/frontend/vercel.json`, 작성해 둠)

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "framework": "vite",
  "installCommand": "npm ci",
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://YOUR-BACKEND.onrender.com/:path*" },
    { "source": "/(.*)", "destination": "/index.html" }
  ]
}
```

- **`YOUR-BACKEND.onrender.com`을 실제 백엔드 주소로 바꿔야 합니다.** (rewrites에는 환경 변수를 쓸 수 없음)
- 첫 번째 규칙: `/api/predict` → `백엔드/predict` 로 전달(프록시). 브라우저 입장에서는 같은 주소라 **CORS가 생기지 않습니다.**
- 두 번째 규칙: 파일이 없는 경로는 `index.html`로 → **새로고침 404 방지**. Vercel은 실제 파일(`/assets/...`)을 먼저 찾으므로 JS·CSS에는 영향이 없습니다.

### package.json 스크립트 (수정 불필요)

```json
"scripts": {
  "dev": "vite --host 0.0.0.0",
  "build": "vite build",
  "preview": "vite preview"
}
```
로컬에서 배포 결과 확인: `npm run build` 후 `npm run preview`.
Node.js는 **22.x**를 사용합니다(Vercel: Project Settings → General → Node.js Version → 22.x).

---

## 2. 환경 변수

이 화면은 **`VITE_API_BASE`** 를 읽습니다(`src/App.tsx`). `VITE_API_BASE_URL`이 아닙니다.

| 방식 | VITE_API_BASE 값 | 비고 |
|---|---|---|
| **A. 프록시 (추천)** | `/api` | vercel.json의 rewrites 사용, CORS 없음, 미리보기 배포도 그대로 동작 |
| B. 직접 호출 | `https://ofr-backend.onrender.com` | 백엔드 CORS 허용 필요 (아래 4번) |

### 대시보드
Project → Settings → Environment Variables → `VITE_API_BASE` = `/api`, 환경은 Production·Preview 모두 체크 → Save.
**Vite 환경 변수는 빌드할 때 코드에 박히므로, 값을 바꾼 뒤에는 반드시 Redeploy** 해야 반영됩니다.

`VITE_`로 시작하는 값은 브라우저 코드에 그대로 노출됩니다. API 주소는 괜찮지만 비밀번호·키는 절대 넣지 마세요.

### Vercel CLI
```powershell
npm i -g vercel
vercel login
cd ofr_v2/app/frontend
vercel link                          # 기존 프로젝트(ime-olive) 연결 또는 새로 만들기
vercel env add VITE_API_BASE production   # 입력값: /api
vercel env add VITE_API_BASE preview      # 입력값: /api
vercel env ls                        # 확인
vercel env pull .env.local           # 로컬 개발용으로 내려받기(선택)
vercel                               # 미리보기 배포
vercel --prod                        # 운영 배포 (https://ime-olive.vercel.app)
```

---

## 3. GitHub 자동 배포

1. 이 폴더를 GitHub 저장소에 올립니다.
   ```powershell
   git init
   git add .
   git commit -m "OFR final"
   git branch -M main
   git remote add origin https://github.com/<계정>/<저장소>.git
   git push -u origin main
   ```
2. https://vercel.com → **Add New → Project → Import Git Repository** → 저장소 선택.
3. 설정:
   - **Project Name: `ime-olive`** → 기본 주소가 `https://ime-olive.vercel.app`이 됩니다.
   - **Root Directory: `ofr_v2/app/frontend`**
   - Framework Preset: Vite (자동 인식), Build: `npm run build`, Output: `dist`
   - Environment Variables: `VITE_API_BASE` = `/api`
4. Deploy. 이후 **main 브랜치에 push하면 자동으로 운영 배포**되고, 다른 브랜치·PR은 미리보기 주소로 배포됩니다
   (Settings → Git → Production Branch = `main`).

### 주소(ime-olive.vercel.app) 지정
`*.vercel.app` 주소는 별도 도메인 구매 없이 **프로젝트 이름**으로 정해집니다.
- 새 프로젝트: 이름을 `ime-olive`로 만들면 됩니다.
- 이미 다른 이름으로 만든 경우: Settings → Domains → `ime-olive.vercel.app` 추가(다른 프로젝트가 쓰고 있지 않아야 함).
- 백엔드 기본 CORS 목록에 이미 `https://ime-olive.vercel.app`이 들어 있어, 팀이 이 이름의 프로젝트를 이미
  가지고 있을 수 있습니다. 그렇다면 그 프로젝트에 저장소를 연결(Settings → Git)하세요.

---

## 4. 자주 생기는 문제

### 새로고침하면 404
`vercel.json`의 두 번째 rewrite(`/(.*)` → `/index.html`)가 해결합니다. Root Directory가
`ofr_v2/app/frontend`로 지정되어 있어야 vercel.json이 읽힙니다.

### CORS 오류 (`blocked by CORS policy`)
- **방식 A(프록시)를 쓰면 생기지 않습니다.**
- 방식 B(직접 호출)라면 백엔드가 화면 주소를 허용해야 합니다. 이 백엔드는 환경 변수 `ALLOWED_ORIGINS`로 설정하며,
  기본값에 `https://ime-olive.vercel.app`이 이미 포함되어 있습니다. 다른 주소(미리보기 등)를 추가하려면 백엔드 서버에:
  ```
  ALLOWED_ORIGINS=https://ime-olive.vercel.app,https://ime-olive-git-main-<팀>.vercel.app,http://localhost:8443
  ```
  미리보기 배포는 주소가 매번 바뀌므로 방식 B에서는 CORS 오류가 납니다. 이 경우에도 방식 A가 편합니다.

### "서버에 연결할 수 없습니다. 백엔드 주소(...)를 확인해주세요."
- 화면 하단 메시지의 주소가 `/api`인지 확인 → 아니면 환경 변수 설정 후 Redeploy.
- 백엔드 주소의 `/health`가 열리는지 확인. Render 무료 서버는 잠들어 있으면 첫 요청에 30초~1분 걸립니다.
  시연 전에 백엔드 주소를 한 번 열어 깨워 두세요.
- 최적화 요청처럼 오래 걸리는 요청이 프록시에서 시간 초과로 실패하면, 방식 B(직접 호출)로 바꿔 보세요.

### 지도가 안 보임
지도 바탕(OpenStreetMap 타일)은 인터넷 연결이 필요합니다. 경로 선과 결과 표는 백엔드 응답으로 그려집니다.

---

## 배포 순서 요약

1. 백엔드: `HOSTING.md` 방법 1로 Render 배포 → 주소 확인, `/health` 정상 확인
2. `ofr_v2/app/frontend/vercel.json`의 `YOUR-BACKEND.onrender.com`을 실제 주소로 수정
3. GitHub에 push
4. Vercel: 프로젝트 이름 `ime-olive`, Root Directory `ofr_v2/app/frontend`, `VITE_API_BASE=/api`
5. https://ime-olive.vercel.app 에서 예시 값 입력 → 예측 → 최적화까지 확인

작성 PC에 Node.js가 없어 실제 Vercel 빌드는 실행해 보지 못했습니다. 첫 배포 때 빌드 로그를 확인하세요.

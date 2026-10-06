# 최신 최종 UI — 2026-10-07

최근 2주 유입·기준 주 분쟁 입력, CSV 업로드 제거, 두 화면의 예시 값 버튼,
구호품 계획과 도로 지도·차량별 적재/출발/도착/복귀 결과를 포함한 현재 UI 소스입니다.
기존 디자인을 유지했습니다. 소스 기준과 파일 해시는 UI_VERSION.json / UI_manifest.json입니다.

## 두 ZIP 연결

UI_FINAL_20261007.zip과 최적화모델_백엔드_FINAL_20261007.zip을 같은 디렉터리에
풀어 하나의 REFUGEE_FINAL_20261007 폴더로 합치세요. 중첩 폴더를 만들지 마세요.
두 ZIP 사이 중복 파일은 없습니다. 백엔드 README.md의 설치/실행을 먼저 진행합니다.
가상환경·node_modules·빌드 캐시는 제외했으므로 최초 한 번 설치가 필요합니다.

## 프런트 실행

Node.js 22.18 이상 및 npm을 설치한 뒤 위 공통 폴더에서 별도 PowerShell을 엽니다.
```powershell
Set-Location ofr_v2/app/frontend
npm ci
$env:VITE_API_BASE='http://127.0.0.1:8000'
npm run dev -- --host 127.0.0.1 --port 8443
```
http://127.0.0.1:8443 에 접속합니다. npm run build 로 배포용 파일을 만들 수 있습니다.
기존 .env.example은 배포 예시이며 위 로컬 환경변수가 우선 적용됩니다.

## 시연

데이터 입력의 예시 값 입력 → 향후 4주 유입량 예측 → 구호품 계획 설정으로 이동 →
구호품 계획의 예시 값 입력 → 최적화 결과 확인.
예시에는 가상 유입/분쟁/물류 수치가 사용되고 실제 연결 엔진이 계산합니다.
Medyka·Dorohusk·Korczowa를 선택할 수 있으며 한 번의 최적화는 선택 구호소 한 곳의 계획입니다.
지도 바탕 타일 표시에는 인터넷 연결이 필요합니다.

Node 입력 검사(공통 폴더에서):
```powershell
node --test ofr_v2/tests/test_ui_final_review.mjs ofr_v2/tests/test_ui_input.mjs ofr_v2/tests/test_two_week_ui.mjs
```
기존 브라우저 저장값이 있으면 예시 버튼으로 현재 시연 입력을 새로 채워주세요.
이번 파일 전달은 원격 배포나 현장 성능 인증을 의미하지 않습니다.

# Oracle Cloud 백엔드 배포 (현재 운영 구성)

화면은 Vercel(https://ime-olive.vercel.app), 백엔드는 Oracle Cloud Always Free VM에서 실행합니다.
현재 백엔드 주소: https://64-110-107-225.sslip.io (`/health`로 상태 확인)

| 파일 | 역할 |
|---|---|
| `Dockerfile.backend` | 백엔드 전용 이미지 (FastAPI, 포트 7860) |
| `docker-compose.yml` | 백엔드 + Caddy(HTTPS 자동 인증서, 응답 압축) |
| `Caddyfile` | `https://<IP를 -로 바꾼 값>.sslip.io` 로 서비스, zstd/gzip 압축 |
| `setup.sh` | Docker 설치, 방화벽(80/443) 열기, 빌드·실행 (재부팅 후 자동 시작) |

## 서버 만들기 (Always Free 범위)

- Ubuntu 22.04, Shape `VM.Standard.A1.Flex`, OCPU 2, 메모리 12GB (무료 한도 전체)
- Security List에 TCP 80, 443 Ingress 추가

## 설치

서버에 이 저장소를 복사한 뒤 저장소 루트에서:
```bash
bash deploy/oracle/setup.sh <서버 공인 IP>
```
1~2분 뒤 `https://<IP를 -로 바꾼 값>.sslip.io/health` 확인.
주소가 바뀌면 화면의 `ofr_v2/app/frontend/.env.production`과 `vercel.json`도 새 주소로 바꿔야 합니다.

## 성능 참고 (기준 주 2026-01-26 예시, 한국에서 접속)

| 구호소 | 도로 배차 최적화 응답 |
|---|---|
| Medyka | 약 8초 |
| Korczowa | 약 8초 |
| Dorohusk | 약 27초 (도로 자료가 많아 결과 약 28MB, 압축 후 약 5MB) |

서버 시작 직후 몇 분 동안은 창고 2곳 x 구호소 3곳의 도로 자료를 미리 읽는 중이라 첫 요청이 느릴 수 있습니다.
Always Free VM은 7일 동안 사용률이 매우 낮으면 Oracle이 회수할 수 있습니다.

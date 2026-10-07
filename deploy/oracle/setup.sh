#!/usr/bin/env bash
# Oracle Cloud Ubuntu VM에서 OFR 백엔드를 HTTPS로 실행한다.
# 사용법 (저장소 루트에서):  bash deploy/oracle/setup.sh <서버 공인 IP>
set -euo pipefail

IP="${1:?서버 공인 IP를 입력하세요. 예: bash deploy/oracle/setup.sh 140.238.1.2}"
DOMAIN="$(echo "$IP" | tr . -).sslip.io"
cd "$(dirname "$0")"

# 1) Docker 설치 (없을 때만)
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
fi

# 2) Oracle Ubuntu 이미지의 기본 방화벽(iptables)에서 80/443 열기
#    마지막의 REJECT 규칙보다 앞에 넣어야 적용된다
for port in 80 443; do
  if ! sudo iptables -C INPUT -p tcp --dport "$port" -m state --state NEW -j ACCEPT 2>/dev/null; then
    pos="$(sudo iptables -L INPUT -n --line-numbers | awk '$2 == "REJECT" {print $1; exit}')"
    sudo iptables -I INPUT "${pos:-1}" -p tcp --dport "$port" -m state --state NEW -j ACCEPT
  fi
done
if command -v netfilter-persistent >/dev/null 2>&1; then
  sudo netfilter-persistent save
fi

# 3) 빌드·실행 (서버 재부팅 후에도 자동 시작)
echo "DOMAIN=$DOMAIN" > .env
sudo docker compose up -d --build

echo
echo "완료. 1~2분 뒤 확인: https://$DOMAIN/health"

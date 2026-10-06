# OFR 통합 호스팅 이미지: 화면 빌드(Node) + API(Python)를 한 컨테이너에서 실행
# 빌드: docker build -t ofr .
# 실행: docker run -p 8000:8000 ofr   ->  http://localhost:8000

# 1) 화면 빌드
FROM node:22-slim AS ui
WORKDIR /ui
COPY ofr_v2/app/frontend/package.json ofr_v2/app/frontend/package-lock.json ./
RUN npm ci
COPY ofr_v2/app/frontend/ ./
# API를 같은 서버(상대 경로)로 호출하도록 빌드
ENV VITE_API_BASE=.
RUN npm run build

# 2) API 서버
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1
WORKDIR /srv
COPY ofr_v2/app/requirements.txt ofr_v2/app/requirements.txt
RUN pip install --no-cache-dir -r ofr_v2/app/requirements.txt
COPY ofr_v2/app ofr_v2/app
COPY ofr_v2/data ofr_v2/data
COPY --from=ui /ui/dist ofr_v2/app/frontend/dist
WORKDIR /srv/ofr_v2/app
EXPOSE 8000
# 호스팅 서비스가 PORT 환경변수를 주면 그 포트를 사용
CMD ["sh", "-c", "uvicorn serve:app --host 0.0.0.0 --port ${PORT:-8000}"]

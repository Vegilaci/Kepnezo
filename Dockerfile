# Build the React bundle in the image; Node.js is not needed on the NAS.
FROM node:22-alpine AS frontend-build
WORKDIR /build/frontend
COPY Frontend/package.json Frontend/package-lock.json ./
RUN npm ci
COPY Frontend/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine AS web
COPY deploy/nginx-container.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /build/frontend/dist/ /usr/share/nginx/html/
EXPOSE 8080

FROM python:3.13-slim AS backend
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SHARED_ROOT=/data \
    TMPDIR=/data/.family-share-tmp
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY Backend/ ./backend/
EXPOSE 8000
CMD ["python", "backend/scripts/container_start.py"]

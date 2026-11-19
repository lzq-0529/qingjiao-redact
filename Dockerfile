# Stage 1: Build React workbench UI
FROM node:22-alpine AS frontend-builder
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime with FastAPI + ModelScope RaNER
FROM python:3.11-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MODELSCOPE_CACHE=/app/.model_cache/modelscope \
    QINGJIAO_DATA_DIR=/app/data \
    QINGJIAO_STATIC_DIR=/app/static

COPY backend/requirements.txt backend/requirements-ner.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && pip install --no-cache-dir -r backend/requirements-ner.txt

COPY pyproject.toml README.md ./
COPY backend/ ./backend/
COPY benchmarks/ ./benchmarks/
COPY --from=frontend-builder /web/dist ./static

RUN pip install --no-cache-dir --no-deps -e .

EXPOSE 8000
VOLUME ["/app/data", "/app/.model_cache"]

CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]

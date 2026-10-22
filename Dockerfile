# Compiled Vite app + FastAPI served together under the same origin on Render.
FROM node:22-alpine AS ui
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./backend/
COPY src/ ./src/
COPY data/seed/ ./data/seed/
COPY data/raw/ ./data/raw/
COPY data/processed/ ./data/processed/
COPY --from=ui /app/frontend/dist ./frontend/dist
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1"]

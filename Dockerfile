# Production Dockerfile — Resume AI Builder
# Multi-stage: build client static files → serve with FastAPI (single
# container hosts both UI and API). PDF compilation happens on an external
# LaTeX MCP server, so no TeX Live is installed in this image.
FROM node:22-alpine AS client-build
WORKDIR /app/client
COPY client/package.json ./
RUN npm install
COPY client/ ./
RUN npm run build

FROM python:3.13-slim AS server
WORKDIR /app

# Install system deps (libpq for asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && pip install bcrypt

# Copy server source — preserve module structure (server.main imports from server.config etc.)
COPY server/ ./server/
COPY --from=client-build /app/client/dist ./server/static/

# Bundle the fallback template
COPY template/master_resume.tex ./template/master_resume.tex

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

FROM python:3.12-slim

# Node.js ve Prisma CLI için gerekli sistem kütüphanelerini yükle (libatomic1, openssl, ca-certificates, curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libatomic1 \
    openssl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# UV Paket Yöneticisini Yükle
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Bağımlılıkları ve Proje Dosyalarını Kopyala
COPY pyproject.toml uv.lock ./
COPY prisma ./prisma
COPY server.py prompts.py mcp_utils.py data.db .env ./

# Bağımlılıkları Kur ve Prisma Client Üret
RUN uv sync --frozen
RUN uv run prisma generate

# HTTP SSE Portunu Aç
EXPOSE 8000

# MCP Sunucusunu SSE HTTP Modunda Başlat
CMD ["uv", "run", "python", "server.py"]

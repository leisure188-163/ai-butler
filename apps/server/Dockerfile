# 构建上下文必须是 monorepo 根目录（server 依赖 workspace 里的 core 包）
FROM python:3.12-slim
WORKDIR /app

# 安装 uv 并复制 workspace 关键部分
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/core/src packages/core/src
COPY apps/server/src apps/server/src

RUN uv pip install --system --no-cache .
CMD ["uvicorn", "server.main:app", "--host", "0.0.0.0", "--port", "8000"]

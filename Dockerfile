FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

ENV PORT=8000
EXPOSE 8000

# 배포 헬스체크는 DB까지 확인하는 /health/ready를 봐야 한다.
CMD ["./scripts/start.sh"]

#!/usr/bin/env sh
# 컨테이너 진입점 — 마이그레이션을 먼저 적용하고 서버를 띄운다.
set -e
uv run alembic upgrade head
exec uv run uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"

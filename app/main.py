from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import AsyncSessionLocal
from app.services.maintenance_service import fail_stale_jobs

settings = get_settings()
configure_logging()
logger = structlog.get_logger()

if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # 생기부는 민감 정보라 요청 본문이나 헤더가 Sentry로 새어 나가면 안 된다.
        send_default_pii=False,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await fail_stale_jobs()
    yield


app = FastAPI(title="세특연구소 API", lifespan=lifespan)
app.add_middleware(RequestContextMiddleware)
app.include_router(api_router)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.info("app error", error_code=exc.error_code, message=exc.message)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error_code": exc.error_code, "message": exc.message},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """검증 오류도 공통 에러 형식으로 통일한다 — 클라이언트가 FastAPI 기본
    {"detail": [...]}와 우리 형식을 둘 다 처리하지 않아도 되게."""
    return JSONResponse(
        status_code=422,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": "요청 형식이 올바르지 않습니다",
            "details": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error")
    return JSONResponse(
        status_code=500,
        content={"error_code": "INTERNAL_ERROR", "message": "일시적인 오류가 발생했습니다"},
    )


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def readiness() -> dict[str, str]:
    """DB까지 확인하는 준비 상태 점검 — 배포 헬스체크는 이쪽을 봐야 한다."""
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT 1"))
    return {"status": "ready"}

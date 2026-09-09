"""structlog 설정 — 표준 logging까지 같은 파이프라인으로 흘려보낸다.

운영에서는 JSON 한 줄씩(로그 수집기가 파싱), 로컬에서는 사람이 읽는 컬러 출력으로
렌더링한다. contextvars를 쓰기 때문에 request_id/user_id를 한 번 bind해 두면 그
요청에서 발생한 모든 로그(우리 코드든 SQLAlchemy든)에 자동으로 따라붙는다.
"""

import logging
import sys

import structlog

from app.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if settings.log_json
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        # 렌더링은 stdlib 핸들러의 ProcessorFormatter가 전담한다. 여기서 renderer를
        # 함께 쓰면 structlog 로그가 한 번 렌더된 뒤 다시 포맷돼 두 번 찍힌다.
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.log_level.upper()]
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                renderer,
            ],
        )
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level.upper())

    # uvicorn은 자체 핸들러를 달아 두어 그대로 두면 로그가 두 번 찍힌다.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

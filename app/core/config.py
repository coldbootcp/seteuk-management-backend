from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/seteuk"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14

    anthropic_api_key: str | None = None
    kakao_client_id: str | None = None
    kakao_client_secret: str | None = None
    # 카카오와 완전히 같은 패턴 — 클라이언트가 Google OAuth2 access token만
    # 받아 넘기고, 백엔드는 그 토큰으로 구글 userinfo API를 직접 불러 신원을
    # 확인한다. 이 값은 클라이언트 SDK 설정용이라 서버 동작에는 필수가 아니다.
    google_client_id: str | None = None
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.1
    environment: str = "local"

    # --- 이메일 발송 (Resend) ---
    resend_api_key: str | None = None
    # Resend에 검증된 발신 도메인의 주소여야 한다. 비워 두면(로컬 개발 등)
    # 이메일을 실제로 보내지 않고 로그로만 남긴다 — 카카오 버튼이 키 없으면
    # '준비 중'으로 빠지는 것과 같은 자세.
    email_from: str = "세특연구소 <onboarding@resend.dev>"
    # 인증·재설정 링크가 가리킬 프론트엔드 주소. 백엔드와 다른 오리진에서 돈다.
    frontend_base_url: str = "http://localhost:3100"
    email_verification_token_expire_hours: int = 24
    password_reset_token_expire_minutes: int = 60
    # 탈퇴 요청 후 완전 삭제까지의 유예 기간.
    account_deletion_grace_days: int = 30

    log_level: str = "INFO"
    # 운영에서는 JSON 한 줄, 로컬에서는 사람이 읽는 출력.
    log_json: bool = False

    # 웹 프론트엔드와 API가 서로 다른 오리진에서 도는 구조라(로컬은 3000 vs 8000,
    # 운영은 별도 도메인) 브라우저가 요청을 보내려면 CORS 허용이 필요하다.
    # 콤마로 구분된 오리진 목록.
    cors_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3100,http://127.0.0.1:3100"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    # 하루(24시간 슬라이딩 윈도우) 사용자별 LLM 작업 한도.
    daily_upload_limit: int = 5
    daily_diagnosis_limit: int = 5
    daily_roadmap_limit: int = 10
    daily_recommendation_limit: int = 20
    daily_chat_message_limit: int = 100
    # 하루 한도를 실제로 적용할지. 비워 두면 환경으로 정한다 — 개발 중에는 같은
    # 시나리오를 하루에도 수십 번 태워야 해서 한도가 검증을 막는다. 운영에서는
    # 켜져 있어야 하므로 ENVIRONMENT를 production으로 두면 자동으로 적용된다.
    rate_limit_enabled: bool | None = None

    # processing 상태로 이 시간을 넘긴 job은 프로세스가 죽은 것으로 보고 실패 처리한다.
    stale_job_timeout_minutes: int = 30

    # 모델 프로바이더는 하네스 경계 뒤에 있다(P-3). 지금 붙어 있는 것은
    # DeepSeek 하나지만, 호출부를 바꾸지 않고 교체할 수 있어야 한다.
    llm_provider: str = "deepseek"
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    seteuk_llm_concurrency: int = 15
    # 모델 호출 타임아웃(초). SDK 기본값은 connect 5초인데, 파싱은 블록 15개를
    # 동시에 열기 때문에 그 5초에 걸려 멀쩡한 블록이 통째로 버려지는 일이 있었다.
    llm_connect_timeout_seconds: float = 20.0
    llm_read_timeout_seconds: float = 180.0


@lru_cache
def get_settings() -> Settings:
    return Settings()

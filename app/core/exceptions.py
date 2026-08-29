class AppError(Exception):
    status_code: int = 400
    error_code: str = "BAD_REQUEST"

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class EmailAlreadyExistsError(AppError):
    status_code = 409
    error_code = "EMAIL_ALREADY_EXISTS"


class InvalidCredentialsError(AppError):
    status_code = 401
    error_code = "INVALID_CREDENTIALS"


class InvalidTokenError(AppError):
    status_code = 401
    error_code = "INVALID_TOKEN"


class UserNotFoundError(AppError):
    status_code = 404
    error_code = "USER_NOT_FOUND"


class UnsupportedFileError(AppError):
    status_code = 422
    error_code = "UNSUPPORTED_FILE"


class UploadNotFoundError(AppError):
    status_code = 404
    error_code = "UPLOAD_NOT_FOUND"


class UploadNotReadyError(AppError):
    status_code = 409
    error_code = "UPLOAD_NOT_READY"


class LLMUnavailableError(AppError):
    status_code = 503
    error_code = "LLM_UNAVAILABLE"


class DiagnosisNotFoundError(AppError):
    status_code = 404
    error_code = "DIAGNOSIS_NOT_FOUND"


class DiagnosisNotReadyError(AppError):
    status_code = 409
    error_code = "DIAGNOSIS_NOT_READY"


class RecordNotFoundError(AppError):
    status_code = 404
    error_code = "RECORD_NOT_FOUND"


class ActivityNotFoundError(AppError):
    status_code = 404
    error_code = "ACTIVITY_NOT_FOUND"


class PlanItemNotFoundError(AppError):
    status_code = 404
    error_code = "PLAN_ITEM_NOT_FOUND"


class InvalidPlanTransitionError(AppError):
    status_code = 409
    error_code = "INVALID_PLAN_TRANSITION"


class ConversationNotFoundError(AppError):
    status_code = 404
    error_code = "CONVERSATION_NOT_FOUND"


class RecommendationNotFoundError(AppError):
    status_code = 404
    error_code = "RECOMMENDATION_NOT_FOUND"


class ProfileIncompleteError(AppError):
    status_code = 409
    error_code = "PROFILE_INCOMPLETE"


class SocialAuthError(AppError):
    status_code = 401
    error_code = "SOCIAL_AUTH_FAILED"


class RateLimitedError(AppError):
    status_code = 429
    error_code = "RATE_LIMITED"

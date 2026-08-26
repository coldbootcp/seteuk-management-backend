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

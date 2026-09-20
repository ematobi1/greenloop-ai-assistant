from app.errors import ApiError

PUBLIC_MESSAGES = {
    "timeout": "The model provider timed out",
    "unavailable": "The model provider is unavailable",
    "rejected": "The model provider rejected the request",
    "invalid_response": "The model provider returned an invalid response",
    "unsafe_configuration": "The model provider could not be started safely",
    "unknown_provider": "Unknown model provider",
    "context_too_large": "The message is too large for the model context",
}

HTTP_STATUS = {
    "timeout": 504,
    "unavailable": 503,
    "rejected": 502,
    "invalid_response": 502,
    "unsafe_configuration": 503,
    "unknown_provider": 422,
    "context_too_large": 422,
}


class AiError(Exception):
    """Failure inside the AI engine. The message is always safe to show to a client."""

    def __init__(self, code: str, retryable: bool = False):
        super().__init__(PUBLIC_MESSAGES[code])
        self.code = code
        self.retryable = retryable

    @property
    def public_message(self) -> str:
        return PUBLIC_MESSAGES[self.code]

    def to_api_error(self) -> ApiError:
        return ApiError(HTTP_STATUS[self.code], f"AI_{self.code.upper()}", self.public_message)

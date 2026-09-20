from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.errors import ApiError
from app.security.token import token_matches

bearer_scheme = HTTPBearer(auto_error=False)


def require_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> None:
    expected_hash = request.app.state.settings.api_token_hash
    if not expected_hash or credentials is None or not token_matches(
        credentials.credentials, expected_hash
    ):
        raise ApiError(
            401,
            "UNAUTHENTICATED",
            "Missing or invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(api_key: str | None = Security(api_key_header)) -> None:
    if api_key != get_settings().api_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing API key")

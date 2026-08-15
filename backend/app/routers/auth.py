from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from backend.app.auth.repository import DuplicateEmailError
from backend.app.auth.security import (
    InvalidAccessTokenError,
    create_access_token,
    decode_access_token,
)
from backend.app.auth.service import (
    AccountNotFoundError,
    AuthenticatedUser,
    AuthService,
    InvalidCredentialsError,
)
from backend.app.config import Settings
from backend.app.dependencies import get_app_settings, get_auth_service
from backend.app.schemas.auth import AuthUserResponse, LoginRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])
_rate_limit_lock = Lock()
_auth_attempts: dict[str, list[float]] = {}
_MAX_RATE_LIMIT_KEYS = 10_000


def get_auth_service_factory() -> Callable[[], AuthService]:
    return get_auth_service


def _settings(settings: Settings) -> Settings:
    if len(settings.auth_secret_key) < 32:
        raise HTTPException(status_code=503, detail="鉴权服务尚未配置")
    if settings.environment == "production" and not settings.auth_cookie_secure:
        raise HTTPException(status_code=503, detail="生产环境必须启用安全 Cookie")
    return settings


def _check_auth_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    allowed_origins = {allowed.rstrip("/") for allowed in settings.cors_origins}
    if origin is not None and origin.rstrip("/") not in allowed_origins:
        raise HTTPException(status_code=403, detail="请求来源不受信任")


def _check_auth_rate_limit(request: Request, settings: Settings) -> None:
    client_host = request.client.host if request.client else "unknown"
    key = f"{client_host}:{request.url.path}"
    now = monotonic()
    cutoff = now - settings.auth_rate_limit_window_seconds
    with _rate_limit_lock:
        expired_keys = [
            existing_key
            for existing_key, values in _auth_attempts.items()
            if not values or values[-1] < cutoff
        ]
        for expired_key in expired_keys:
            _auth_attempts.pop(expired_key, None)
        if key not in _auth_attempts and len(_auth_attempts) >= _MAX_RATE_LIMIT_KEYS:
            oldest_key = min(_auth_attempts, key=lambda item: _auth_attempts[item][-1])
            _auth_attempts.pop(oldest_key, None)
        attempts = [value for value in _auth_attempts.get(key, []) if value >= cutoff]
        if len(attempts) >= settings.auth_rate_limit_attempts:
            raise HTTPException(status_code=429, detail="尝试次数过多，请稍后再试")
        attempts.append(now)
        _auth_attempts[key] = attempts


def _set_session(response: Response, user: AuthenticatedUser, settings: Settings) -> None:
    token = create_access_token(
        user.user_id,
        settings.auth_secret_key,
        expires_delta=timedelta(minutes=settings.auth_access_token_minutes),
    )
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.auth_access_token_minutes * 60,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )


def _response(user: AuthenticatedUser) -> AuthUserResponse:
    return AuthUserResponse(**user.__dict__)


def get_current_user(
    request: Request,
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_app_settings),
) -> AuthenticatedUser:
    configured = _settings(settings)
    session_token = request.cookies.get(configured.auth_cookie_name)
    if not session_token:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        return service.get_user(decode_access_token(session_token, configured.auth_secret_key))
    except (InvalidAccessTokenError, AccountNotFoundError) as exc:
        raise HTTPException(status_code=401, detail="登录状态已失效") from exc


def require_current_user_when_auth_enabled(
    request: Request,
    settings: Settings = Depends(get_app_settings),
    service_factory: Callable[[], AuthService] = Depends(get_auth_service_factory),
) -> AuthenticatedUser | None:
    if not settings.auth_secret_key:
        if settings.allow_unauthenticated_research_api:
            return None
        raise HTTPException(status_code=503, detail="鉴权密钥未配置")
    current_user = get_current_user(request=request, service=service_factory(), settings=settings)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        _check_auth_origin(request, settings)
    return current_user


def authorize_user_access(
    target_user_id: int,
    current_user: AuthenticatedUser | None,
    service_factory: Callable[[], AuthService],
) -> None:
    if current_user is None:
        return
    if not service_factory().can_access_user(current_user, target_user_id):
        raise HTTPException(status_code=403, detail="无权访问其他用户数据")


@router.post("/register", response_model=AuthUserResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_app_settings),
) -> AuthUserResponse:
    configured = _settings(settings)
    _check_auth_origin(request, configured)
    _check_auth_rate_limit(request, configured)
    try:
        user = service.register(str(payload.email), payload.display_name, payload.password)
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail="该邮箱已注册") from exc
    _set_session(response, user, configured)
    return _response(user)


@router.post("/login", response_model=AuthUserResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_app_settings),
) -> AuthUserResponse:
    configured = _settings(settings)
    _check_auth_origin(request, configured)
    _check_auth_rate_limit(request, configured)
    try:
        user = service.authenticate(str(payload.email), payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_session(response, user, configured)
    return _response(user)


@router.get("/me", response_model=AuthUserResponse)
def me(current_user: AuthenticatedUser = Depends(get_current_user)) -> AuthUserResponse:
    return _response(current_user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_app_settings),
) -> Response:
    _check_auth_origin(request, settings)
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response

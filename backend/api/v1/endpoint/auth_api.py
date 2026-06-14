from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.api.dependencies import (
    get_audit_service,
    get_feature_flag_service,
    get_login_data,
    get_user_service,
)
from backend.api.deps.services import get_google_oauth_service, get_sms_service
from backend.config.settings import settings
from backend.core.exceptions import app_bad_request
from backend.core.security import create_access_token
from backend.middleware.rate_limit import RateLimiter
from backend.models.enums import AuditOutcome
from backend.models.schemas.user_schema import (
    GoogleAuthUrlResponse,
    GoogleCallbackRequest,
    PhoneLoginRequest,
    SMSSendRequest,
    SMSSendResponse,
    Token,
    UserCreate,
    UserLogin,
    UserResponse,
)
from backend.services.audit_service import AuditAction, AuditService, record_audit
from backend.services.feature_flag_service import FeatureFlagService
from backend.services.google_oauth_service import GoogleOAuthService
from backend.services.sms_service import SMSService
from backend.services.user_service import UserService

router = APIRouter()
register_limiter = RateLimiter(
    times=settings.AUTH_REGISTER_RATE_LIMIT_TIMES,
    seconds=settings.AUTH_REGISTER_RATE_LIMIT_SECONDS,
)
login_limiter = RateLimiter(
    times=settings.AUTH_LOGIN_RATE_LIMIT_TIMES,
    seconds=settings.AUTH_LOGIN_RATE_LIMIT_SECONDS,
)
sms_limiter = RateLimiter(
    times=settings.SMS_SEND_RATE_LIMIT_TIMES,
    seconds=settings.SMS_SEND_RATE_LIMIT_SECONDS,
)
sms_login_limiter = RateLimiter(
    times=settings.AUTH_SMS_LOGIN_RATE_LIMIT_TIMES,
    seconds=settings.AUTH_SMS_LOGIN_RATE_LIMIT_SECONDS,
)
google_callback_limiter = RateLimiter(
    times=settings.AUTH_GOOGLE_CALLBACK_RATE_LIMIT_TIMES,
    seconds=settings.AUTH_GOOGLE_CALLBACK_RATE_LIMIT_SECONDS,
)
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
LoginDataDep = Annotated[UserLogin, Depends(get_login_data)]
AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]
SMSServiceDep = Annotated[SMSService, Depends(get_sms_service)]
GoogleOAuthServiceDep = Annotated[GoogleOAuthService, Depends(get_google_oauth_service)]
FeatureFlagServiceDep = Annotated[FeatureFlagService, Depends(get_feature_flag_service)]


@router.get("/config")
async def get_system_config(
    feature_flag_service: FeatureFlagServiceDep,
) -> dict[str, bool]:
    """获取系统级公开灰度/控制开关（免登录）。"""
    return await feature_flag_service.get_system_features()


@router.post("/register", dependencies=[Depends(register_limiter)])
async def register(
    user_in: UserCreate,
    user_service: UserServiceDep,
    feature_flag_service: FeatureFlagServiceDep,
) -> UserResponse:
    system_flags = await feature_flag_service.get_system_features()
    if not system_flags.get("enable-public-registration", True):
        raise app_bad_request(
            "当前处于封闭内测阶段，暂不开放公开注册", code="REGISTRATION_CLOSED"
        )

    async with user_service.write():
        user = await user_service.user_register_with_personal_workspace(user_in)
    return UserResponse.model_validate(user)


@router.post("/login", dependencies=[Depends(login_limiter)])
async def login(
    login_data: LoginDataDep,
    user_service: UserServiceDep,
    audit_service: AuditServiceDep,
    feature_flag_service: FeatureFlagServiceDep,
) -> Token:
    # 1. 调用 Service 验证
    async with user_service.write():
        user = await user_service.authenticate(login_data)
        if not user:
            await record_audit(
                audit_service,
                action=AuditAction.AUTH_LOGIN_FAILED,
                outcome=AuditOutcome.FAILED,
                metadata={
                    "username": login_data.username,
                    "reason": "bad_credentials",
                },
            )
            raise app_bad_request("用户名或密码错误", code="BAD_CREDENTIALS")

        if not user.is_active:
            await record_audit(
                audit_service,
                action=AuditAction.AUTH_LOGIN_FAILED,
                actor_user_id=user.id,
                outcome=AuditOutcome.FAILED,
                metadata={
                    "username": login_data.username,
                    "reason": "inactive_user",
                },
            )
            raise app_bad_request("用户名或密码错误", code="BAD_CREDENTIALS")

    # 2. 校验封闭内测登录限制（在写事务之外，用户标量属性已加载到内存）
    system_flags = await feature_flag_service.get_system_features()
    if system_flags.get(
        "enable-closed-beta-login", False
    ) and not feature_flag_service.is_beta_user(user):
        raise app_bad_request(
            "系统正在维护或处于封闭内测中，当前仅限内测人员登录",
            code="BETA_LIMIT_LOGIN",
        )

    # 3. 发放 Token (Token 生成是纯 CPU 计算，无需 await)
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id,
        expires_delta=access_token_expires,
    )
    await record_audit(
        audit_service,
        action=AuditAction.AUTH_LOGIN_SUCCESS,
        actor_user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        metadata={"username": login_data.username},
    )
    return Token(access_token=access_token, token_type="bearer")  # noqa: S106


# ── SMS Verification ──────────────────────────────────────────────


@router.post("/sms/send", dependencies=[Depends(sms_limiter)])
async def sms_send(body: SMSSendRequest, sms_service: SMSServiceDep) -> SMSSendResponse:
    """发送短信验证码。"""
    await sms_service.send_code(body.phone)
    return SMSSendResponse(
        message="验证码已发送",
    )


@router.post("/sms/login", dependencies=[Depends(sms_login_limiter)])
async def sms_login(
    body: PhoneLoginRequest,
    user_service: UserServiceDep,
    sms_service: SMSServiceDep,
    audit_service: AuditServiceDep,
    feature_flag_service: FeatureFlagServiceDep,
) -> Token:
    """手机号 + 验证码登录（首次自动注册）。"""
    if not await sms_service.verify_code(body.phone, body.code):
        raise app_bad_request("验证码错误或已过期", code="INVALID_SMS_CODE")

    # 事务前获取注册开关，传入 service 原子判定
    system_flags = await feature_flag_service.get_system_features()
    allow_new = system_flags.get("enable-public-registration", True)

    async with user_service.write():
        user = await user_service.find_or_create_by_phone(
            body.phone, allow_new_registration=allow_new
        )

    if not user.is_active:
        raise app_bad_request("账号已停用", code="INACTIVE_USER")

    # 校验封闭内测登录限制（在写事务之外）
    system_flags = await feature_flag_service.get_system_features()
    if system_flags.get(
        "enable-closed-beta-login", False
    ) and not feature_flag_service.is_beta_user(user):
        raise app_bad_request(
            "系统正在维护或处于封闭内测中，当前仅限内测人员登录",
            code="BETA_LIMIT_LOGIN",
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id,
        expires_delta=access_token_expires,
    )
    await record_audit(
        audit_service,
        action=AuditAction.AUTH_SMS_LOGIN_SUCCESS,
        actor_user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        metadata={"phone": body.phone, "auth_provider": "phone"},
    )
    return Token(access_token=access_token, token_type="bearer")  # noqa: S106


# ── Google OAuth ──────────────────────────────────────────────────


@router.get("/google/url")
async def google_auth_url(
    redirect_uri: Annotated[str, Query(description="前端回调地址")],
    google_service: GoogleOAuthServiceDep = GoogleOAuthServiceDep,  # type: ignore[assignment]
) -> GoogleAuthUrlResponse:
    """获取 Google OAuth2 授权跳转 URL。"""
    url = google_service.get_authorization_url(redirect_uri)
    return GoogleAuthUrlResponse(url=url)


@router.post("/google/callback", dependencies=[Depends(google_callback_limiter)])
async def google_callback(
    body: GoogleCallbackRequest,
    user_service: UserServiceDep,
    google_service: GoogleOAuthServiceDep,
    audit_service: AuditServiceDep,
    feature_flag_service: FeatureFlagServiceDep,
) -> Token:
    """用 Google 授权码换取 JWT（首次自动注册）。"""
    claims = await google_service.exchange_code(body.code, body.redirect_uri)

    # 事务前获取注册开关，传入 service 原子判定
    system_flags = await feature_flag_service.get_system_features()
    allow_new = system_flags.get("enable-public-registration", True)

    async with user_service.write():
        user = await user_service.find_or_create_by_google(
            google_sub=claims["sub"],
            email=claims.get("email"),
            name=claims.get("name"),
            allow_new_registration=allow_new,
        )

    if not user.is_active:
        raise app_bad_request("账号已停用", code="INACTIVE_USER")

    # 校验封闭内测登录限制（在写事务之外）
    system_flags = await feature_flag_service.get_system_features()
    if system_flags.get(
        "enable-closed-beta-login", False
    ) and not feature_flag_service.is_beta_user(user):
        raise app_bad_request(
            "系统正在维护或处于封闭内测中，当前仅限内测人员登录",
            code="BETA_LIMIT_LOGIN",
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        subject=user.id,
        expires_delta=access_token_expires,
    )
    await record_audit(
        audit_service,
        action=AuditAction.AUTH_GOOGLE_LOGIN_SUCCESS,
        actor_user_id=user.id,
        resource_type="user",
        resource_id=user.id,
        metadata={"google_sub": claims["sub"], "auth_provider": "google"},
    )
    return Token(access_token=access_token, token_type="bearer")  # noqa: S106

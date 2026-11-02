import hmac
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from bson import ObjectId
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymongo.errors import DuplicateKeyError

from app.core.config import get_settings
from app.core.mailer import send_email
from app.core.rate_limit import check_request_limit
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.db.client import get_database, get_mongo_client

GENERIC_RECOVERY_MESSAGE = "If the account can be recovered, an email will be sent."
GENERIC_VERIFICATION_MESSAGE = "If the account can be verified, an email will be sent."
GENERIC_REGISTRATION_MESSAGE = "If registration can be completed, check your email for next steps."
SESSION_COOKIE_PATH = "/"


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    password: str
    organization_name: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        try:
            return validate_email(value, check_deliverability=False).normalized.lower()
        except EmailNotValidError as error:
            raise ValueError("Enter a valid email address.") from error

    @field_validator("full_name", "organization_name")
    @classmethod
    def trim_required_names(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field cannot be blank.")
        return normalized

    @field_validator("password")
    @classmethod
    def enforce_password_length(cls, value: str) -> str:
        if len(value) < 12:
            raise ValueError("Password must contain at least 12 characters.")
        if len(value) > 256:
            raise ValueError("Password must contain no more than 256 characters.")
        return value


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        try:
            return validate_email(value, check_deliverability=False).normalized.lower()
        except EmailNotValidError as error:
            raise ValueError("Enter a valid email address.") from error


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class RecoveryRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        try:
            return validate_email(value, check_deliverability=False).normalized.lower()
        except EmailNotValidError as error:
            raise ValueError("Enter a valid email address.") from error


class PasswordResetRequest(TokenRequest):
    password: str

    @field_validator("password")
    @classmethod
    def enforce_password_length(cls, value: str) -> str:
        if len(value) < 12:
            raise ValueError("Password must contain at least 12 characters.")
        if len(value) > 256:
            raise ValueError("Password must contain no more than 256 characters.")
        return value


class FactoryCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=160)


@dataclass(frozen=True)
class Principal:
    user_id: ObjectId
    organization_id: ObjectId
    role: str
    email: str
    full_name: str
    organization_name: str
    organization_slug: str


def require_csrf(request: Request) -> None:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    settings = get_settings()
    cookie_token = request.cookies.get(settings.csrf_cookie_name, "")
    header_token = request.headers.get("X-CSRF-Token", "")
    if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="A valid CSRF token is required.")


router = APIRouter(dependencies=[Depends(require_csrf)])


def _rate_limit(request: Request, action: str, identity: str, limit: int) -> None:
    check_request_limit(
        request,
        action=action,
        identity=identity,
        limit=limit,
    )


def _public_link(path: str, token: str) -> str:
    return f"{get_settings().public_app_url.rstrip('/')}{path}?token={quote(token)}"


def _duration_label(seconds: int) -> str:
    for unit, divisor in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds % divisor == 0:
            value = seconds // divisor
            return f"{value} {unit}{'' if value == 1 else 's'}"
    return f"{seconds} seconds"


def _send_verification_email(email: str, token: str) -> None:
    expiration = _duration_label(get_settings().verification_ttl_seconds)
    send_email(
        email,
        "Verify your RealityLoop AI account",
        "Verify your email address using this one-time link:\n\n"
        f"{_public_link('/app/verify', token)}\n\n"
        f"This link expires after {expiration}. "
        "If you did not request this account, ignore this email.",
    )


def _send_password_reset_email(email: str, token: str) -> None:
    expiration = _duration_label(get_settings().password_reset_ttl_seconds)
    send_email(
        email,
        "Reset your RealityLoop AI password",
        "Choose a new password using this one-time link:\n\n"
        f"{_public_link('/app/reset-password', token)}\n\n"
        f"This link expires after {expiration}. "
        "If you did not request this change, ignore this email.",
    )


def _set_auth_cookies(response: Response, session_token: str) -> None:
    settings = get_settings()
    csrf_token = create_token()
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=SESSION_COOKIE_PATH,
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        max_age=settings.session_ttl_seconds,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        path=SESSION_COOKIE_PATH,
    )


def _clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        settings.session_cookie_name,
        path=SESSION_COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        path=SESSION_COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=False,
        samesite="strict",
    )


def _run_transaction(callback):
    with get_mongo_client().start_session() as session:
        return session.with_transaction(callback)


def _session_options(session) -> dict[str, object]:
    return {"session": session} if session is not None else {}


def _store_auth_token(
    *,
    user_id: ObjectId,
    token_type: str,
    token: str,
    expires_at: datetime,
) -> None:
    now = datetime.now(UTC)

    def operation(session) -> None:
        database = get_database()
        database.auth_tokens.delete_many(
            {"user_id": user_id, "token_type": token_type},
            **_session_options(session),
        )
        database.auth_tokens.insert_one(
            {
                "_id": hash_token(token),
                "user_id": user_id,
                "token_type": token_type,
                "expires_at": expires_at,
                "created_at": now,
            },
            **_session_options(session),
        )

    _run_transaction(operation)


def _slug_for_organization(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-") or "workspace"
    return f"{base[:55].rstrip('-')}-{ObjectId()!s}"


def _issue_session(user_id: ObjectId, organization_id: ObjectId) -> str:
    settings = get_settings()
    raw_token = create_token()
    now = datetime.now(UTC)
    get_database().sessions.insert_one(
        {
            "_id": hash_token(raw_token),
            "user_id": user_id,
            "organization_id": organization_id,
            "created_at": now,
            "expires_at": now + timedelta(seconds=settings.session_ttl_seconds),
            "last_seen_at": now,
        }
    )
    return raw_token


def get_current_principal(request: Request) -> Principal:
    raw_token = request.cookies.get(get_settings().session_cookie_name)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Sign in to continue.")

    now = datetime.now(UTC)
    session = get_database().sessions.find_one(
        {"_id": hash_token(raw_token), "expires_at": {"$gt": now}}
    )
    if session is None:
        raise HTTPException(status_code=401, detail="Your session has expired. Sign in again.")

    database = get_database()
    user = database.users.find_one(
        {"_id": session["user_id"], "email_verified_at": {"$ne": None}}
    )
    membership = database.organization_memberships.find_one(
        {
            "user_id": session["user_id"],
            "organization_id": session["organization_id"],
        }
    )
    organization = database.organizations.find_one({"_id": session["organization_id"]})
    if user is None or membership is None or organization is None:
        database.sessions.delete_one({"_id": session["_id"]})
        raise HTTPException(status_code=401, detail="Your workspace session is no longer valid.")

    return Principal(
        user_id=user["_id"],
        organization_id=organization["_id"],
        role=membership["role"],
        email=user["email"],
        full_name=user["full_name"],
        organization_name=organization["name"],
        organization_slug=organization["slug"],
    )


def require_roles(*roles: str):
    def dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(status_code=403, detail="Your workspace role cannot perform this action.")
        return principal

    return dependency


def _parse_object_id(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=404, detail="Factory not found.")
    return ObjectId(value)


@router.get("/csrf")
def issue_csrf_token(response: Response) -> dict[str, str]:
    settings = get_settings()
    token = create_token()
    response.set_cookie(
        settings.csrf_cookie_name,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        path=SESSION_COOKIE_PATH,
    )
    return {"csrf_token": token}


@router.post("/auth/register", status_code=202)
def register(payload: RegisterRequest, request: Request) -> dict[str, str]:
    settings = get_settings()
    _rate_limit(request, "register", "all", settings.auth_register_limit)
    password_hash = hash_password(payload.password)
    now = datetime.now(UTC)
    user_id = ObjectId()
    organization_id = ObjectId()
    verification_token = create_token()
    slug = _slug_for_organization(payload.organization_name)

    def operation(session) -> None:
        database = get_database()
        database.users.insert_one(
            {
                "_id": user_id,
                "email": payload.email,
                "full_name": payload.full_name,
                "password_hash": password_hash,
                "email_verified_at": None,
                "created_at": now,
                "updated_at": now,
            },
            **_session_options(session),
        )
        database.organizations.insert_one(
            {
                "_id": organization_id,
                "name": payload.organization_name,
                "slug": slug,
                "created_at": now,
                "updated_at": now,
            },
            **_session_options(session),
        )
        database.organization_memberships.insert_one(
            {
                "organization_id": organization_id,
                "user_id": user_id,
                "role": "owner",
                "created_at": now,
                "updated_at": now,
            },
            **_session_options(session),
        )
        database.auth_tokens.insert_one(
            {
                "_id": hash_token(verification_token),
                "user_id": user_id,
                "token_type": "email_verification",
                "expires_at": now + timedelta(seconds=settings.verification_ttl_seconds),
                "created_at": now,
            },
            **_session_options(session),
        )

    try:
        _run_transaction(operation)
    except DuplicateKeyError:
        return {"message": GENERIC_REGISTRATION_MESSAGE}

    _send_verification_email(payload.email, verification_token)
    return {"message": GENERIC_REGISTRATION_MESSAGE}


@router.post("/auth/verify")
def verify_email(payload: TokenRequest, request: Request) -> dict[str, str]:
    _rate_limit(request, "verify-token", "all", get_settings().auth_verification_limit)
    now = datetime.now(UTC)
    digest = hash_token(payload.token)

    def operation(session) -> bool:
        database = get_database()
        token_record = database.auth_tokens.find_one_and_delete(
            {
                "_id": digest,
                "token_type": "email_verification",
                "expires_at": {"$gt": now},
            },
            **_session_options(session),
        )
        if token_record is None:
            return False
        result = database.users.update_one(
            {"_id": token_record["user_id"], "email_verified_at": None},
            {"$set": {"email_verified_at": now, "updated_at": now}},
            **_session_options(session),
        )
        return result.modified_count == 1

    if not _run_transaction(operation):
        raise HTTPException(status_code=400, detail="This verification link is invalid or expired.")
    return {"message": "Email verified. Sign in to open your workspace."}


@router.post("/auth/resend-verification", status_code=202)
def resend_verification(payload: RecoveryRequest, request: Request) -> dict[str, str]:
    _rate_limit(request, "verification", payload.email, get_settings().auth_verification_limit)
    user = get_database().users.find_one({"email": payload.email})
    if user is None or user.get("email_verified_at") is not None:
        return {"message": GENERIC_VERIFICATION_MESSAGE}

    token = create_token()
    _store_auth_token(
        user_id=user["_id"],
        token_type="email_verification",
        token=token,
        expires_at=datetime.now(UTC)
        + timedelta(seconds=get_settings().verification_ttl_seconds),
    )
    _send_verification_email(payload.email, token)
    return {"message": GENERIC_VERIFICATION_MESSAGE}


@router.post("/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, str]:
    settings = get_settings()
    _rate_limit(request, "login", "all", settings.auth_login_limit)
    _rate_limit(request, "login-email", payload.email, settings.auth_login_limit)
    database = get_database()
    user = database.users.find_one({"email": payload.email})
    stored_hash = (user.get("password_hash") if user else None) or DUMMY_PASSWORD_HASH
    password_matches = verify_password(payload.password, stored_hash)
    if user is None or not password_matches:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    if user.get("email_verified_at") is None:
        raise HTTPException(status_code=403, detail="Verify your email before signing in.")

    membership = database.organization_memberships.find_one({"user_id": user["_id"]})
    if membership is None:
        raise HTTPException(status_code=403, detail="No workspace membership is available.")
    raw_session = _issue_session(user["_id"], membership["organization_id"])
    _set_auth_cookies(response, raw_session)
    return {"message": "Signed in.", "redirect": "/app/dashboard"}


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict[str, str]:
    raw_token = request.cookies.get(get_settings().session_cookie_name)
    if raw_token:
        get_database().sessions.delete_one({"_id": hash_token(raw_token)})
    _clear_auth_cookies(response)
    return {"message": "Signed out."}


@router.post("/auth/password-reset/request", status_code=202)
def request_password_reset(
    payload: RecoveryRequest,
    request: Request,
) -> dict[str, str]:
    _rate_limit(request, "recovery", "all", get_settings().auth_recovery_limit)
    _rate_limit(request, "recovery-email", payload.email, get_settings().auth_recovery_limit)
    user = get_database().users.find_one({"email": payload.email})
    if user is not None:
        token = create_token()
        _store_auth_token(
            user_id=user["_id"],
            token_type="password_reset",
            token=token,
            expires_at=datetime.now(UTC)
            + timedelta(seconds=get_settings().password_reset_ttl_seconds),
        )
        _send_password_reset_email(payload.email, token)
    return {"message": GENERIC_RECOVERY_MESSAGE}


@router.post("/auth/password-reset/confirm")
def confirm_password_reset(payload: PasswordResetRequest, request: Request) -> dict[str, str]:
    _rate_limit(request, "reset-confirm", "all", get_settings().auth_recovery_limit)
    now = datetime.now(UTC)
    digest = hash_token(payload.token)
    new_password_hash = hash_password(payload.password)

    def operation(session) -> ObjectId | None:
        database = get_database()
        token_record = database.auth_tokens.find_one_and_delete(
            {
                "_id": digest,
                "token_type": "password_reset",
                "expires_at": {"$gt": now},
            },
            **_session_options(session),
        )
        if token_record is None:
            return None
        database.users.update_one(
            {"_id": token_record["user_id"]},
            {"$set": {"password_hash": new_password_hash, "updated_at": now}},
            **_session_options(session),
        )
        database.sessions.delete_many(
            {"user_id": token_record["user_id"]},
            **_session_options(session),
        )
        return token_record["user_id"]

    if _run_transaction(operation) is None:
        raise HTTPException(status_code=400, detail="This password reset link is invalid or expired.")
    return {"message": "Password updated. Sign in using your new password."}


@router.get("/auth/me")
def get_me(principal: Principal = Depends(get_current_principal)) -> dict[str, object]:
    return {
        "user": {
            "id": str(principal.user_id),
            "full_name": principal.full_name,
            "email": principal.email,
        },
        "organization": {
            "id": str(principal.organization_id),
            "name": principal.organization_name,
            "slug": principal.organization_slug,
            "role": principal.role,
        },
    }


@router.get("/dashboard")
def get_dashboard(principal: Principal = Depends(get_current_principal)) -> dict[str, object]:
    database = get_database()
    factory_count = database.factories.count_documents(
        {"organization_id": principal.organization_id}
    )
    completed_steps = 1 + min(factory_count, 1)
    return {
        "user": {
            "full_name": principal.full_name,
            "email": principal.email,
        },
        "organization": {
            "id": str(principal.organization_id),
            "name": principal.organization_name,
            "slug": principal.organization_slug,
            "role": principal.role,
        },
        "factory_count": factory_count,
        "onboarding": {
            "completed": completed_steps,
            "total": 2,
            "steps": [
                {"key": "workspace", "label": "Workspace verified", "complete": True},
                {
                    "key": "factory",
                    "label": "Create your first factory",
                    "complete": factory_count > 0,
                },
            ],
        },
    }


@router.get("/factories")
def list_factories(principal: Principal = Depends(get_current_principal)) -> dict[str, object]:
    records = get_database().factories.find(
        {"organization_id": principal.organization_id}
    ).sort("created_at", 1)
    return {
        "factories": [
            {"id": str(record["_id"]), "name": record["name"]}
            for record in records
        ]
    }


@router.post("/factories", status_code=201)
def create_factory(
    payload: FactoryCreateRequest,
    principal: Principal = Depends(require_roles("owner", "administrator", "engineer")),
) -> dict[str, str]:
    now = datetime.now(UTC)
    document = {
        "organization_id": principal.organization_id,
        "name": payload.name,
        "created_at": now,
        "updated_at": now,
    }
    result = get_database().factories.insert_one(document)
    return {"id": str(result.inserted_id), "name": payload.name}


@router.get("/factories/{factory_id}")
def get_factory(
    factory_id: str,
    principal: Principal = Depends(get_current_principal),
) -> dict[str, str]:
    factory = get_database().factories.find_one(
        {
            "_id": _parse_object_id(factory_id),
            "organization_id": principal.organization_id,
        }
    )
    if factory is None:
        raise HTTPException(status_code=404, detail="Factory not found.")
    return {"id": str(factory["_id"]), "name": factory["name"]}

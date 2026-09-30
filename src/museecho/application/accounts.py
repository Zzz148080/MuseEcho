from __future__ import annotations

import hashlib
import secrets
import smtplib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Protocol

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from museecho.infrastructure.db import session_scope
from museecho.infrastructure.repositories import (
    AccountTokenModel,
    AuthAttemptModel,
    UserModel,
    UserSessionModel,
)

SESSION_TTL = timedelta(days=30)
VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(hours=1)


class AccountError(Exception):
    def __init__(self, code: str, status_code: int = 400):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class Mailer(Protocol):
    def send(
        self,
        address: str,
        subject: str,
        body: str,
        *,
        template_key: str | None = None,
        template_data: dict[str, str] | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class SMTPMailer:
    host: str
    port: int
    username: str
    password: str
    sender: str

    def send(
        self,
        address: str,
        subject: str,
        body: str,
        *,
        template_key: str | None = None,
        template_data: dict[str, str] | None = None,
    ) -> None:
        del template_key, template_data
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = address
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(self.username, self.password)
            smtp.send_message(message)


@dataclass(frozen=True)
class SessionGrant:
    user_id: str
    email: str
    raw_token: str
    csrf_token: str
    expires_at: datetime


class AccountService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        mailer: Mailer | None,
        public_origin: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions = session_factory
        self._mailer = mailer
        self._origin = public_origin.rstrip("/")
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._hasher = PasswordHasher()
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(24))

    @property
    def registration_available(self) -> bool:
        return self._mailer is not None

    def register(self, email: str, password: str, ip: str) -> None:
        self._require_mailer()
        address = _email(email)
        _password(password)
        self._rate_limit("register", address, ip, 3)
        with session_scope(self._sessions) as session:
            user = session.scalar(select(UserModel).where(UserModel.email == address))
            if user is None:
                user = UserModel(
                    id=str(uuid.uuid4()),
                    email=address,
                    password_hash=self._hasher.hash(password),
                    created_at=self._clock(),
                    verified_at=None,
                    profile_enabled=True,
                )
                session.add(user)
                session.flush()
            elif user.verified_at is not None:
                return
            user_id = user.id
        self._send_token(user_id, address, "verify", VERIFY_TTL)

    def resend_verification(self, email: str, ip: str) -> None:
        self._require_mailer()
        address = _email(email)
        self._rate_limit("resend", address, ip, 3)
        with session_scope(self._sessions) as session:
            user = session.scalar(select(UserModel).where(UserModel.email == address))
            if user is None or user.verified_at is not None:
                return
            user_id = user.id
        self._send_token(user_id, address, "verify", VERIFY_TTL)

    def verify(self, raw_token: str) -> None:
        with session_scope(self._sessions) as session:
            token = self._consume_token(session, raw_token, "verify")
            user = session.get(UserModel, token.user_id)
            if user is None:
                raise AccountError("invalid_token")
            user.verified_at = self._clock()

    def login(self, email: str, password: str, ip: str) -> SessionGrant:
        address = _email(email)
        self._rate_limit("login", address, ip, 8)
        with session_scope(self._sessions) as session:
            user = session.scalar(select(UserModel).where(UserModel.email == address))
            digest = user.password_hash if user is not None else self._dummy_hash
            valid: bool
            try:
                valid = self._hasher.verify(digest, password)
            except (InvalidHashError, VerificationError, UnicodeError):
                valid = False
            if not valid or user is None or user.verified_at is None:
                raise AccountError("invalid_credentials", 401)
            raw = secrets.token_urlsafe(32)
            csrf = secrets.token_urlsafe(32)
            now = self._clock()
            expires_at = now + SESSION_TTL
            session.add(
                UserSessionModel(
                    token_hash=_digest(raw),
                    user_id=user.id,
                    csrf_hash=_digest(csrf),
                    created_at=now,
                    expires_at=expires_at,
                )
            )
            return SessionGrant(user.id, user.email, raw, csrf, expires_at)

    def current_user(self, raw_token: str | None) -> tuple[str, str] | None:
        if not raw_token or len(raw_token) > 200:
            return None
        with session_scope(self._sessions) as session:
            grant = session.get(UserSessionModel, _digest(raw_token))
            if grant is None or grant.expires_at <= self._clock():
                return None
            user = session.get(UserModel, grant.user_id)
            if user is None or user.verified_at is None:
                return None
            return user.id, user.email

    def authorize_mutation(self, raw_token: str | None, csrf: str | None) -> str | None:
        if not raw_token or not csrf or len(raw_token) > 200 or len(csrf) > 200:
            return None
        with session_scope(self._sessions) as session:
            grant = session.get(UserSessionModel, _digest(raw_token))
            if grant is None or grant.expires_at <= self._clock():
                return None
            if not secrets.compare_digest(grant.csrf_hash, _digest(csrf)):
                return None
            return grant.user_id

    def logout(self, raw_token: str) -> None:
        with session_scope(self._sessions) as session:
            session.execute(
                delete(UserSessionModel).where(UserSessionModel.token_hash == _digest(raw_token))
            )

    def request_reset(self, email: str, ip: str) -> None:
        self._require_mailer()
        address = _email(email)
        self._rate_limit("reset", address, ip, 3)
        with session_scope(self._sessions) as session:
            user = session.scalar(select(UserModel).where(UserModel.email == address))
            if user is None:
                return
            user_id = user.id
        self._send_token(user_id, address, "reset", RESET_TTL)

    def reset_password(self, raw_token: str, password: str) -> None:
        _password(password)
        with session_scope(self._sessions) as session:
            token = self._consume_token(session, raw_token, "reset")
            user = session.get(UserModel, token.user_id)
            if user is None:
                raise AccountError("invalid_token")
            user.password_hash = self._hasher.hash(password)
            # Possession of the one-time link also proves control of an unverified address.
            if user.verified_at is None:
                user.verified_at = self._clock()
            session.execute(delete(UserSessionModel).where(UserSessionModel.user_id == user.id))

    def delete_account(self, user_id: str, password: str) -> None:
        with session_scope(self._sessions) as session:
            user = session.get(UserModel, user_id)
            if user is None:
                raise AccountError("invalid_credentials", 401)
            valid: bool
            try:
                valid = self._hasher.verify(user.password_hash, password)
            except (InvalidHashError, VerificationError, UnicodeError):
                valid = False
            if not valid:
                raise AccountError("invalid_credentials", 401)
            session.delete(user)

    def cleanup_expired(self) -> None:
        now = self._clock()
        with session_scope(self._sessions) as session:
            session.execute(delete(UserSessionModel).where(UserSessionModel.expires_at <= now))
            session.execute(delete(AccountTokenModel).where(AccountTokenModel.expires_at <= now))
            session.execute(
                delete(AuthAttemptModel).where(
                    AuthAttemptModel.created_at < now - timedelta(minutes=15)
                )
            )

    def _send_token(self, user_id: str, email: str, purpose: str, ttl: timedelta) -> None:
        assert self._mailer is not None
        raw = secrets.token_urlsafe(32)
        with session_scope(self._sessions) as session:
            session.add(
                AccountTokenModel(
                    token_hash=_digest(raw),
                    user_id=user_id,
                    purpose=purpose,
                    expires_at=self._clock() + ttl,
                    used_at=None,
                )
            )
        action = "verify" if purpose == "verify" else "reset"
        subject = "MuseEcho 邮箱验证" if purpose == "verify" else "MuseEcho 重置密码"
        template_data = (
            {"verify_token": raw, "expire_hours": "24"}
            if purpose == "verify"
            else {"reset_token": raw, "expire_minutes": "60"}
        )
        try:
            self._mailer.send(
                email,
                subject,
                f"请打开以下链接完成操作：\n{self._origin}/#{action}={raw}\n",
                template_key=purpose,
                template_data=template_data,
            )
        except Exception:
            raise AccountError("email_delivery_failed", 503) from None

    def _consume_token(self, session: Session, raw: str, purpose: str) -> AccountTokenModel:
        if not raw or len(raw) > 200:
            raise AccountError("invalid_token")
        if session.bind is not None and session.bind.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            token = session.get(AccountTokenModel, _digest(raw))
        else:
            token = session.get(AccountTokenModel, _digest(raw), with_for_update=True)
        if (
            token is None
            or token.purpose != purpose
            or token.used_at is not None
            or token.expires_at <= self._clock()
        ):
            raise AccountError("invalid_token")
        token.used_at = self._clock()
        return token

    def _rate_limit(self, action: str, email: str, ip: str, maximum: int) -> None:
        now = self._clock()
        key = _digest(f"{action}:{email}:{ip}")
        ip_key = _digest(f"{action}:ip:{ip}")
        cutoff = now - timedelta(minutes=15)
        with session_scope(self._sessions) as session:
            if session.bind is not None and session.bind.dialect.name == "sqlite":
                session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            session.execute(delete(AuthAttemptModel).where(AuthAttemptModel.created_at < cutoff))
            count = session.scalar(
                select(func.count())
                .select_from(AuthAttemptModel)
                .where(AuthAttemptModel.key_hash == key, AuthAttemptModel.created_at >= cutoff)
            )
            ip_count = session.scalar(
                select(func.count())
                .select_from(AuthAttemptModel)
                .where(AuthAttemptModel.key_hash == ip_key, AuthAttemptModel.created_at >= cutoff)
            )
            if (count is not None and count >= maximum) or (
                ip_count is not None and ip_count >= 30
            ):
                raise AccountError("rate_limited", 429)
            session.add(AuthAttemptModel(id=str(uuid.uuid4()), key_hash=key, created_at=now))
            session.add(AuthAttemptModel(id=str(uuid.uuid4()), key_hash=ip_key, created_at=now))

    def _require_mailer(self) -> None:
        if self._mailer is None:
            raise AccountError("email_not_configured", 503)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _email(value: str) -> str:
    address = value.strip().lower()
    if (
        len(address) > 254
        or len(address) < 5
        or address.count("@") != 1
        or any(character.isspace() for character in address)
        or "." not in address.rsplit("@", 1)[1]
    ):
        raise AccountError("invalid_email")
    return address


def _password(value: str) -> None:
    if len(value) < 12 or len(value) > 128:
        raise AccountError("invalid_password")

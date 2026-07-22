"""Auth endpoints — verify passcode and return HMAC-signed session token.

Tokens survive server restarts — they're stateless HMAC-signed payloads,
validated against the passcode hash as signing key. No in-memory store needed.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from base64 import urlsafe_b64encode
from time import time

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

TOKEN_TTL_SECONDS = 24 * 3600  # 24 hours


class VerifyRequest(BaseModel):
    passcode: str = Field(..., min_length=1, max_length=32)


class VerifyResponse(BaseModel):
    token: str
    ok: bool = True


def _signing_key(request: Request) -> bytes:
    """Derive HMAC key from the stored bcrypt hash (stable across restarts)."""
    return request.app.state.container.config.auth_passcode_hash.encode("utf-8")


def _sign(payload: str, key: bytes) -> str:
    """HMAC-SHA256 sign a payload, return payload.signature."""
    sig = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).digest()
    return f"{payload}.{urlsafe_b64encode(sig).decode('ascii')}"


def _verify(token: str, key: bytes) -> bool:
    """Check token signature and TTL."""
    try:
        payload, sig_b64 = token.rsplit(".", 1)
        expected_sig = urlsafe_b64encode(
            hmac.new(key, payload.encode("utf-8"), hashlib.sha256).digest()
        ).decode("ascii")
        if not hmac.compare_digest(sig_b64, expected_sig):
            return False
        issued_at = int(payload.rsplit(":", 1)[-1])
        return (time() - issued_at) < TOKEN_TTL_SECONDS
    except (ValueError, IndexError):
        return False


@router.post("/api/auth/verify", response_model=VerifyResponse)
async def verify_passcode(body: VerifyRequest, request: Request) -> JSONResponse:
    config = request.app.state.container.config
    stored_hash = config.auth_passcode_hash.encode("utf-8")

    if not bcrypt.checkpw(body.passcode.encode("utf-8"), stored_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid passcode",
        )

    key = _signing_key(request)
    payload = f"{secrets.token_hex(16)}:{int(time())}"
    token = _sign(payload, key)

    _logger.info("Auth token generated")
    return JSONResponse(content={"token": token, "ok": True})


@router.post("/api/auth/logout")
async def logout() -> JSONResponse:
    return JSONResponse(content={"ok": True})


@router.get("/api/auth/validate")
async def validate(authorization: str = Header(default="Bearer "), *, request: Request) -> JSONResponse:
    key = _signing_key(request)
    token = authorization.removeprefix("Bearer ").strip()
    if token and _verify(token, key):
        return JSONResponse(content={"ok": True})
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


def require_auth(authorization: str = Header(default="Bearer "), *, request: Request) -> None:
    """FastAPI dependency — validates the Bearer token via HMAC signature."""
    key = _signing_key(request)
    token = authorization.removeprefix("Bearer ").strip()
    if not token or not _verify(token, key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

"""Auth endpoints — verify passcode and return session token."""

from __future__ import annotations

import logging

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

# In-memory token store: token → True
# Resets on server restart; sessions last for the server lifetime
_tokens: set[str] = set()


class VerifyRequest(BaseModel):
    passcode: str = Field(..., min_length=1, max_length=32)


class VerifyResponse(BaseModel):
    token: str
    ok: bool = True


@router.post("/api/auth/verify", response_model=VerifyResponse)
async def verify_passcode(body: VerifyRequest, request: Request) -> JSONResponse:
    config = request.app.state.container.config
    stored_hash = config.auth_passcode_hash.encode("utf-8")

    if not bcrypt.checkpw(body.passcode.encode("utf-8"), stored_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid passcode",
        )

    # Generate a simple session token
    import secrets
    token = secrets.token_hex(32)
    _tokens.add(token)

    _logger.info("Auth token generated — active sessions: %d", len(_tokens))
    return JSONResponse(content={"token": token, "ok": True})


@router.post("/api/auth/logout")
async def logout(authorization: str = Header(default="")) -> JSONResponse:
    token = authorization.removeprefix("Bearer ").strip()
    _tokens.discard(token)
    _logger.info("Token revoked — active sessions: %d", len(_tokens))
    return JSONResponse(content={"ok": True})


def require_auth(authorization: str = Header(default="Bearer ")) -> None:
    """FastAPI dependency — validates the Bearer token from Authorization header."""
    token = authorization.removeprefix("Bearer ").strip()
    if not token or token not in _tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

"""
auth.py — Clerk JWT verification for all /api routes.

Every /api/* request must carry `Authorization: Bearer <Clerk session JWT>`.
Tokens are verified against Clerk's JWKS (RS256): signature, expiry, issuer.

Config (env):
  CLERK_ISSUER   Your Clerk Frontend API URL, e.g.
                 https://your-app-name.clerk.accounts.dev
                 (Clerk dashboard → Configure → API keys → Frontend API URL)

If CLERK_ISSUER is not set, verification is DISABLED — every request is let
through and a CRITICAL warning is logged at startup. That mode exists for
local development only; never deploy without it.
"""

import os
import time
import logging
from typing import Optional

import requests
from jose import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

CLERK_ISSUER = os.environ.get("CLERK_ISSUER", "").rstrip("/")

_JWKS_TTL_SECONDS = 3600
_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}


def auth_enabled() -> bool:
    return bool(CLERK_ISSUER)


def _get_jwks(force: bool = False) -> Optional[dict]:
    """Fetch (and cache for 1h) Clerk's JSON Web Key Set."""
    now = time.time()
    if (
        not force
        and _jwks_cache["keys"]
        and (now - _jwks_cache["fetched_at"]) < _JWKS_TTL_SECONDS
    ):
        return _jwks_cache["keys"]
    try:
        resp = requests.get(f"{CLERK_ISSUER}/.well-known/jwks.json", timeout=10)
        resp.raise_for_status()
        _jwks_cache["keys"] = resp.json()
        _jwks_cache["fetched_at"] = now
        return _jwks_cache["keys"]
    except Exception as e:
        logger.error(f"Failed to fetch Clerk JWKS: {e}")
        # Fall back to a stale cache rather than locking everyone out
        return _jwks_cache["keys"]


def verify_clerk_token(token: str) -> dict:
    """
    Verify a Clerk session JWT. Returns the claims dict.
    Raises ValueError on any verification failure.
    """
    jwks = _get_jwks()
    if not jwks:
        raise ValueError("Clerk JWKS unavailable")

    try:
        header = jwt.get_unverified_header(token)
    except Exception:
        raise ValueError("Malformed token")

    kid = header.get("kid")
    key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if key is None:
        # Key rotation — refresh JWKS once before giving up
        jwks = _get_jwks(force=True) or {}
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if key is None:
        raise ValueError("Unknown signing key")

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=CLERK_ISSUER,
            # Clerk session tokens carry no `aud` claim by default
            options={"verify_aud": False},
        )
    except Exception as e:
        raise ValueError(str(e))

    return claims


# Paths under /api that skip auth (none today; /health and /docs are outside /api)
_PUBLIC_API_PATHS: set[str] = set()


class ClerkAuthMiddleware(BaseHTTPMiddleware):
    """
    Rejects unauthenticated /api requests with 401.

    - Skips CORS preflight (OPTIONS) — the browser sends those without headers.
    - Skips everything outside /api (/health, /docs, /openapi.json).
    - On success, verified claims are exposed as `request.state.clerk`.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if (
            not auth_enabled()
            or request.method == "OPTIONS"
            or not path.startswith("/api")
            or path in _PUBLIC_API_PATHS
        ):
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return JSONResponse(
                {"detail": "Not authenticated — missing bearer token."},
                status_code=401,
            )

        token = auth_header.split(" ", 1)[1].strip()
        try:
            claims = verify_clerk_token(token)
        except ValueError as e:
            logger.warning(f"Rejected token for {path}: {e}")
            return JSONResponse(
                {"detail": f"Not authenticated — {e}"},
                status_code=401,
            )

        request.state.clerk = claims
        return await call_next(request)

from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError
from pydantic import BaseModel

from app.core.config import settings

security = HTTPBearer(auto_error=False)


class AuthenticatedUser(BaseModel):
    id: str
    email: Optional[str] = None
    is_anonymous: bool = False
    role: str = "authenticated"


_jwks_client: Optional[PyJWKClient] = None


def get_jwks_client() -> PyJWKClient:
    """Retrieve singleton PyJWKClient instance for Supabase JWKS."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(
            settings.supabase_jwks_url,
            cache_jwk_set=True,
            cache_keys=True,
            lifespan=300,
        )
    return _jwks_client


def set_jwks_client(client: Optional[PyJWKClient]) -> None:
    """Setter for PyJWKClient, primarily for testing and dependency injection."""
    global _jwks_client
    _jwks_client = client


def decode_token(token: str, jwks_client: Optional[PyJWKClient] = None) -> dict:
    """Decode and validate a Supabase ES256 JWT using project JWKS."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    kid = header.get("kid")
    if not kid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token header: missing kid",
            headers={"WWW-Authenticate": "Bearer"},
        )

    alg = header.get("alg")
    if alg != "ES256":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token algorithm: expected ES256, got {alg}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    client = jwks_client or get_jwks_client()
    try:
        signing_key = client.get_signing_key(kid)
    except PyJWKClientError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or unknown token signing key: {kid}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not retrieve signing key from JWKS",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    try:
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
            issuer=settings.supabase_issuer,
            options={
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": True,
                "verify_sub": True,
            },
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidAudienceError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token audience",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidIssuerError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> AuthenticatedUser:
    """Validate Bearer token and return AuthenticatedUser."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload: missing sub",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Determine anonymous status from Supabase standard claims
    is_anon = bool(payload.get("is_anonymous", False))
    app_metadata = payload.get("app_metadata", {})
    if app_metadata.get("provider") == "anonymous":
        is_anon = True

    return AuthenticatedUser(
        id=user_id,
        email=payload.get("email"),
        is_anonymous=is_anon,
        role=payload.get("role", "authenticated"),
    )

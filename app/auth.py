"""
Authentication: bcrypt password verification, JWT issuance, and token revocation.

Credential setup

Passwords will never be stored in source. For each researcher, they will have to generate a hash:

    python -c "from passlib.context import CryptContext; \
               print(CryptContext(['bcrypt']).hash('yourpassword'))"

Then add it to their .env:

    RESEARCHER_A_HASH=$2b$12$...

Any env var ending in _HASH whose value starts with $2 (bcrypt prefix) is going to automatically picked up at startup as a valid user.

Token revocation Logic

Revoked JTI (JWT ID) values are all held in a Redis set with TTL equal to the
remaining token lifetime, so the set stays bounded. Revoke a token by
calling POST /auth/revoke with a valid Bearer token, the token is added to
the blocklist and is rejected on all subsequent requests.
"""

import os
import uuid
import logging
from datetime import datetime, timedelta, timezone

import jwt
import redis as redis_lib
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext

load_dotenv()
logger = logging.getLogger(__name__)

SECRET_KEY = os.environ["JWT_SECRET"]
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", 8))
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_USERS: dict[str, str] = {}


def _load_users() -> None:
    """Populate the in-process user table from env vars at startup."""
    for key, value in os.environ.items():
        if key.endswith("_HASH") and value.startswith("$2"):
            username = key[: -len("_HASH")].lower()
            _USERS[username] = value
    logger.info("Loaded %d user(s) from environment.", len(_USERS))


def _verify_user(username: str, password: str) -> bool:
    hashed = _USERS.get(username)
    if not hashed:
        pwd_context.dummy_verify()
        return False
    return pwd_context.verify(password, hashed)


def _redis_client() -> redis_lib.Redis:
    return redis_lib.from_url(REDIS_URL, decode_responses=True)


def _blocklist_key(jti: str) -> str:
    return f"revoked_jti:{jti}"


def _is_revoked(jti: str) -> bool:
    try:
        client = _redis_client()
        return client.exists(_blocklist_key(jti)) == 1
    except redis_lib.RedisError as exc:
        logger.error("Redis blocklist check failed: %s", exc)
        return False


def revoke_token(jti: str, expires_at: datetime) -> None:
    """Add a JTI to the blocklist with a TTL matching its remaining lifetime."""
    remaining = int((expires_at - datetime.now(timezone.utc)).total_seconds())
    if remaining <= 0:
        return  
    try:
        client = _redis_client()
        client.setex(_blocklist_key(jti), remaining, "1")
    except redis_lib.RedisError as exc:
        logger.error("Failed to revoke token %s: %s", jti, exc)
        raise HTTPException(status_code=503, detail="Could not revoke token. Try again.")

def create_access_token(sub: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=EXPIRE_HOURS)
    payload = {
        "sub": sub,
        "exp": expires_at,
        "jti": str(uuid.uuid4()),  # This is the Unique ID which will be required for revocation.
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> dict:
    """Decode and validate a JWT, raising HTTPException on any failure."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired — please log in again.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        )

def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    payload = _decode_token(token)

    researcher_id: str | None = payload.get("sub")
    jti: str | None = payload.get("jti")

    if not researcher_id:
        raise HTTPException(status_code=401, detail="Invalid token payload.")

    if jti and _is_revoked(jti):
        raise HTTPException(status_code=401, detail="Token has been revoked.")

    return researcher_id


def get_current_user_payload(token: str = Depends(oauth2_scheme)) -> dict:
    """Like get_current_user but returns the full decoded payload (needed for revocation)."""
    return _decode_token(token)


def login(form: OAuth2PasswordRequestForm = Depends()):
    if not _verify_user(form.username, form.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {
        "access_token": create_access_token(sub=form.username),
        "token_type": "bearer",
    }


def logout(payload: dict = Depends(get_current_user_payload)) -> dict:
    """Revoke the current token so it cannot be reused before expiry."""
    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti and exp:
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        revoke_token(jti, expires_at)
    return {"message": "Token revoked successfully."}

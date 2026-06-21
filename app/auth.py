import os
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.environ["JWT_SECRET"]
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", 8))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Users are stored as bcrypt hashes — never plaintext.
# Generate a hash: python -c "from passlib.context import CryptContext; print(CryptContext(['bcrypt']).hash('yourpassword'))"
# Then set RESEARCHER_A_HASH in your .env
_USERS: dict[str, str] = {}


def _load_users() -> None:
    """Populate the in-process user table from environment variables at startup."""
    for key, value in os.environ.items():
        if key.endswith("_HASH") and value.startswith("$2"):
            username = key[: -len("_HASH")].lower()
            _USERS[username] = value


def _verify_user(username: str, password: str) -> bool:
    hashed = _USERS.get(username)
    if not hashed:
        return False
    return pwd_context.verify(password, hashed)


def create_access_token(sub: str) -> str:
    payload = {
        "sub": sub,
        "exp": datetime.now(timezone.utc) + timedelta(hours=EXPIRE_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme)) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        researcher_id: str = payload.get("sub")
        if not researcher_id:
            raise HTTPException(status_code=401, detail="Invalid token payload.")
        return researcher_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired — please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")


def login(form: OAuth2PasswordRequestForm = Depends()):
    if not _verify_user(form.username, form.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"access_token": create_access_token(sub=form.username), "token_type": "bearer"}

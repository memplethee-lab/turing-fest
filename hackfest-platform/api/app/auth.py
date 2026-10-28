import os
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGO = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)

def create_team_token(team_id: str, event_id: str) -> str:
    payload = {
        "team_id": team_id,
        "event_id": event_id,
        "role": "team",
        "exp": datetime.now(timezone.utc) + timedelta(hours=18),  # comfortably covers a 1-day event
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

async def get_current_team(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token")
    if payload.get("role") != "team":
        # An admin token should never be usable as a team token, or vice
        # versa — the "role" claim keeps the two scopes from bleeding into
        # each other even though they share a JWT secret and verification path.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not a team token")
    return payload  # {"team_id": ..., "event_id": ..., "role": "team"}


def create_admin_token() -> str:
    payload = {
        "role": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(hours=18),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


async def get_current_admin(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token")
    if payload.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin access required")
    return payload

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
    if payload.get("role") not in ("team", "user"):
        # An admin token should never be usable as a team token, or vice
        # versa — the "role" claim keeps the two scopes from bleeding into
        # each other even though they share a JWT secret and verification path.
        # Per-user tokens carry the same team_id/event_id claims, so anything
        # a team can do (submit, poll results), a logged-in member can too —
        # rate limits stay per-team either way.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not a team or user token")
    return payload  # {"team_id": ..., "event_id": ..., "role": "team"|"user"}


def create_admin_token(username: str = "admin") -> str:
    payload = {
        "sub": username,
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
    return payload  # {"sub": admin username, "role": "admin"}


def create_user_token(user_id: str, team_id: str, event_id: str, username: str) -> str:
    payload = {
        "sub": username,
        "user_id": user_id,
        "team_id": team_id,
        "event_id": event_id,
        "role": "user",
        "exp": datetime.now(timezone.utc) + timedelta(hours=18),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    """For endpoints that need the individual behind the team (e.g. /users/me),
    unlike get_current_team which accepts team-shared and user tokens alike."""
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token")
    if payload.get("role") != "user":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not a user token")
    return payload

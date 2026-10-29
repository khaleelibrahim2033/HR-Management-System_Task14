from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from .config import settings
from .models import User


password_hash = PasswordHash.recommended()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_access_token(user: User) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_access_token_minutes)
    return jwt.encode({"sub": str(user.id), "role": user.role.value, "exp": expires}, settings.jwt_secret_key, algorithm=ALGORITHM)

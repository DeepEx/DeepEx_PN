import os
from passlib.context import CryptContext
from fastapi import Request, HTTPException, Depends
from sqlalchemy.orm import Session
from db import get_db
from models import User

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


SESSION_KEY = "deepex_user"

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)

def get_current_user(request: Request) -> str:
    u = request.session.get(SESSION_KEY)
    if not u:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return u

def require_user(request: Request) -> str:
    return get_current_user(request)

def ensure_admin_user(db: Session):
    username = os.environ["ADMIN_USERNAME"]
    password = os.environ["ADMIN_PASSWORD"]
    if not db.query(User).filter(User.username == username).first():
        db.add(User(username=username, password_hash=hash_password(password)))
        db.commit()

def get_user(request: Request) -> str | None:
    return request.session.get(SESSION_KEY)

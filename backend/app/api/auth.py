from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import auth_rate_limit, get_current_user
from app.core.security import create_token, hash_password, verify_password
from app.memory.vectors import ALL, vectors
from app.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "onboarded": u.onboarded,
            "created_at": u.created_at.isoformat() if u.created_at else None}


@router.post("/register", dependencies=[Depends(auth_rate_limit)])
async def register(body: RegisterIn, db: AsyncSession = Depends(get_db)):
    count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    if not settings.ALLOW_REGISTRATION and count > 0:
        raise HTTPException(403, "Registration is closed on this JARVIS instance.")
    email = body.email.lower()
    if (await db.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise HTTPException(409, "An account with this email already exists.")
    u = User(email=email, password_hash=hash_password(body.password), name=body.name.strip())
    db.add(u)
    await db.commit()
    return {"token": create_token(u.id), "user": user_out(u)}


@router.post("/login", dependencies=[Depends(auth_rate_limit)])
async def login(body: LoginIn, db: AsyncSession = Depends(get_db)):
    u = (await db.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Wrong email or password.")
    return {"token": create_token(u.id), "user": user_out(u)}


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return user_out(user)


class ProfileIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)


@router.patch("/me")
async def update_me(body: ProfileIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.name is not None:
        user.name = body.name.strip()
    await db.commit()
    return user_out(user)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/password", dependencies=[Depends(auth_rate_limit)])
async def change_password(body: PasswordIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is wrong.")
    user.password_hash = hash_password(body.new_password)
    await db.commit()
    return {"ok": True}


class DeleteIn(BaseModel):
    password: str


@router.post("/delete-account", dependencies=[Depends(auth_rate_limit)])
async def delete_account(body: DeleteIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Irreversible: deletes the user and ALL their data (DB rows cascade, vectors removed)."""
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(400, "Password is wrong.")
    for c in ALL:
        await vectors.delete_where(c, user.id)
    await db.delete(user)
    await db.commit()
    return {"deleted": True}

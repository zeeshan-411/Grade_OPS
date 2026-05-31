from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.models.user import Role


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: Role = Role.TA


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.v1.deps import get_current_user, require_role
from app.models.user import Role, User
from app.schemas.user import UserOut

router = APIRouter(tags=["users"])


@router.get("/users/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user


@router.get("/instructor/ping")
async def instructor_ping(
    user: Annotated[User, Depends(require_role(Role.INSTRUCTOR))],
) -> dict[str, str]:
    return {"ok": "instructor", "email": user.email}


@router.get("/ta/ping")
async def ta_ping(
    user: Annotated[User, Depends(require_role(Role.TA))],
) -> dict[str, str]:
    return {"ok": "ta", "email": user.email}

"""Seed a default instructor + TA for local development.

Usage (from inside the backend container):
    python -m scripts.seed
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import Role, User

SEED_USERS = [
    ("instructor@gradeops.dev", "instructor123", Role.INSTRUCTOR),
    ("ta@gradeops.dev", "ta12345678", Role.TA),
]


async def seed() -> None:
    async with SessionLocal() as db:
        for email, password, role in SEED_USERS:
            existing = await db.execute(select(User).where(User.email == email))
            if existing.scalar_one_or_none() is not None:
                print(f"skip (exists): {email}")
                continue
            db.add(
                User(
                    email=email,
                    hashed_password=hash_password(password),
                    role=role,
                )
            )
            print(f"created: {email} ({role.value})  password={password}")
        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed())

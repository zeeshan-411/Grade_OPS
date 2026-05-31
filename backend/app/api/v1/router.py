from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import auth, exams, reviews, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(exams.router)
api_router.include_router(reviews.router)

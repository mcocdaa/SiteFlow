from fastapi import APIRouter

from app import admin, views

router = APIRouter()
router.include_router(views.router)
router.include_router(admin.router)

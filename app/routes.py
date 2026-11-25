from fastapi import APIRouter

from app import admin, views
from app.extensions import mascot_chat
from app.plugins.bottle import api as bottle_api

router = APIRouter()
router.include_router(views.router)
router.include_router(admin.router)
router.include_router(mascot_chat.router)
router.include_router(bottle_api.router)

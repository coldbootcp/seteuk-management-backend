from fastapi import APIRouter

from app.api.v1.attachments import router as attachments_router
from app.api.v1.auth import router as auth_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.diagnosis import router as diagnosis_router
from app.api.v1.plans import router as plans_router
from app.api.v1.profile import router as profile_router
from app.api.v1.recommendations import router as recommendations_router
from app.api.v1.records import record_routers
from app.api.v1.roadmaps import router as roadmaps_router
from app.api.v1.seteuk import router as seteuk_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(seteuk_router)
api_router.include_router(profile_router)
api_router.include_router(diagnosis_router)
for record_router in record_routers:
    api_router.include_router(record_router)
api_router.include_router(attachments_router)
api_router.include_router(plans_router)
api_router.include_router(roadmaps_router)
api_router.include_router(recommendations_router)
api_router.include_router(conversations_router)

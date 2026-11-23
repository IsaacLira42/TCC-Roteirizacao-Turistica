from fastapi import APIRouter
from app.api.v1.endpoints.health import router as health_router
from app.modules.activities.endpoints import router as activities_router
from app.modules.recommendations.endpoints import router as recommendations_router

router = APIRouter()
router.include_router(health_router)
router.include_router(activities_router)
router.include_router(recommendations_router)
from typing import List, Optional
from fastapi import APIRouter, Depends, Query

from app.core.database import SessionLocal
from app.modules.activities.models import Activity
from app.modules.activities.schemas import ActivityCreate, ActivityRead, ActivityUpdate
from app.modules.activities.service import ActivityService, get_session

router = APIRouter(prefix="/activities", tags=["activities"])


def get_activity_service(session=Depends(get_session)):
    return ActivityService(session=session)


@router.get("", response_model=List[ActivityRead])
def list_activities(
    service: ActivityService = Depends(get_activity_service),
    skip: int = Query(0, ge=0, description="Número de registros para pular"),
    limit: int = Query(100, ge=1, le=500, description="Máximo de registros por página"),
    name: Optional[str] = Query(None, description="Filtrar por nome (busca parcial)"),
    category: Optional[str] = Query(
        None, description="Filtrar por categoria (busca parcial)"
    ),
):
    activities = service.list_activities(skip=skip, limit=limit, name=name, category=category)
    return activities


@router.get("/{activity_id}", response_model=ActivityRead)
def get_activity(
    activity_id: str,
    service: ActivityService = Depends(get_activity_service),
):
    return service.get_activity(activity_id=activity_id)


@router.post("", response_model=ActivityRead, status_code=201)
def create_activity(
    activity_in: ActivityCreate,
    service: ActivityService = Depends(get_activity_service),
):
    # Convert Pydantic model to dict for repository
    activity_dict = activity_in.model_dump(exclude_unset=True)
    return service.create_activity(activity_data=activity_dict)


@router.put("/{activity_id}", response_model=ActivityRead)
def update_activity(
    activity_id: str,
    activity_in: ActivityUpdate,
    service: ActivityService = Depends(get_activity_service),
):
    # Convert Pydantic model to dict, excluding None values
    activity_dict = activity_in.model_dump(exclude_unset=True)
    return service.update_activity(activity_id=activity_id, activity_data=activity_dict)


@router.delete("/{activity_id}", status_code=204)
def delete_activity(
    activity_id: str,
    service: ActivityService = Depends(get_activity_service),
):
    service.delete_activity(activity_id=activity_id)
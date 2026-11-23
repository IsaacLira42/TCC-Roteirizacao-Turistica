from typing import List, Optional

from fastapi import HTTPException, status

from app.core.database import SessionLocal
from app.modules.activities.models import Activity
from app.modules.activities.repository import ActivityRepository


def get_session():
    return SessionLocal()


class ActivityService:
    def __init__(self, session=None):
        self._session = session or get_session()
        self._repo = ActivityRepository(self._session)

    @property
    def repo(self) -> ActivityRepository:
        return self._repo

    def list_activities(
        self,
        skip: int = 0,
        limit: int = 100,
        name: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Activity]:
        queryset = self.repo.list_all(skip=skip, limit=limit)
        if name:
            queryset = self.repo.search_by_name(name_query=name, skip=skip, limit=limit)
        if category:
            queryset = self.repo.search_by_category(category=category, skip=skip, limit=limit)
        return queryset

    def count_activities(self) -> int:
        return self.repo.count_total()

    def get_activity(self, activity_id: str) -> Activity:
        activity = self.repo.get_by_id(activity_id=activity_id)
        if activity is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Activity with id={activity_id} not found",
            )
        return activity

    def create_activity(self, activity_data: dict) -> Activity:
        # Validate duration range
        min_dur = activity_data.get("duration_estimated_min", 1)
        max_dur = activity_data.get("duration_estimated_max", 1)
        if min_dur > max_dur:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="duration_estimated_min must be <= duration_estimated_max",
            )
        return self.repo.create(activity_data=activity_data)

    def update_activity(self, activity_id: str, activity_data: dict) -> Activity:
        activity = self.repo.get_by_id(activity_id=activity_id)
        if activity is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Activity with id={activity_id} not found",
            )
        # Validate duration range if being updated
        if "duration_estimated_min" in activity_data or "duration_estimated_max" in activity_data:
            min_dur = activity_data.get(
                "duration_estimated_min", activity.duration_estimated_min
            )
            max_dur = activity_data.get(
                "duration_estimated_max", activity.duration_estimated_max
            )
            if min_dur > max_dur:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="duration_estimated_min must be <= duration_estimated_max",
                )
        return self.repo.update(activity_id=activity_id, activity_data=activity_data)

    def delete_activity(self, activity_id: str) -> bool:
        return self.repo.delete(activity_id=activity_id)
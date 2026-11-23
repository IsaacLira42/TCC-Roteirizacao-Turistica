import json

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.core.database import Base
from app.modules.activities.models import Activity


def _serialize_categories(data: dict) -> dict:
    """Converte `categories` (list) para JSON string antes de persistir.

    O modelo usa Column(String) (VARCHAR). O schema Pydantic devolve list[str]
    na leitura. Na escrita, precisamos serializar de volta para string.

    Se `categories` vier como list (inclusive []), vira JSON string.
    Se vier como string (já serializado), mantém.
    Se vier como None (não enviado), mantém None.
    """
    data = dict(data)
    cats = data.get("categories")
    if isinstance(cats, list):
        data["categories"] = json.dumps(cats)
    return data


class ActivityRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_all(self, skip: int = 0, limit: int = 100):
        stmt = select(Activity).order_by(Activity.id).offset(skip).limit(limit)
        result = self.db.execute(stmt)
        return result.scalars().all()

    def count_total(self) -> int:
        stmt = select(func.count(Activity.id))
        result = self.db.execute(stmt)
        return result.scalar_one()

    def get_by_id(self, activity_id: str) -> Activity | None:
        return self.db.get(Activity, activity_id)

    def create(self, activity_data: dict) -> Activity:
        # Serializa categories (list → string)
        activity_data = _serialize_categories(activity_data)

        # Garante id
        if "id" not in activity_data or activity_data["id"] is None:
            activity_data["id"] = f"atividade_{self.count_total() + 1:04d}"

        db_activity = Activity(**activity_data)
        self.db.add(db_activity)
        self.db.commit()
        self.db.refresh(db_activity)
        return db_activity

    def update(self, activity_id: str, activity_data: dict) -> Activity | None:
        db_activity = self.db.get(Activity, activity_id)
        if db_activity is None:
            return None

        # Serializa categories (list → string), inclusive [] → "[]"
        activity_data = _serialize_categories(activity_data)

        for key, value in activity_data.items():
            setattr(db_activity, key, value)

        self.db.commit()
        self.db.refresh(db_activity)
        return db_activity

    def delete(self, activity_id: str) -> bool:
        db_activity = self.db.get(Activity, activity_id)
        if db_activity is None:
            return False
        self.db.delete(db_activity)
        self.db.commit()
        return True

    def search_by_name(self, name_query: str, skip: int = 0, limit: int = 100):
        stmt = (
            select(Activity)
            .filter(Activity.name.ilike(f"%{name_query}%"))
            .offset(skip)
            .limit(limit)
        )
        result = self.db.execute(stmt)
        return result.scalars().all()

    def search_by_category(self, category: str, skip: int = 0, limit: int = 100):
        stmt = (
            select(Activity)
            .filter(Activity.categories.ilike(f"%{category}%"))
            .offset(skip)
            .limit(limit)
        )
        result = self.db.execute(stmt)
        return result.scalars().all()
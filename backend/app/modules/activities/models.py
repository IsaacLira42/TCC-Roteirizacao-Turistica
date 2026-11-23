from sqlalchemy import Column, Integer, String, Float, CheckConstraint
from sqlalchemy.sql.sqltypes import SmallInteger

from app.core.database import Base


class Activity(Base):
    __tablename__ = "activities"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    city = Column(String, nullable=True)
    origin_block = Column(String, nullable=True)
    categories = Column(String, nullable=True)  # stored as JSON string
    duration_estimated_min = Column(Integer, nullable=False)
    duration_estimated_max = Column(Integer, nullable=False)
    source_duration = Column(String, nullable=True)
    observation_annotation = Column(String, nullable=True)

    __table_args__ = (
        CheckConstraint("lat >= -90 AND lat <= 90", name="chk_lat_range"),
        CheckConstraint("lon >= -180 AND lon <= 180", name="chk_lon_range"),
        CheckConstraint(
            "duration_estimated_min > 0", name="chk_duration_min_positive"
        ),
        CheckConstraint(
            "duration_estimated_min <= duration_estimated_max",
            name="chk_duration_min_lte_max",
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "lat": self.lat,
            "lon": self.lon,
            "city": self.city,
            "origin_block": self.origin_block,
            "categories": self.categories,
            "duration_estimated_min": self.duration_estimated_min,
            "duration_estimated_max": self.duration_estimated_max,
            "source_duration": self.source_duration,
            "observation_annotation": self.observation_annotation,
        }
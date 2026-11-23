from typing import List, Optional
from pydantic import BaseModel, Field, validator


class ActivityCreate(BaseModel):
    name: str = Field(..., description="Nome da atividade turística")
    type: str = Field(..., description="Tipo OpenStreetMap (ex: tourism=museum)")
    lat: float = Field(..., description="Latitude decimal")
    lon: float = Field(..., description="Longitude decimal")
    city: Optional[str] = Field(None, description="Município")
    origin_block: Optional[str] = Field(
        None, description="Bloco de origem da coleta (alimentacao, lazer, etc)"
    )
    categories: Optional[List[str]] = Field(
        None, description="Categorias turísticas atribuídas"
    )
    duration_estimated_min: int = Field(
        ..., ge=1, description="Duração mínima estimada em minutos"
    )
    duration_estimated_max: int = Field(
        ..., ge=1, description="Duração máxima estimada em minutos"
    )
    source_duration: Optional[str] = Field(
        None, description="Origem da estimativa de duração"
    )
    observation_annotation: Optional[str] = Field(
        None, description="Observação ou anotação de revisão"
    )

    @validator("categories", pre=True, always=True)
    def ensure_categories_list(cls, v):
        if isinstance(v, str):
            # Try to parse as JSON list
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return [c.strip() for c in v.split(",")]
        return v if v else []

    model_config = {"from_attributes": True}


class ActivityRead(BaseModel):
    id: str
    name: str
    type: str
    lat: float
    lon: float
    city: Optional[str] = None
    origin_block: Optional[str] = None
    categories: Optional[List[str]] = None
    duration_estimated_min: int
    duration_estimated_max: int
    source_duration: Optional[str] = None
    observation_annotation: Optional[str] = None

    @validator("categories", pre=True)
    def parse_categories_from_string(cls, v):
        """Converte string do banco para lista quando lendo via from_attributes."""
        if isinstance(v, str):
            import json
            # Try JSON first
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
            # Try comma-separated
            return [c.strip() for c in v.split(",") if c.strip()]
        return v


class ActivityUpdate(BaseModel):
    name: Optional[str] = Field(None, description="Nome da atividade")
    type: Optional[str] = Field(None, description="Tipo OpenStreetMap")
    lat: Optional[float] = Field(None, description="Latitude decimal")
    lon: Optional[float] = Field(None, description="Longitude decimal")
    city: Optional[str] = Field(None, description="Município")
    origin_block: Optional[str] = Field(
        None, description="Bloco de origem da coleta"
    )
    categories: Optional[List[str]] = Field(
        None, description="Categorias turísticas"
    )
    duration_estimated_min: Optional[int] = Field(
        None, ge=1, description="Duração mínima estimada"
    )
    duration_estimated_max: Optional[int] = Field(
        None, ge=1, description="Duração máxima estimada"
    )
    source_duration: Optional[str] = Field(
        None, description="Origem da estimativa de duração"
    )
    observation_annotation: Optional[str] = Field(
        None, description="Observação ou anotação de revisão"
    )

    # Validador que garante que, se categories vier como string, vira lista
    @validator("categories", pre=True, always=True)
    def ensure_categories_list(cls, v):
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                # Se for string sem JSON, trata como lista separada por vírgula
                if v.strip():
                    return [c.strip() for c in v.split(",")]
                return []
        return v if v is not None else None

    model_config = {"from_attributes": True}
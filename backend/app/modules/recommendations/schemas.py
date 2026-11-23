from typing import List, Literal, Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field, validator, root_validator

from app.modules.preferences.schemas import CategoryWeights


# ---- Esquema auxiliar para ponto de referência ----
class LatLon(BaseModel):
    """Ponto geográfico com lat e lon."""

    lat: float = Field(..., description="Latitude decimal")
    lon: float = Field(..., description="Longitude decimal")

    model_config = {"extra": "forbid", "strict": True}


# ---- ENTRADA ----

class RecommendationInput(BaseModel):
    """Payload de entrada POST /api/v1/recommendations."""

    category_weights: CategoryWeights = Field(
        ..., description="Pesos das sete categorias experimentais"
    )
    seed: Optional[int] = Field(
        None,
        description=(
            "Semente para baseline_random; para personalized com tie_break="
            "'random', semente do embaralhamento de desempate"
        ),
    )
    tie_break: Literal["id", "random"] = Field(
        "id",
        description=(
            "Desempate entre atividades de mesmo escore na estratégia "
            "personalizada: 'id' (determinístico, padrão) ou 'random' "
            "(exige seed)"
        ),
    )
    trip_days: int = Field(
        ..., ge=2, le=7,
        description="Quantidade de dias da viagem (2, 4 ou 7)"
    )
    daily_limit_min: int = Field(
        ..., ge=240, le=360,
        description="Limite diário em minutos (240 para 2 dias, 360 para 4 ou 7 dias)"
    )
    reference_point: LatLon = Field(
        ..., description="Coordenadas (lat, lon) do ponto de referência do cenário"
    )

    @validator("trip_days")
    def validar_trip_days(cls, v):
        if v not in (2, 4, 7):
            raise ValueError("trip_days must be 2, 4, or 7")
        return v

    @validator("reference_point")
    def validar_reference_point(cls, v):
        # Aceita objeto com lat e lon (ex: {"lat": -23.55, "lon": -46.63})
        if not hasattr(v, "lat") or not hasattr(v, "lon"):
            raise ValueError("reference_point must have 'lat' and 'lon' attributes")
        lat, lon = v.lat, v.lon
        if not (-90 <= lat <= 90):
            raise ValueError("latitude must be between -90 and 90")
        if not (-180 <= lon <= 180):
            raise ValueError("longitude must be between -180 and 180")
        return v

    model_config = {"extra": "forbid", "strict": True}


# ---- SAÍDA ----

class DayResult(BaseModel):
    """Um dia do roteiro, com seu número e atividades inseridas."""
    day: int = Field(..., description="Número do dia (1 a trip_days)")
    activities: List[str] = Field(
        ..., description="IDs das atividades inseridas nesse dia"
    )


class ItineraryResult(BaseModel):
    """Estrutura do roteiro gerado."""
    days: List[DayResult] = Field(
        ..., description="Lista de dias com atividades inseridas"
    )


class MetricsResult(BaseModel):
    """Métricas de compatibilidade e cobertura."""
    compatibility_media: Optional[float] = Field(
        None, description="Média de compatibilidade (null em baseline ou roteiro vazio)"
    )
    cobertura_interesses: Optional[float] = Field(
        None, description="Proporção de categorias ativas representadas (null em baseline)"
    )


class DayMetricsResult(BaseModel):
    """Métricas secundárias de um dia do roteiro final."""
    day: int = Field(..., description="Número do dia (1 a trip_days)")
    distance_m: float = Field(
        ..., description="Soma das pernas usadas no dia, incluindo referência → primeira atividade"
    )
    travel_minutes: float = Field(..., description="Soma das durações das pernas usadas no dia")
    visit_minutes: float = Field(
        ..., description="Soma das durações das visitas (média entre mínimo e máximo)"
    )
    total_minutes: float = Field(..., description="travel_minutes + visit_minutes")
    occupancy: Optional[float] = Field(
        None,
        description="total_minutes / daily_limit_min; nulo em dia sem atividades (não ativo)",
    )
    limit_violations: int = Field(
        0, description="1 quando o dia final excede o limite diário; 0 caso contrário"
    )

    model_config = {"extra": "forbid"}


class ItineraryMetricsResult(BaseModel):
    """Métricas secundárias do roteiro final efetivamente selecionado."""
    total_distance_m: float = Field(0.0, description="Soma de distance_m dos dias")
    total_travel_minutes: float = Field(0.0, description="Soma de travel_minutes dos dias")
    total_visit_minutes: float = Field(0.0, description="Soma de visit_minutes dos dias")
    total_occupied_minutes: float = Field(0.0, description="Soma de total_minutes dos dias")
    total_violations: int = Field(0, description="Soma de limit_violations dos dias")
    days: List[DayMetricsResult] = Field(
        default_factory=list, description="Métricas por dia, na ordem dos dias do roteiro"
    )

    model_config = {"extra": "forbid"}


class ExcludedActivity(BaseModel):
    """Atividade elegível que não foi inserida no roteiro."""
    activity_id: str = Field(..., description="ID da atividade")
    motive_code: str = Field(
        ..., description="Código estável do motivo (invalid_duration, no_viable_route, daily_limit_exceeded)"
    )


class IneligibleActivity(BaseModel):
    """Atividade removida antes da seleção por problemas de elegibilidade."""
    activity_id: str = Field(..., description="ID da atividade")
    motive_code: str = Field(
        ..., description="Código estável do motivo (invalid_duration, no_viable_route)"
    )


class RecommendationResult(BaseModel):
    """Resposta completa do endpoint."""
    strategy: Literal["personalized", "personalized_id", "baseline_random"] = Field(
        ..., description="Estratégia executada"
    )
    seed: Optional[int] = Field(
        None,
        description=(
            "Semente da baseline; semente do desempate na personalizada com "
            "tie_break='random'; nula na personalizada com tie_break='id'"
        ),
    )
    itinerary: ItineraryResult = Field(
        ..., description="Roteiro produzido com atividades por dia"
    )
    activities: List[str] = Field(
        ..., description="IDs das atividades selecionadas (achatada)"
    )
    metrics: MetricsResult = Field(..., description="Métricas de compatibilidade e cobertura")
    excluded_activities: List[ExcludedActivity] = Field(
        default_factory=list, description="Atividades elegíveis não inseridas"
    )
    ineligible_activities: List[IneligibleActivity] = Field(
        default_factory=list, description="Atividades removidas por elegibilidade"
    )
    notes: Optional[str] = Field(
        None, description="Observação livre sobre o resultado"
    )
    itinerary_metrics: Optional[ItineraryMetricsResult] = Field(
        None, description="Métricas secundárias do roteiro final (distância, tempos, ocupação, violações)"
    )

    model_config = {"extra": "forbid", "strict": True}
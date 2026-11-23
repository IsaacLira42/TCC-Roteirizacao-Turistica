from typing import Literal

from pydantic import BaseModel, Field


# Taxonomia oficial das sete categorias experimentais (ordem preservada)
CATEGORIAS_EXPERIMENTAL = [
    "praia",
    "natureza",
    "gastronomia",
    "cultura_historia",
    "lazer",
    "religioso",
    "compras_artesanato",
]


class CategoryWeights(BaseModel):
    """Schema de validação de pesos de categorias para o módulo de Preferences.

    Responsável unicamente pela validação de entrada (contrato HTTP).
    - Sete campos obrigatórios correspondentes às categorias do experimento.
    - Apenas números inteiros entre 0 e 3 (inclusive).
    - Rejeita chaves adicionais.
    - Não utilizar valores padrão.
    - Aceitar todos os pesos iguais a zero.
    - Disponibilizar uma forma clara de identificar categorias ativas e pesos zerados.
    - Não implementar persistência nem lógica de recomendação.
    """

    praia: int = Field(
        ..., ge=0, le=3,
        description="Interesse por praias (0 = não interessa, 3 = alto interesse)"
    )
    natureza: int = Field(
        ..., ge=0, le=3,
        description="Interesse por natureza (0 = não interessa, 3 = alto interesse)"
    )
    gastronomia: int = Field(
        ..., ge=0, le=3,
        description="Interesse por gastronomia (0 = não interessa, 3 = alto interesse)"
    )
    cultura_historia: int = Field(
        ..., ge=0, le=3,
        description="Interesse por cultura e história (0 = não interessa, 3 = alto interesse)"
    )
    lazer: int = Field(
        ..., ge=0, le=3,
        description="Interesse por lazer (0 = não interessa, 3 = alto interesse)"
    )
    religioso: int = Field(
        ..., ge=0, le=3,
        description="Interesse por religioso (0 = não interessa, 3 = alto interesse)"
    )
    compras_artesanato: int = Field(
        ..., ge=0, le=3,
        description="Interesse por compras e artesanato (0 = não interessa, 3 = alto interesse)"
    )

    model_config = {
        "extra": "forbid",
        "coerce_numbers_to_str": False,
        "strict": True,
    }

    @property
    def categorias_ativas(self) -> list[str]:
        """Retorna lista de categorias com peso estritamente maior que zero."""
        return [
            cat for cat in CATEGORIAS_EXPERIMENTAL
            if getattr(self, cat) > 0
        ]

    @property
    def todos_zerados(self) -> bool:
        """Retorna True se todos os sete pesos forem exatamente zero."""
        return all(
            getattr(self, cat) == 0
            for cat in CATEGORIAS_EXPERIMENTAL
        )

    def __repr__(self) -> str:
        ativos = self.categorias_ativas
        return (
            f"CategoryWeights("
            f"ativos={ativos if ativos else 'nenhum'}, "
            f"todos_zerados={self.todos_zerados})"
        )

"""Testes unitários do schema CategoryWeights do módulo Preferences."""

import pytest

from app.modules.preferences.schemas import CategoryWeights


# ---------- Payloads de teste ----------

payload_valido_variado = {
    "praia": 3,
    "natureza": 2,
    "gastronomia": 1,
    "cultura_historia": 0,
    "lazer": 0,
    "religioso": 0,
    "compras_artesanato": 0,
}

payload_todos_zerados = {
    "praia": 0,
    "natureza": 0,
    "gastronomia": 0,
    "cultura_historia": 0,
    "lazer": 0,
    "religioso": 0,
    "compras_artesanato": 0,
}

payloads_campos_adicionais = {
    "praia": 3,
    "natureza": 2,
    "gastronomia": 1,
    "cultura_historia": 0,
    "lazer": 0,
    "religioso": 0,
    "compras_artesanato": 0,
    "campo_extra": 1,
}

payloads_valores_invalidos = [
    ("menor_que_zero", {"praia": -1, "natureza": 0, "gastronomia": 0, "cultura_historia": 0, "lazer": 0, "religioso": 0, "compras_artesanato": 0}),
    ("maior_que_tres", {"praia": 4, "natureza": 0, "gastronomia": 0, "cultura_historia": 0, "lazer": 0, "religioso": 0, "compras_artesanato": 0}),
    ("decimal", {"praia": 3.5, "natureza": 0, "gastronomia": 0, "cultura_historia": 0, "lazer": 0, "religioso": 0, "compras_artesanato": 0}),
    ("string", {"praia": "3", "natureza": 0, "gastronomia": 0, "cultura_historia": 0, "lazer": 0, "religioso": 0, "compras_artesanato": 0}),
    ("booleano", {"praia": True, "natureza": 0, "gastronomia": 0, "cultura_historia": 0, "lazer": 0, "religioso": 0, "compras_artesanato": 0}),
]

payloads_campos_obrigatorios_ausentes = [
    ("sem_praia", {"natureza": 0, "gastronomia": 0, "cultura_historia": 0, "lazer": 0, "religioso": 0, "compras_artesanato": 0}),
    ("sem_natureza", {"praia": 0, "gastronomia": 0, "cultura_historia": 0, "lazer": 0, "religioso": 0, "compras_artesanato": 0}),
    ("sem_gastronomia", {"praia": 0, "natureza": 0, "cultura_historia": 0, "lazer": 0, "religioso": 0, "compras_artesanato": 0}),
    ("sem_cultura_historia", {"praia": 0, "natureza": 0, "gastronomia": 0, "lazer": 0, "religioso": 0, "compras_artesanato": 0}),
    ("sem_lazer", {"praia": 0, "natureza": 0, "gastronomia": 0, "cultura_historia": 0, "religioso": 0, "compras_artesanato": 0}),
    ("sem_religioso", {"praia": 0, "natureza": 0, "gastronomia": 0, "cultura_historia": 0, "lazer": 0, "compras_artesanato": 0}),
    ("sem_compras_artesanato", {"praia": 0, "natureza": 0, "gastronomia": 0, "cultura_historia": 0, "lazer": 0, "religioso": 0}),
]


# ---------- Tests ----------

class TestCategoryWeightsValid:
    """Tests for valid CategoryWeights payloads."""

    def test_payload_valido_variado(self):
        """Payload com pesos variados deve ser aceito."""
        data = payload_valido_variado
        cw = CategoryWeights(**data)
        assert cw.praia == 3
        assert cw.natureza == 2
        assert cw.gastronomia == 1
        assert cw.cultura_historia == 0
        assert cw.lazer == 0
        assert cw.religioso == 0
        assert cw.compras_artesanato == 0
        assert cw.todos_zerados is False
        assert "praia" in cw.categorias_ativas
        assert "natureza" in cw.categorias_ativas
        assert "gastronomia" in cw.categorias_ativas  # peso 1 > 0, deve estar ativo
        assert "cultura_historia" not in cw.categorias_ativas  # peso 0, deve estar inativo

    def test_payload_todos_zerados(self):
        """Payload com todos os pesos em zero deve ser aceito (caso válido)."""
        cw = CategoryWeights(**payload_todos_zerados)
        assert cw.todos_zerados is True
        assert cw.categorias_ativas == []
        assert repr(cw).endswith("todos_zerados=True)")


class TestCategoryWeightsInvalid:
    """Tests for invalid CategoryWeights payloads."""

    @pytest.mark.parametrize("nome, dados", payloads_valores_invalidos)
    def test_campos_invalidos_rejeitados(self, nome, dados):
        """Campos com valores fora da faixa 0-3 devem ser rejeitados."""
        with pytest.raises(Exception):
            CategoryWeights(**dados)

    @pytest.mark.parametrize("nome, dados", payloads_campos_obrigatorios_ausentes)
    def test_campos_obrigatorios_ausentes_rejeitados(self, nome, dados):
        """Ausência de qualquer campo obrigatório deve ser rejeitada."""
        with pytest.raises(Exception):
            CategoryWeights(**dados)

    def test_campos_adicionais_rejeitados(self):
        """Campos extras não previstos no schema devem ser rejeitados."""
        with pytest.raises(Exception):
            CategoryWeights(**payloads_campos_adicionais)


# ---------- Property Tests ----------

class TestCategoriasAtivas:
    """Tests for the categorias_ativas property."""

    def test_categorias_ativas_com_pesos_positivos(self):
        """Deve retornar apenas categorias com peso > 0."""
        data = {"praia": 2, "natureza": 0, "gastronomia": 1, "cultura_historia": 0, "lazer": 0, "religioso": 0, "compras_artesanato": 0}
        cw = CategoryWeights(**data)
        assert cw.categorias_ativas == ["praia", "gastronomia"]

    def test_categorias_ativas_com_todos_zerados(self):
        """Quando todos pesos são zero, deve retornar lista vazia."""
        cw = CategoryWeights(**payload_todos_zerados)
        assert cw.categorias_ativas == []

    def test_categorias_ativas_ordem_preservada(self):
        """A ordem das categorias deve seguir a taxonomia oficial."""
        data = {"praia": 1, "natureza": 1, "gastronomia": 0, "cultura_historia": 1, "lazer": 0, "religioso": 0, "compras_artesanato": 0}
        cw = CategoryWeights(**data)
        # Lista fixa — se a propriedade mudar a ordem, o teste falha
        assert cw.categorias_ativas == ["praia", "natureza", "cultura_historia"]


# ---------- Integration-style Tests ----------

class TestSchemaStrictness:
    """Tests ensuring strict type checking."""

    def test_rejeita_float(self):
        """Números float devem ser rejeitados mesmo que sejam iguais a um inteiro."""
        with pytest.raises(Exception):
            CategoryWeights(**{"praia": 3.0, "natureza": 0, "gastronomia": 0, "cultura_historia": 0, "lazer": 0, "religioso": 0, "compras_artesanato": 0})

    def test_rejeita_booleano(self):
        """Booleanos devem ser rejeitados (True é int(1) em Python, mas strict=True deve bloquear)."""
        with pytest.raises(Exception):
            CategoryWeights(**{"praia": True, "natureza": 0, "gastronomia": 0, "cultura_historia": 0, "lazer": 0, "religioso": 0, "compras_artesanato": 0})

    def test_aceita_zero(self):
        """O valor 0 deve ser aceito como peso válido."""
        cw = CategoryWeights(**payload_todos_zerados)
        assert cw.todos_zerados is True
    def test_aceita_trinca(self):
        """Os valores 0, 1, 2, 3 devem ser aceitos."""
        for valor in [0, 1, 2, 3]:
            data = {"praia": valor, "natureza": 0, "gastronomia": 0, "cultura_historia": 0, "lazer": 0, "religioso": 0, "compras_artesanato": 0}
            cw = CategoryWeights(**data)
            assert getattr(cw, "praia") == valor


# ---------- Helper ----------

# Re-definição do payload todos zerados para uso nos testes
import json
payload_todos_zerados = {
    "praia": 0,
    "natureza": 0,
    "gastronomia": 0,
    "cultura_historia": 0,
    "lazer": 0,
    "religioso": 0,
    "compras_artesanato": 0,
}
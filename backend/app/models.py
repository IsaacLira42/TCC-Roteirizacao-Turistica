# Agregador de modelos para o Alembic.
# Importe aqui TODOS os modelos que herdam de Base,
# para que Base.metadata os conheça durante o autogenerate.

from app.modules.activities.models import Activity  # noqa: F401

__all__ = ["Activity"]

"""Обучение и перенос боевого опыта между ПК."""

from .battle_experience import (
    export_battle_experience,
    get_battle_host_id,
    import_battle_experience,
)

__all__ = [
    "export_battle_experience",
    "get_battle_host_id",
    "import_battle_experience",
]
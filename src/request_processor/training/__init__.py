"""Обучение и перенос данных prod между рабочим ПК и машиной разработки."""

from .prod_data import (
    export_prod_data,
    get_prod_station_id,
    import_prod_data,
)

__all__ = [
    "export_prod_data",
    "get_prod_station_id",
    "import_prod_data",
]

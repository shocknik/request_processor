"""Устаревший скрипт миграции в пакеты (v0.8.2+ shim удалены).

Оставлен для справки. Модули уже лежат в extraction/, parsing/, …
Повторный запуск не требуется.
"""

from __future__ import annotations

import sys

print(
    "reorganize_packages.py: миграция завершена в v0.8.2, shim-файлы удалены.",
    file=sys.stderr,
)
raise SystemExit(0)
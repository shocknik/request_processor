# Версии Lab_request / request-processor

## Принцип: несколько осей, у каждой — один SoT

| Ось | Что означает | **Единый источник истины** | Где ещё видно |
|-----|--------------|----------------------------|---------------|
| **Приложение (package)** | Релиз продукта / zip / GUI | **`pyproject.toml` → `[project].version`** | `__version__` (importlib.metadata), лог `package_version` / `pyproject_version`, README «см. pyproject» |
| **Схема БД** | Совместимость migrate-db | **Код миграций** в `persistence/sqlite_repo.py` (и будущий `migrations/`) | После migrate; backup перед update |
| **protocol_meta** | Контракт с protocol_generator | **Поле `schema_version` в JSON** + docs `PROTOCOL_GENERATOR_BRIDGE.md` | Contract tests |
| **Алгоритмы extract/OCR** | Воспроизводимость кэша / corrections | Явные version-строки в коде/кэш-ключе (по мере введения) | OCR cache key, CorrectionEvent |
| **Роль данных (БД-файл)** | dev vs work | **`db_profile` рядом с файлом** (`db-role` / `db-info`) | Заголовок GUI |

**Не** смешивать: bump `0.9.1 → 0.9.2` **не** обязан менять `protocol_meta.schema_version` и наоборот.

Книга (learning book, ред. 2) формулирует то же:  
«Для релиза версия приложения, схема БД и формат protocol_meta должны иметь **отдельные и однозначные** номера.»

---

## Правила для агента и релизов

1. **Менять package version** — только в `pyproject.toml`.  
   Затем: `pip install -e .` (чтобы egg-info = pyproject).  
   README / INSTALL / паспорт — «Версия: см. `pyproject.toml`» или подтягивать при релизе **из** pyproject, не руками вразнобой.

2. **Не** дублировать «магическую» константу `0.9.1` в `src/` (кроме fallback `0.0.0-dev` если пакет не установлен).

3. При релизе zip имя может содержать package version:  
   `request_processor_<version>_YYYYMMDD.zip` — version читается из pyproject.

4. `db-info` / роль БД **не** версия приложения: это метка **данных**.

---

## Диагностика

```powershell
request-processor --version          # package (Click)
python -c "import request_processor as r; print(r.__version__)"
# в логе старта: package_version=… pyproject_version=…  (mismatch → pip install -e .)
request-processor db-info            # роль data/app.db
```

---

## Что ещё не централизовано (долг, не блокер)

- Явный `SCHEMA_VERSION` / таблица `schema_migrations` (сейчас migrate идемпотентный, без единого номера в UI).
- Bump README «205 tests» / дат — при релизе, не в каждом PR.
- Learning book / паспорт — снимки на дату; не SoT runtime.

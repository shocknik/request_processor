# База требований, aliases и каталог приёмки ТУ

**Статус:** S5 каркас + **волна 1** (`acceptance_items`, 2026-07-24).  
Полный импорт таблиц из docx — **волна 2**. Файлы ТУ **только локально**, не в git.

ТЗ: Obsidian «63 - ТЗ ТУ каталог — сжато для переутверждения (v3)» (согласовано).

## Зачем

| Проблема | Решение |
|----------|---------|
| Одно испытание — много названий в ПМИ/письмах | `test_aliases` |
| Пункт ТУ ↔ метод ↔ прайс | `requirements` + links + **acceptance_items** |
| Строка таблицы приёмки ТУ | `acceptance_items` + `acceptance_item_clauses` |
| Внешний ГОСТ метода | `method_external_refs` (отдельный контур) |
| Программы S4 | позже: auto-link program_item → acceptance |

## Таблицы

```
norm_documents           — ТУ / ГОСТ / IEC (+ edition_note, source_format, status)
requirements             — пункт clause (один, не диапазон) + title/body + clause_kind
requirement_test_links   — requirement → price_test_code
test_aliases             — «r жилы» → канон / code
acceptance_items         — строка приёмки (name_exact, billable, regime_json, …)
acceptance_item_clauses  — item ↔ requirement (role: requirement | method_internal)
method_external_refs     — item → ГОСТ/IEC + метод
```

**Решения v3:** `group_code` / `test_category` опциональны; маркировка — `billable=0`;  
режимы v1 — плоский `regime_json` (ветки по марке — v2).

## Seed (авто при migrate-db)

- Пример **ТУ 16.К99-058-2014** (2 пункта)  
- Пример **ГОСТ 7229-76**  
- Aliases: «сопротивление жил», «r жилы», …

## CLI

```powershell
request-processor migrate-db
request-processor list-norm-documents
request-processor list-requirements
request-processor list-test-aliases
request-processor add-test-alias --alias "сопротивление ТПЖ" --canonical "…" --code resistance_core

# Волна 1 — каталог приёмки
request-processor list-acceptance-items
request-processor list-acceptance-items --doc "ТУ 27.31.11-131-47273194-2025"
request-processor show-norm-catalog --doc "ТУ 27.31.11-131-47273194-2025"
request-processor show-acceptance-item --id 1
request-processor add-acceptance-item --doc "ТУ-…" --name "…" --req 2.5.1 --method 5.4.1
```

Seed при migrate: 3 строки эталона **131** (растяжение, затухание, маркировка n/a).

## Как наполнять (пока вручную / полуавто)

1. Вы выбираете 1 ТУ из `data/training/rag_corpus/tu` (локально).  
2. Добавляем `norm_documents` + ключевые `requirements` (CLI/SQL/будущий GUI).  
3. Вяжем к `price_test_code` и aliases.  
4. Импорт программ (S4) начинает чаще попадать в прайс.

Авто-парсинг PDF/DOC ТУ **не** включён в этот релиз — только каркас.

## Связь с обновлением на рабочем ПК

`migrate-db` (в `update.ps1`) создаст таблицы **без** потери заказов.  
См. [UPDATE.md](UPDATE.md).

## Импорт из локального корпуса (S5.1)

### Текст ТУ → requirements

```powershell
# один файл
request-processor import-norm-text --file "data\knowledge\manufacturer_v1\raw_text\16.К99-058-2014.txt"

# пакет из корпуса (S5, 2026-07-22)
request-processor import-norm-text --dir "data\knowledge\manufacturer_v1\raw_text" --limit 15 --max-clauses 40
request-processor list-norm-documents
request-processor list-requirements
```

GUI: вкладка **10. Программы** → блок «Нормы и синонимы» → **Импорт ТУ .txt…**

Эвристика: строки `1.4.1 Описание…` с ключевыми словами (испытан, сопротивл…).  
Это **каркас**, не юридически полный разбор.

Рекомендуемые ТУ для наполнения (локально): `16.К99-058-2014`, `27.31.11-131-*` (Вулкан/ОК), `27.32.13-099-*`.

### YAML синонимов → aliases

```powershell
request-processor import-aliases-yaml --file "data\knowledge\manufacturer_v1\test_synonyms.yaml"
request-processor list-test-aliases
```

Aliases участвуют в:
- `map_requirements_to_tests` (подсказки испытаний из текста);
- `match-program-price` (сопоставление позиций программы).

## Не в git

Корпус `rag_corpus/**`, `data/knowledge/**` — только на диске.  
В репозиторий: схема, seed, код импорта, документация.

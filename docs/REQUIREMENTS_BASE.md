# База требований и aliases (S5 — каркас)

**Статус:** схема + seed-примеры + CLI.  
Полный разбор ТУ/IEC/ГОСТ из `rag_corpus` — **следующий этап** (файлы локально, не в git).

## Зачем

| Проблема | Решение v1 |
|----------|------------|
| Одно испытание — много названий в ПМИ/письмах | `test_aliases` |
| Пункт ТУ ↔ метод ↔ прайс | `norm_documents` + `requirements` + `requirement_test_links` |
| Программы уже импортируют пункты | позже: auto-link program_item → requirement |

## Таблицы

```
norm_documents     — ТУ / ГОСТ / IEC (идентификатор, kind, title)
requirements       — пункт (clause) + title/body
requirement_test_links — requirement → price_test_code
test_aliases       — «r жилы» → канон / code
```

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
```

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

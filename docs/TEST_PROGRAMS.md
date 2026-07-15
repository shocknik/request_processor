# Программы испытаний (S4)

**Lab_request** хранит программы ПМИ/ПИ в SQLite и умеет импортировать **полный Word (.docx)**.

## Зачем

1. Не набивать перечень испытаний вручную на каждый заказ.  
2. Связать пункты ТУ / методов с позициями программы.  
3. По возможности сопоставить строки с **прайсом** (`test_items`) → быстро заполнить вкладку «Расчёт».  
4. Позже — кормить protocol_generator и базу требований.

## Модель данных

```
test_programs
  id, name, test_type, cable_mark_text, tu_ref, source_path, notes, …

test_program_items
  program_id, sort_order, name
  requirement_doc, requirement_clause   -- документ/пункты требований
  method_doc, method_clause             -- документ/пункты метода
  price_test_code                       -- опц. код из прайса
  meta_json                             -- задел под режимы
```

**Не путать** с `test_items` (прайс) и `test_mappings` (фраза → код).

## Как устроен импорт DOCX

Типовой файл (как у Спецкабель):

1. **Абзацы** — «ПРОГРАММА», вид (приёмосдаточные / исследовательские…), марка, ТУ.  
2. **Таблицы** 4 колонки:  
   `№ | Вид испытаний | Пункты требований | Пункты методов`

Импортёр:

- читает **все** таблицы (не только первую);
- склеивает многострочные ячейки;
- вытаскивает ТУ regex `ТУ …`;
- не трогает PDF/`.doc` (нужен именно **docx**).

Код: `src/request_processor/generation/program_importer.py`.

## GUI

Вкладка **10. Программы**:

| Кнопка | Действие |
|--------|----------|
| Импорт DOCX… | Файл → БД |
| Сопоставить прайс | `price_test_code` по имени / test_mappings |
| → В расчёт | отмечает испытания с известным кодом на вкладке 2 |
| Удалить | cascade items |

## CLI

```powershell
request-processor migrate-db

request-processor import-test-program --file "path\to\программа.docx"
request-processor list-test-programs
request-processor show-test-program --id 1
request-processor match-program-price --id 1
request-processor delete-test-program --id 1 --yes
```

## Сопоставление с прайсом

Порядок:

1. Уже заданный `price_test_code`  
2. Точное / подстрочное совпадение `name` ↔ `test_items.name`  
3. `map_requirements_to_tests` (в т.ч. авто-маппинги «имя прайса → code»)

Не всё сопоставится с первого раза — это нормально. Допишите маппинг в **11. Настройки** или вручную в БД позже.

## Связь с другими частями

| Модуль | Связь |
|--------|--------|
| Расчёт | «→ В расчёт» |
| protocol_meta JSON | позиции расчёта (после применения) |
| База требований (S5) | requirement_doc/clause → каталог норм |

## Ограничения v1

- Только **docx** (не скан PDF).  
- Сложные объединённые ячейки / многоуровневые таблицы — эвристика.  
- Режимы (температура, ГСМ…) пока в `meta_json` не разбираются.  
- Синонимы «одно испытание — много названий» — через `test_mappings`, не отдельная таблица aliases (заложено в плане 46).

## Файлы

| Путь | Роль |
|------|------|
| `persistence/sqlite_repo.py` | таблицы + CRUD + match |
| `generation/program_importer.py` | parse/import docx |
| `cli.py` | import/list/show/delete/match |
| `ui/gui.py` | вкладка 10 |

---

*S4 · Lab_request · corpus PMI локально, не в git.*

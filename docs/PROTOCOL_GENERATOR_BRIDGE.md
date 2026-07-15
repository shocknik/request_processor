# Мост request-processor → protocol_generator

**Версия:** v0.10 (S3)  
**Цель:** из заказа Lab_request получить **JSON без измеренных значений** и скормить его `protocol_generator` **без правок** его кода.

## Поток

```
Заказ (марки + расчёты)
    → export-protocol-meta / кнопка «JSON → protocol_generator»
    → data/generated/protocol_meta_order….json
    → protocol_generator main.py <json>
    → DOCX протокол (таблицы; «факт» пустой)
```

## Lab_request

**GUI:** вкладка **4. Заказы** → выбрать заказ → **JSON → protocol_generator**

**CLI:**

```powershell
request-processor export-protocol-meta --order-id 12
# или
request-processor export-protocol-meta --order-id 12 -o D:\tmp\meta.json
```

## protocol_generator

Не меняем. Запуск:

```powershell
cd D:\My_projects\protocol_generator
.\venv\Scripts\python.exe main.py "D:\My_projects\request_processor\data\generated\protocol_meta_….json"
```

Или из репо request-processor:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_protocol_from_json.ps1 `
  -JsonPath "data\generated\protocol_meta_order12_….json"
```

## Что в JSON

| Секция | Содержимое |
|--------|------------|
| PRIMARY | как в `meta_with_single_laying.json` |
| 3 / 4 | заказчик / изготовитель из заказа |
| 5 | марка, ID = order_id |
| 7 | цель + перечень марок |
| 9 | методы из прайса (если есть) |
| 10 | испытания из строк расчёта; **Фактический результат = ""** |
| 11 | оборудование — пустой объект (заполнить позже / вручную) |
| `_meta` | служебное: order_id, measured_values=false |

## Ограничения v1

- Нет полного оборудования ИЛ (секция 11 пустая).  
- Нет «умных» критериев из ТУ — заглушки «—».  
- Пожарные специализированные таблицы protocol_generator заработают, когда в JSON появятся соответствующие блоки (позже).  
- Несколько марок в заказе: в объекте — первая; все перечислены в цели.

## Связанные файлы

- `src/request_processor/generation/protocol_meta_export.py`
- `scripts/run_protocol_from_json.ps1`
- Образец формата: `D:\My_projects\protocol_generator\data\meta_with_single_laying.json`

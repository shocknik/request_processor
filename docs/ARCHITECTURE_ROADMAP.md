# Архитектура Lab_request: что уже есть (S1–S5)

Краткая карта для оператора и разработчика. Детали — в отдельных docs/.

```
┌─────────────────────────────────────────────────────────────┐
│  Lab_request (request-processor)                            │
│                                                             │
│  1 Заявка → extract (docx/pdf) → human confirm              │
│  2 Расчёт ← прайс test_items + test_mappings + aliases      │
│  3 КП ← lab_profile + logo + styles                         │
│  4 Заказы → пакет / JSON protocol_meta                      │
│  10 Программы ← import DOCX PMI                             │
│  12 Журнал ← logs                                           │
│                                                             │
│  data/app.db  (сохраняется при update.ps1)                  │
└───────────────────────────┬─────────────────────────────────┘
                            │ JSON без измерений
                            ▼
              protocol_generator (отдельный проект)
                            │
                            ▼
                      DOCX протокол
```

| Спринт | Содержание | Документ |
|--------|------------|----------|
| S1 | UX, Lab_request, удаления, старт | INSTALL, UPDATE |
| S2 | КП стили, лого, Журнал, Урок ИИ 0 | lab_profile.example |
| S3 | JSON → protocol_generator | PROTOCOL_GENERATOR_BRIDGE |
| S4 | Программы DOCX | TEST_PROGRAMS |
| S5 | Каркас норм + aliases | REQUIREMENTS_BASE |
| Ops | Обновление без сноса | **UPDATE.md** |

## Принципы

1. **data/** — святое (БД, corrections, generated).  
2. **Код** обновляется zip/update.ps1.  
3. **protocol_generator** не правим — только JSON.  
4. **LLM** opt-in, human-in-the-loop.  
5. **rag_corpus** локально, не git.

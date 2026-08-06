# UI architecture (v0.10 redesign)

Монолитный `gui.py` ранее разбит на расширяемый пакет; в v0.10 добавлен
редизайн оболочки и страницы «Заявки» под макет (sidebar + cards).

```
ui/
  gui.py              # entry: main (lazy re-exports, без тяжёлого import)
  bootstrap.py        # splash ASAP → import app → init → mainloop (+ t_pre_splash/t_import)
  app.py              # RequestProcessorApp (mixins + tk.Tk)
  state.py            # CalcTestEntry, ExtractionDraft, RequestPageState
  theme.py            # AppStyles + design tokens (#F5F7FA / #1677FF)
  extract_job.py      # 2026-07-27: worker extract (Queue), no tkinter
  bg_job.py           # 2026-07-28: run_bg_job / schedule_ui (короткие Thread-jobs)
  modal.py            # 2026-07-28: create_modal / present_modal / run_modal (D4)
  feedback_journal.py # 2026-07-31: журнал пожеланий (Файл → …)
  shell/
    app_shell.py      # __init__(progress=…), _build_ui (sidebar + notebook)
    menubar.py        # Файл / Вид / Данные / Сервис / Справка
  tabs/
    pdf_tab.py        # «Заявки»: extract_job + free-text bg_job; org HITL; clipboard fields
    calc_tab.py       # picker: Canvas + Checkbutton, _picker_active_category
    orgs_tab.py       # поиск org Unicode casefold (06.08)
    kp_tab.py, orders_tab.py, ...
  widgets/
    splash.py         # splash + progress; без ico с UNC (NAS cold start)
    clipboard.py      # Ctrl+C/V/X keycode-first (RU/EN), anti double-paste (06.08)
    sidebar.py        # Sidebar, NAV_ITEMS, SECTION_TO_TAB
    components.py     # PageHeader, StepIndicator, UploadPanel,
                      # EmptyState, BottomActionBar, StatusBadge, CardFrame
```

## Clipboard / org search (2026-08-06)

- **ClipboardMixin:** обработка Ctrl+C/X/V/A по **Windows keycode** (раскладка RU/EN);
  повторный paste после copy блокируется (`_rp_clip_busy`); поле адреса Заявки —
  `_enable_field_clipboard` (keycode first).
- **Организации:** `list_organizations(search=…)` фильтрует через `str.casefold()`
  (кириллица: «тольят» = «Тольят»). SQLite `LIKE` для не-ASCII регистрозависим.

## Startup (2026-08-06)

- `bootstrap.run_gui`: окно splash **до** version/logging/тяжёлого `app`;
  лог: `t_pre_splash`, `t_import`, `ready total`.
- `start_gui.bat`: сообщение «запуск…» (на NAS pythonw может молчать 10–20 с);
  `REQUEST_PROCESSOR_SPLASH_ICON=0` — не тянуть ico с UNC.

## Extract / progress (2026-07-27)

- **Worker** (`extract_job.run_extract_job`): только `extract_from_document` +
  `prepare_extraction_draft` → `queue.Queue[GuiExtractEvent]`.  
  Запрещено: `self.after`, `StringVar.get`, `messagebox`, `destroy`.
- **Main** (`pdf_tab._run_extract_pdf`): читает tk-vars → dialog →
  `after` poll Queue → `_apply_extraction_draft_ui` → 💡 hints отдельно.
- Progress: этап, детали, elapsed, indeterminate bar, кнопка **Отмена**
  (`cancel_event`). Без `grab_set` / `wait_window`.
- Диагностика: log tag `ExtractTimeline`, `data/logs/gui_extract_trace.log`,
  `runtime fingerprint` (path/sha `pdf_tab.py`).
- Py 3.12+: `tk.StringVar(master=dlg)` на Toplevel (default root).

## Background jobs (2026-07-28, D1)

Два стиля (не смешивать tk в worker):

| Когда | Модуль | Паттерн |
|-------|--------|---------|
| Длинный job + progress / cancel | `extract_job` | Queue + poll main |
| Короткий (расчёт, КП, Word) | `bg_job.run_bg_job` | Thread + `after(0)` |

- `work()` — pure, без tk/vars; `on_success` / `on_error` — только main.
- `schedule_ui(root, cb)` — безопасный `after(0)` (pytest без mainloop → warning).
- На `run_bg_job`: calc, KP, orders (application / protocol / protocol_meta), programs import.
- Extract по-прежнему Queue; pack documents — sync main thread.

## Modal dialogs (2026-07-28, D4)

```
create_modal(parent, title=…)  →  pack widgets  →  present_modal / run_modal
```

- **Не** `grab_set` до geometry (Windows 1×1).
- Vars: `StringVar(master=dlg, …)`.
- Уже: pack options, mark editor, org editor, test add, mapping editor.

## Роль БД в заголовке (2026-07-28)

`app_shell` при старте читает `persistence.db_profile` и ставит title:

`Lab_request · БД: тестовая [DEV]` / `копия рабочей [WORK-COPY]` / `рабочая [WORK]`.

CLI: `request-processor db-info`, `db-role --set …`. См. `docs/VERSIONING.md`, `docs/db_profile.example.yaml`.

## Calc picker (2026-07-27)

- Источник фильтра категории: `_picker_active_category` (не combobox StringVar).
- Список: scroll Canvas + `ttk.Checkbutton` + стабильные `BooleanVar`.
- Combobox values обновлять после load прайса, не на каждый refresh.
- Ввод марки / поиск: debounce **180 ms** (не rebuild на каждый символ).

## Старт (splash)

При `start_gui.bat` / ярлыке сначала показывается **Lab_request** splash
(тёмный, без рамки): прогресс 0–100% и лента этапов.

| % (примерно) | Этап |
|--------------|------|
| 5–12 | загрузчик, DPI, логи |
| 12–50 | import `ui.app` (тяжёлые зависимости) |
| 55–70 | БД / migrate / прайс |
| 70–88 | тема + сборка UI |
| 90–99 | справочники (марки, орг, заказы…) |
| 100 | deiconify главного окна |

Почему на **рабочем ПК** дольше, чем на dev: часто `W:\` (NAS), cold start
после включения, антивирус, `pythonw` + первый import пакетов; на dev —
локальный SSD и тёплый кэш. В логе ищите `[Старт] … ms`.

## UX (v0.10)

- **Левая боковая панель** вместо длинного горизонтального ряда вкладок:
  Заявки · Расчёты · КП · Заказы | Марки · Организации · Программы |
  История · Сравнение · Настройки. Сворачивание «« / »».
- **Notebook скрыт** (`Hidden.TNotebook`) — API `notebook.select()` /
  menubar / smoke-тесты сохранены; навигация через sidebar.
- **Этапы заявки** (1. Загрузка → 2. Распознавание → 3. Проверка →
  4. Подтверждение) — отдельный `StepIndicator`, **не** смешиваются с
  бизнес-разделами Расчёт/КП/Заказ.
- **Страница «Заявки»**: PageHeader + UploadPanel + карточки Марки /
  Организации + BottomActionBar; одна primary-кнопка в каждый момент.
- **Состояние**: `RequestPageState` + `render_request_state()` —
  единая точка обновления статуса, этапа, кнопок, empty state.
- Меню — вторичные действия (Файл / Вид / Данные / Сервис / Справка).
- **Нет вкладки «Журнал»** — логи в `data/logs/` (Сервис → Открыть папку логов…).

## Design tokens

| Роль | Цвет |
|------|------|
| Фон | `#F5F7FA` |
| Карточки | `#FFFFFF` |
| Акцент | `#1677FF` |
| Текст | `#1F2329` |
| Вторичный | `#6B7280` |
| Границы | `#D9DEE7` |

Стили: `AppStyles.configure()` / `apply_fluent_theme()` — тема `clam`,
именованные `Sidebar.*`, `Primary.TButton`, `PageTitle.TLabel`, …

## RequestPageState

| State | Бейдж | Primary |
|-------|--------|---------|
| EMPTY | Не обработана | Извлечь данные (disabled) |
| FILE_SELECTED | Документ выбран | Извлечь данные |
| PROCESSING | Распознавание | Распознавание… |
| REVIEW_REQUIRED | Требует проверки | Подтвердить заявку |
| READY_TO_CONFIRM | Готова к подтверждению | Подтвердить заявку |
| CONFIRMED | Подтверждена | Извлечь данные |
| ERROR | Ошибка | Извлечь данные |

## Logs

| File | Source |
|------|--------|
| `data/logs/app_YYYY-MM-DD.log` | GUI, CLI, runtime, uncaught exceptions, env snapshot |
| `data/logs/scripts_YYYY-MM-DD.log` | `install.ps1`, `update.ps1`, `create_desktop_shortcut.ps1` |
| `data/logs/tests_YYYY-MM-DD.log` | pytest session (pass/fail each test) |
| `data/gui_launch.log` | `start_gui.bat` launch errors |

Set `REQUEST_PROCESSOR_LOG=DEBUG` for verbose console. UI-теги: `[UI]`, `[Заявка]`, `[Старт]`.

## Price catalog

`ensure_price_catalog()` restores full `test_items` from xlsx or bundled
`persistence/price_catalog_seed.json` when the DB has fewer than 20 rows
(clean install without `-IncludeAppDb`).

## Desktop shortcut

`scripts/create_desktop_shortcut.ps1` is UTF-8 BOM + ASCII-safe strings
so Windows PowerShell 5.1 does not mojibake Cyrillic and fail to parse.

## Принципы расширения

1. Новые разделы: tab mixin + `notebook.add` + пункт в `NAV_ITEMS` /
   `SECTION_TO_TAB` (или только меню, если нет в сайдбаре).
2. Бизнес-логику не класть в widgets — только layout/state hooks.
3. Тяжёлые OCR/парсинг — поток + `after()` для UI (как `_run_extract_pdf`).
4. Не ломать `notebook.select` / smoke: 11 вкладок, прежние tab text.

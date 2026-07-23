# UI architecture (v0.10 redesign)

Монолитный `gui.py` ранее разбит на расширяемый пакет; в v0.10 добавлен
редизайн оболочки и страницы «Заявки» под макет (sidebar + cards).

```
ui/
  gui.py              # entry: main (lazy re-exports, без тяжёлого import)
  bootstrap.py        # splash → import app → init → mainloop
  app.py              # RequestProcessorApp (mixins + tk.Tk)
  state.py            # CalcTestEntry, ExtractionDraft, RequestPageState
  theme.py            # AppStyles + design tokens (#F5F7FA / #1677FF)
  shell/
    app_shell.py      # __init__(progress=…), _build_ui (sidebar + notebook)
    menubar.py        # Файл / Вид / Данные / Сервис / Справка
  tabs/
    pdf_tab.py        # страница «Заявки» (редизайн)
    calc_tab.py, kp_tab.py, orders_tab.py, ...
  widgets/
    splash.py         # тёмный splash + progress bar + этапы [Старт]
    clipboard.py      # Ctrl+C/V/X, context menus for entries
    sidebar.py        # Sidebar, NAV_ITEMS, SECTION_TO_TAB
    components.py     # PageHeader, StepIndicator, UploadPanel,
                      # EmptyState, BottomActionBar, StatusBadge, CardFrame
```

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

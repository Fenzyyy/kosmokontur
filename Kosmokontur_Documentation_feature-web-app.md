# Топливный космоконтур 2035 — техническая и конкурсная документация

**Снимок проекта:** ветка `feature/web-app`  
**Commit:** `9618841a2847a8aabd124caa0b7a2f5113137a7d`  
**Дата анализа:** 19 сентября 2026 г.  
**Репозиторий:** `Fenzyyy/kosmokontur`

> Документ описывает фактическое состояние репозитория на указанном коммите. Код, данные и репозиторий в ходе подготовки этой документации не изменялись.

## 1. Назначение проекта

Проект реализует расчётно-оптимизационный цифровой контур для топливного узла 2035–2040 гг. Он объединяет исходные таблицы кейса, суточный физический баланс топлива, контрактные ограничения, инвестиционные решения, экономические расчёты, обязательный стресс-сценарий и веб-интерфейс оператора.

Критерии кейса проверяют одновременно модель, цифровой контур, контрольные/стресс-тесты, риски, выгрузки и защитные материалы; поэтому эта документация разделяет **что уже реализовано в коде** и **какие конкурсные артефакты ещё отсутствуют**.

## 2. Состав репозитория

### 2.1 Архитектура верхнего уровня

```text
kosmokontur/
├─ backend/                    # основной FastAPI-адаптер
├─ frontend/                   # HTML/CSS/JS операторского интерфейса
├─ fuel_model/                 # расчётное ядро
├─ data/case_input/            # исходные таблицы кейса
├─ configs/                    # TEAM_ASSUMPTION / роли источников
├─ tests/                      # reference cases и web integration
├─ tools/                      # adapter для organizer ParticipantPlan
├─ kosmokontur/tests/          # небольшой legacy-набор expected checks
├─ .github/workflows/          # CI optimizer + web integration
├─ Dockerfile
├─ run_local.py
├─ start_local.bat
└─ README_WEB.md
```

В ветке также отслеживаются каталоги `__pycache__`; это не участвует в расчётной архитектуре и не является функциональной частью цифрового контура.

### 2.2 Канонический путь выполнения

```text
CSV + JSON
   │
   ▼
load_case()
   │
   ▼
Case
   │          Plan JSON             Scenario
   │              │                    │
   └──────────────┴──────────┬─────────┘
                              ▼
                       validate_plan()
                              │
                              ▼
                          resolve()
                              │
                              ▼
                       engine.evaluate()
                  ┌───────────┴───────────┐
                  ▼                       ▼
             _physics()               _costs()
                  └───────────┬───────────┘
                              ▼
                       checks + KPI
                              │
                              ▼
                           Result
                              │
                    FastAPI serialization
                              │
                              ▼
                         Browser UI
```

Это соответствует критерию архитектуры: происхождение результата можно проследить от входных данных и решений до поставок, баланса, затрат, ограничений и результата.

## 3. Исходные данные кейса

### 3.1 Горизонт спроса

| Год | Общий спрос, т | Критический спрос, т | Low, т | High, т |
|---:|---:|---:|---:|---:|
| 2035 | 100 | 80 | 80 | 110 |
| 2036 | 140 | 105 | 112 | 154 |
| 2037 | 190 | 135 | 152 | 209 |
| 2038 | 250 | 170 | 200 | 312.5 |
| 2039 | 320 | 210 | 256 | 400 |
| 2040 | 390 | 250 | 312 | 487.5 |

Критический спрос в модели трактуется как подмножество общего. `combined_total_demand()` не складывает критический спрос второй раз; `serve_demand()` сначала обслуживает critical, затем non-critical.

### 3.2 Каналы поставки

| ID | Канал | Мощность, т/год | Переменная цена, млн/т | Reservation, млн/т-год | Take-or-pay | Lead time | Роль |
|---|---|---:|---:|---:|---:|---:|---|
| A | Earth-Core | 190 | 6.2 | 0.45 | 70% | 12 мес | базовый Earth |
| B | Earth-Flex | 110 | 8.9 | 0.15 | 0% | 4 мес | гибкий Earth |
| C | Earth-New | 130 | 7.1 | 0.30 | 50% | 18–24 мес | требует `EARTH_NEW` |
| D | Lunar-ISRU | 120 | 3.0 | 0 | 0% | 1–2 мес | требует `LUNAR_ISRU`, post-commissioning |
| E | Emergency | 80 | 13.8 | 0.35 | 0% | 6 недель | резервный канал |

`reliability_profile` хранится как метаданные CASE_INPUT; в BASE эти множители не применяются. В обязательном стрессе фактическая поставка D задаётся явно через `delivery_share`, без повторного умножения на reliability.

### 3.3 Хранение

| Режим | Ёмкость, т | Потери на throughput | Holding cost, млн/т-год | CAPEX, млн | Fixed OPEX, млн/год |
|---|---:|---:|---:|---:|---:|
| BASE | 70 | 4.5% | 0.72 | 0 | 0 |
| ZBO | 120 | 1.2% | 0.72 | 180 | 12 |

Особенно важно для stress: предел потерь равен 2%, поэтому базовое хранилище с 4.5% потерь не удовлетворяет stress loss ceiling; ZBO с 1.2% удовлетворяет его. Оптимизатор имеет отдельный precheck, который отсеивает инвестиционный набор, если требуемый loss ceiling заведомо недостижим.

### 3.4 Инвестиции

| Опция | Этапы | Total CAPEX, млн | Ввод |
|---|---|---:|---|
| EARTH_NEW | option 90 + exercise 270 | 360 | канонический график: 2035-01, ввод 2037-01 |
| LUNAR_ISRU | exercise 1250 | 1250 | канонический график: 2035-01, ввод 2038-01 |
| ZBO | modernization 180 | 180 | канонический график: 2036-01, ввод 2036-01 |

Три опции дают `2^3 = 8` инвестиционных комбинаций, и текущий real-case test проверяет наличие всех восьми в frontier.

Лимиты кейса: CAPEX до конца 2037 г. — 1800 млн; всего до конца 2040 г. — 2800 млн.

### 3.5 Ограничения

- Общий service level BASE ≥ 97% ежегодно.
- Critical service level BASE ≥ 99% ежегодно.
- CAPEX до конца 2037 ≤ 1800 млн.
- CAPEX до конца 2040 ≤ 2800 млн.
- 45-дневный резерв ежегодно.
- Emergency не используется как базовый канал более двух лет подряд.
- В MANDATORY_STRESS потери 2038–2040 ≤ 2% валового поступления.

Эти требования соответствуют формату критериев, где жюри ожидает годовые проверки сервиса, ёмкости, мощности, CAPEX, сроков, резерва и контрактов, без маскирования нарушений усреднением.

## 4. Математическая модель

### 4.1 Временная дискретизация

- Расчётный шаг: 1 сутки.
- Каждый модельный год: 365 суток.
- Поставки по годовому заказу распределяются по доступным первым числам месяцев.
- Отдельно учитывается подготовительный период до горизонта.
- Для месяцев используется календарная арифметика, для day/week — точное смещение.

### 4.2 Материальный баланс

Основное уравнение:

`I_end = I_start + Q_delivered - Losses - Q_served`

Потери:

`Losses = Throughput × loss_rate`

В модели потери начисляются один раз на валовое поступление в день; на остаток запаса повторно не начисляются.

Дефицит не моделируется отрицательным запасом:

`Shortage = max(0, Demand - Served)`

Уровень обслуживания:

`SL = Served / Demand`, а при нулевом спросе явно задаётся `SL = 1`.

Модель дополнительно хранит `balance_residual`, что позволяет механически проверять соблюдение материального баланса по каждому году.

### 4.3 Critical demand

`demand_critical ⊆ demand_total`.

Выдача устроена так:

1. сначала обслуживается critical;
2. затем оставшийся запас идёт на non-critical demand;
3. `served_total` уже включает critical и не складывается с ним второй раз.

Контрольные V02 и V09 предназначены именно для проверки этой семантики.

### 4.4 Reservation и take-or-pay

Take-or-pay:

`Q_pay = max(Q_order, take_or_pay_share × Q_reserved_period)`

Переменная плата:

`VariablePayment = Price × Q_pay`

Резерв мощности:

`ReservationPayment = rate × annual_reserved_capacity × period_fraction`

V03/V04/V05 проверяют, что take-or-pay не начисляется второй раз и что reservation prorates по доле доступного периода.

### 4.5 45-дневный резерв

`ReserveRequired = AnnualTotalDemand × 45 / 365`

В Result отдельно присутствуют:

- `reserve_stock_at_check` — физический запас;
- `reserve_emergency_equivalent` — эквивалент Emergency reserve;
- `reserve_covered` — сумма покрытия;
- `RESERVE_45D_SHORT` — количественный недобор.

Таким образом, контрактный Emergency reserve не превращается в физический запас. Он считается только как отдельный эквивалент с учётом мощности и доступности канала.

### 4.6 Discounting

`PV = CF / (1 + r)^(year - base_year)`

В текущей конфигурации:

- `discount_rate = 0.05`;
- `discount_base_year = 2035`;
- денежные значения трактуются как млн у.е. в ценах 2035 г.

Ставка 5% прямо помечена в коде как TEAM_ASSUMPTION и не должна подаваться в защите как внешний установленный факт без источника.

### 4.7 Стрессовая поставка

`ActualDelivery = PlannedDelivery × ActualShare`

Для обязательного стресса D:

- 2038: 55% плана;
- 2039: 75% плана.

Сценарий дополнительно задаёт:

- demand × 1.15 в 2038–2040;
- price A/B × 1.25 в 2038–2039;
- loss ceiling 2% в 2038–2040.

Сценарии не объединяются молча: `combine()` вызывает `ScenarioConflict`, если два overlay изменяют один и тот же параметр без явного правила.

## 5. Расчётное ядро

### 5.1 `fuel_model/model.py`

Основные сущности:

- `DemandRow` — спрос по году;
- `Source` — источник топлива;
- `StorageMode` — режим хранения;
- `InvestmentOption` — вариант инвестиции;
- `Constraints` — требования кейса;
- `Assumptions` — TEAM_ASSUMPTION;
- `Case` — весь входной контур;
- `Plan` — решение оператора;
- `Scenario` — наложение сценария;
- `Result` — годовая физика, затраты, KPI, violations и supply schedule.

### 5.2 `loader.py`

Загрузчик поддерживает текущие таблицы:

- `demand.csv`;
- `supply_sources.csv`;
- `storage_options.csv`;
- `investment_options.csv`;
- `constraints.csv`;
- `configs/source_roles.json`;
- `configs/assumptions.json`.

Кроме того, loader допускает альтернативные имена файлов и исходный organizer-format. Это сделано для уменьшения ручной перепаковки исходных таблиц.

### 5.3 `resolve.py`

Преобразует решения `Plan` в даты:

- начало поставок источников;
- ввод инвестиционных опций;
- дни CAPEX-платежей;
- активный режим хранения.

Для C используется семантика `build`; для D — `post_commissioning`; остальные каналы по умолчанию используют `order`.

### 5.4 `checks.py`

Разделены две группы:

**Плановые проверки:** мощности, резерв, доступность, инвестиционные сроки, Emergency streak.

**Результатные проверки:** service level, 45-day reserve, stress loss ceiling, storage overflow, CAPEX limits.

Каждый `Violation` имеет:

`code, severity, year, subject, value, limit, excess, message`.

Это непосредственно соответствует требованию критериев показывать год, величину и причину нарушения.

### 5.5 `engine.py`

`evaluate(case, plan, scenario)` выполняет полный расчёт:

1. validate input;
2. resolve dates and availability;
3. build delivery schedule;
4. run daily inventory loop;
5. calculate costs;
6. check constraints;
7. build KPI and Result.

`Result.meta` содержит `engine_version`, `input_version`, horizon, units и assumptions.

## 6. Инвестиционная логика

`fuel_model/investments.py` является **единственной канонической точкой построения стандартного investment schedule**.

`build_investment_decision()`:

- выбирает первый допустимый год этапов;
- ставит этапы в первый месяц выбранного года;
- применяет min/max build boundary через `lead_time_choice`;
- учитывает `earliest_in_service_year`;
- отбрасывает ввод за пределами горизонта.

Один и тот же builder используется:

`defaults API → frontend` и `optimizer → candidate plan`.

Это устраняет расхождение UI и оптимизатора, которое раньше могло возникать при ручном формировании schedule.

## 7. Оптимизатор

### 7.1 Статус метода

Оптимизатор **эвристический**. Он явно предупреждает, что глобальный оптимум математически не гарантируется.

### 7.2 Алгоритм

1. Перебор инвестиционных комбинаций.
2. Для текущего кейса — полный power set из 8 комбинаций.
3. Для каждой комбинации строится canonical investment schedule.
4. При пустом supply-plan создаётся greedy seed.
5. Выполняются repair passes:
   - reserve repair;
   - storage overflow repair;
   - service shortage repair;
   - benchmark reallocation.
6. Затем выполняется coordinate descent по годовым заказам.
7. Кандидат принимается только при улучшении лексикографического score.

### 7.3 Score

Приоритеты:

1. число HARD-нарушений;
2. critical shortage;
3. total shortage;
4. reserve gap;
5. число benchmark misses;
6. total cost;
7. PV cost.

Это важно для интерпретации результата: минимальная номинальная цена не является первым критерием выбора.

### 7.4 Investment frontier

`CandidateSummary` хранит:

- набор инвестиций;
- статус кандидата;
- причину отклонения;
- CAPEX total;
- CAPEX through deadline;
- score;
- scenario metrics по каждому сценарию;
- selected flag.

В веб-контуре эти точки отображаются как CAPEX ↔ service level и таблица кандидатов.

## 8. Сценарии и sensitivity

### Встроенные сценарии

- `BASE` — контрольный сценарий;
- `MANDATORY_STRESS` — обязательный stress;
- `LOW_DEMAND` — контрольная чувствительность;
- `HIGH_DEMAND` — контрольная чувствительность.

### Исследовательские функции

`sceanarios.py` поддерживает:

- `price_shock()`;
- `demand_shock()`;
- `delivery_shock()`;
- `combine()`.

`analysis.py` поддерживает:

- `compare_scenarios()`;
- `sweep()` для одномерной чувствительности.

### Что реально доступно сейчас

Модель может исследовать чувствительность в Python, но текущий UI не содержит отдельного экрана для задания диапазонов и построения чувствительности. `/api/optimize` принимает только зарегистрированные scenario IDs, а встроенные scenarios ограничены набором `BASE/MANDATORY_STRESS/LOW_DEMAND/HIGH_DEMAND`.

Для конкурсной документации следует подготовить отдельную таблицу:

| Параметр | База | Диапазон | Метрика | Порог |
|---|---:|---:|---|---|
| Demand multiplier | 1.00 | например, x0.9…x1.2 | shortage / SL / PV cost | первый год нарушения |
| Price multiplier A/B | 1.00 | сценарный диапазон | PV cost | смена альтернативы |
| D delivery share | 1.00 | 0.5…1.0 | shortage / service | нарушение 99% |
| Storage loss rate | mode coefficient | вокруг 1.2–4.5% | loss / storage feasibility | превышение 2% |

Диапазоны в этой таблице являются **форматом отчёта**, а не фактически выполненными испытаниями этого снимка репозитория.

## 9. Контрольные и интеграционные тесты

### 9.1 V01–V10

Reference tests покрывают:

| Case | Проверка |
|---|---|
| V01 | material balance |
| V02 | shortage без отрицательного inventory |
| V03 | take-or-pay minimum |
| V04 | отсутствие double-counting take-or-pay |
| V05 | reservation proration |
| V06 | losses once on throughput |
| V07 | 45-day reserve |
| V08 | capacity exceeded |
| V09 | critical demand nested in total |
| V10 | stress delivery без двойного reliability |

Reference values находятся отдельно от implementation formulas, что полезно для воспроизводимости.

### 9.2 Real-case tests

`fuel_model/test_real_case.py` проверяет:

- загрузку горизонта 2035–2040;
- источники A–E;
- storage BASE/ZBO;
- инвестиции EARTH_NEW/LUNAR_ISRU/ZBO;
- constraints;
- source roles;
- работу optimizer на BASE;
- работу optimizer на BASE + MANDATORY_STRESS;
- отсутствие storage overflow в stress;
- полный frontier из 8 комбинаций;
- ровно один selected candidate.

### 9.3 Web integration tests

`tests/test_web_api.py` проверяет:

- `/api/health`;
- `/api/defaults`;
- `/api/calculate`;
- `/api/optimize`;
- `/api/frontier`;
- одинаковый investment schedule в API и optimizer;
- сохранение явных investment decisions;
- zero-filled web template как empty Plan;
- выдачу frontend assets;
- rejection плохого scenario/plan;
- round-trip Plan JSON.

### 9.4 CI на текущем коммите

На commit `9618841a...` workflow `web integration` выполняет:

- install dependencies — success;
- `pytest tests/test_web_api.py` — success;
- `pytest tests/test_reference_cases.py` — success;
- `node --check frontend/app.js` — **failure**;
- Docker health smoke test — skipped из-за предыдущего failure.

Причина видна непосредственно в текущем `frontend/app.js`: в `chartSvg()` между двумя инструкциями присутствует литеральная последовательность `\n` после `const rawMax...`, а не обычный перевод строки. Это текущий дефект снимка ветки; в рамках этого документа он не исправлялся.

## 10. Веб-интерфейс

### 10.1 Вкладки

**Plan**

- годовые orders по A–E;
- contract reserve;
- investment selection;
- initial stock;
- BASE / MANDATORY_STRESS toggle.

**Dashboard**

- FEASIBLE / CHECK;
- PV COST;
- CAPEX;
- SHORTAGE;
- MIN SL TOTAL;
- MIN SL CRITICAL;
- inventory chart;
- CAPEX chart;
- yearly table;
- violations.

**Investment frontier**

- CAPEX ↔ MIN SL BASE chart;
- table всех frontier candidates;
- selected candidate marker.

**Advanced / JSON**

- Plan JSON;
- форматирование JSON;
- применение JSON;
- последний Result JSON.

### 10.2 Канонический API

| Method | Endpoint | Назначение |
|---|---|---|
| GET | `/api/health` | состояние API, engine, years, sources, storage, investments |
| GET | `/api/defaults` | input defaults, Plan template, canonical investment schedules, scenarios |
| POST | `/api/calculate` | прямой расчёт одного Plan в одном Scenario |
| POST | `/api/optimize` | оптимизация по переданному набору Scenario |
| POST | `/api/frontier` | optimization + frontier points |

### 10.3 Ошибки

Валидация выполняется в `fuel_model.validation`. Ошибки называются по полю и коду:

- UNKNOWN_SOURCE;
- YEAR_OUT_OF_HORIZON;
- NOT_A_NUMBER;
- NEGATIVE_VALUE;
- UNKNOWN_OPTION;
- STAGE_COUNT_MISMATCH;
- DATE_OUT_OF_HORIZON;
- DATE_ORDER;
- BAD_MULTIPLIER;
- BAD_SHARE.

FastAPI возвращает сообщение как HTTP 400, а UI выводит его в блоке сообщения.

## 11. Запуск

### Windows

```text
start_local.bat
```

или:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
python run_local.py
```

После запуска:

`http://127.0.0.1:8000`

### Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python run_local.py
```

### Docker

```bash
docker build -t kosmokontur-web .
docker run --rm -p 8000:8000 kosmokontur-web
```

Dockerfile запускает `uvicorn backend.api:app` на 8000.

## 12. Сохранение и выгрузка

### Что есть

`Plan` поддерживает:

- `to_dict()`;
- `from_dict()`;
- `save(path)`;
- `load(path)`.

CLI `fuel_model/run.py` поддерживает `--export` и генерирует CSV:

- yearly;
- costs;
- sources;
- violations;
- supply_schedule;
- inventory_trace;
- kpis.

### Чего нет в текущем web-контуре

- кнопки Save Plan;
- списка ранее сохранённых web plans;
- Open/Reopen из UI;
- XLSX export;
- отдельного `/api/export`;
- хранения сценариев и результатов в persistent DB/storage.

Поэтому критерий 20 закрыт только на уровне Python/CLI, но не полностью как операторская функция веб-системы.

## 13. Конкурсная матрица готовности

Ниже приведена не оценка баллов, а фактическая готовность текущего репозитория к предмету проверки.

| № | Критерий | Состояние | Ключевое доказательство | Основной пробел |
|---:|---|---|---|---|
| 1 | Материальный баланс | **Сильно закрыт** | `formulas.py`: `closing_inventory`, `serve_demand`, `shortage`, `combined_total_demand`; `engine.py` ведёт суточный баланс и `balance_residual`; V01, V02, V09 проверяют контрольные векторы. | Для жюри нужны контрольные результаты из повторного запуска и явное сопоставление годовых строк с выгрузкой. |
| 2 | Мощности и сроки поставок | **Закрыт в расчётном ядре** | `resolve.py` рассчитывает доступность и lead time; `check_plan_rules` проверяет CAPACITY_EXCEEDED, ORDER_EXCEEDS_RESERVED, SOURCE_NOT_AVAILABLE; `Result.yearly.sources` разделяет order / planned_delivery / actual_delivery. | Важно в защите показать, что Emergency reserve не является физическим запасом, а учитывается только как подтверждённый эквивалент с учётом доступности. |
| 3 | Экономические расчёты | **Закрыт в модели; обоснование допущений требует документа** | CAPEX, procurement, take-or-pay, reservation, holding cost, fixed OPEX и discounting считаются в `engine.py`; V03/V04 проверяют take-or-pay без двойного учёта. Выручка не моделируется. | `discount_rate=5%` помечен как TEAM_ASSUMPTION и требует внешнего обоснования. |
| 4 | Ограничения стандартного плана | **Закрыт в ядре** | Годовые service level, reserve, storage, CAPEX, investment timing, contract limits и Emergency streak проверяются по годам; нарушения имеют год, величину, лимит и код. | В документации защиты стоит показать хотя бы один выполнимый и один намеренно нарушенный пример. |
| 5 | Проверка и воспроизводимость | **Сильно закрыт по модели; текущий web-CI не зелёный** | Есть V01–V10, organizer reference vectors, deterministic optimizer test, web integration tests. На последнем коммите web-integration запускает оба набора тестов успешно, но падает на `node --check frontend/app.js`. | Для финальной сдачи нужен зелёный CI либо зафиксированное объяснение текущего синтаксического дефекта. |
| 6 | Логика архитектуры расчёта | **Закрыт** | Путь `CSV/JSON → Case → Plan → Scenario → validate → resolve → physics → costs → checks → Result → FastAPI → UI` прослеживается по модулям; `input_fingerprint` записывается в Result. | Нужна единая финальная схема архитектуры в управленческой записке. |
| 7 | Методы и научные источники | **Частично закрыт** | В коде явно названы assumptions и есть ссылка на синтетические reference cases организатора. Однако отдельного реестра научных/технических источников с привязкой к формулам нет. | Нужно отдельно оформить источники и границы применимости параметров; особенно discount rate, storage loss assumptions и lead-time semantics. |
| 8 | Сравнение альтернатив | **Закрыт расчётным контуром; объяснение стратегии надо вынести в документ** | `optimizer.py` перебирает до 2^3=8 инвестиционных комбинаций для текущего кейса; `CandidateSummary` хранит CAPEX и метрики BASE/STRESS; `/api/frontier` отдаёт пространство кандидатов. | Нарративный выбор должен объяснить стоимость горизонта, сервис и гибкость; интерфейс сам по себе этого не доказывает. |
| 9 | Инвестиции и контракты | **Закрыт в модели** | `investments.py` — единый builder; API и optimizer используют один и тот же график. Кейс-инвестиции и CAPEX-лимиты встроены; stage dates и in-service сохраняются в Plan. | Финансирование как отдельный cash-flow блок не выделен; дорожная карта присутствует в виде investment decisions. |
| 10 | Обязательный стрессовый сценарий | **Закрыт** | `mandatory_stress()` задаёт x1.15 demand в 2038–2040, x1.25 цены A/B в 2038–2039, delivery share D=55%/75%, loss ceiling 2%. Комбинация с HIGH_DEMAND не выполняется автоматически. | В защите нужно показать фактический BASE vs STRESS результат для одного и того же Plan. |
| 11 | Анализ чувствительности | **Частично закрыт** | `analysis.sweep()` и LOW/HIGH_DEMAND plus `price_shock`, `demand_shock`, `delivery_shock` поддерживают одномерные исследования. Но отдельного UI/готового отчёта чувствительности и явного поиска порога нет. | Нужна таблица диапазонов параметров и точек нарушения/смены альтернатив. |
| 12 | Методики и протоколы тестов | **Частично закрыт** | Есть unit, reference, real-case и web integration tests; CI запускает их. Случайные испытания и seed не используются. Отдельного протокола испытаний как документа нет. | Нужно вынести протокол: вход → шаги → метрики → ожидаемый результат → критерий прохождения. |
| 13 | Работа плана в стрессе | **Закрыт по вычислению, частично по доказательству эффекта решений** | Optimizer оценивает BASE + STRESS одним score; UI показывает оба сценария и frontier. | Для защиты нужны численные последствия стресса и комментарий по обязательствам/реакции. |
| 14 | Реестр ключевых рисков | **Не реализован как отдельный артефакт** | В модели есть события/параметры для price, demand, delivery, loss, lead time, CAPEX и storage. Но отдельного `risk register` с периодом, ответственным и зависимостями нет. | Нужен отдельный реестр рисков. |
| 15 | Количественная оценка последствий | **Частично** | Сценарные функции позволяют численно менять цену, спрос и фактическую поставку; Result показывает топливо, service, shortage, costs и сроки. Вероятности/распределения не заданы. | Нужна явная связка risk event → parameter change → consequence range. |
| 16 | Меры и остаточный риск | **Не реализован как отдельный артефакт** | В optimizer есть механизмы технического ремонта плана (reserve/service/storage), но это не оформлено как risk mitigation register с cost of measure и residual risk. | Нужна отдельная таблица мер, стоимости и остаточного риска. |
| 17 | Интересы и показатели сторон | **Не реализован как отдельный артефакт** | Модель технически содержит операторский Plan, источники A–E, critical/commercial demand и CAPEX, но stakeholder model/obligations/risk allocation отсутствует. | Нужна stakeholder matrix с KPI, обязательствами, кто платит и кто несёт последствия. |
| 18 | Адаптация к изменению рисков | **Не реализован как отдельный артефакт** | Сценарии можно комбинировать через `combine()` и сравнивать, но компромиссы между сторонами и изменение их интересов не моделируются. | Нужно документировать адаптацию решения при изменении ключевых рисков. |
| 19 | Функции оператора и доступ | **Закрыт** | UI позволяет менять orders, reserve, investments, initial stock, включать STRESS, запускать optimize, смотреть BASE/STRESS/frontier и Advanced JSON; нарушения показываются с годом/величиной/причиной; ошибки возвращаются через API. | Текущее состояние UI пригодно как операторский прототип; отдельные функции sensitivity/risk не входят в критерий 19 напрямую. |
| 20 | Сохранение, выгрузка и развитие | **Частично** | `Plan.save/load` и CLI `--export` дают JSON/CSV на уровне Python; `export_result()` делает yearly/costs/sources/violations/supply_schedule/inventory_trace/kpis CSV. В web UI нет save/reopen и нет XLSX endpoint. | Это один из самых заметных документируемых пробелов. |


Критерии распределены по тем же блокам, что и официальный лист: модель 1–5, архитектура 6–9, стресс 10–13, риски 14–16, stakeholders 17–18, digital contour 19–20.

## 14. Что уже можно демонстрировать жюри

### Модель

- материальный баланс по суткам и годам;
- critical demand как подмножество total;
- losses один раз на throughput;
- 45-day reserve;
- take-or-pay и reservation;
- CAPEX/OPEX/procurement/holding;
- date resolution и lead times;
- yearly violations с value/limit/excess.

### Стратегия

- BASE vs MANDATORY_STRESS;
- инвестиционная frontier из 8 комбинаций;
- canonical investment schedules;
- heuristic optimizer и его score;
- deterministic repeated-run behavior на synthetic case.

### Цифровой контур

- редактирование Plan;
- пересчёт;
- stress toggle;
- dashboard;
- frontier;
- JSON contract;
- понятные validation errors.

## 15. Что сейчас является основным конкурсным долгом

### 15.1 Документационные артефакты

1. **Источники и методики.** Для каждого параметра/метода — внешний источник, формула/алгоритм, место использования, границы применимости.
2. **Sensitivity report.** Диапазоны, точки запуска, метрики и пороги.
3. **Risk register.** Событие, причина, период, параметры, зависимости, owner.
4. **Risk consequence table.** Quantitative consequences.
5. **Mitigation / residual risk table.** Стоимость меры, effect, residual risk.
6. **Stakeholder matrix.** Operator, critical/commercial consumers, fuel/launch suppliers, financing side.
7. **Management memo.** Нормализованный нарратив выбора плана, а не только цифры dashboard.

### 15.2 Технические пробелы web-контура

1. Исправить текущую syntax-check проблему `frontend/app.js`.
2. Добавить web save/reopen.
3. Добавить CSV/XLSX export из интерфейса или API.
4. Явно вывести единицы и параметры в экспортных файлах.
5. При необходимости добавить research scenario input/sensitivity UI поверх уже существующих Python APIs.

Эти пункты являются **описанием текущего состояния и требуемых конкурсных материалов**, а не изменениями репозитория в рамках этой работы.

## 16. Готовый протокол демонстрации

1. Открыть `/` и дождаться `API: online`.
2. В Plan показать годы 2035–2040 и каналы A–E.
3. Показать investment options и canonical schedules через `/api/defaults`/UI.
4. Нажать `Запустить оптимизацию` с BASE + MANDATORY_STRESS.
5. В Dashboard показать для BASE: PV cost, CAPEX, shortage, SL total, SL critical.
6. Переключить STRESS и показать те же KPI.
7. Открыть Investment frontier и показать все evaluated candidates и selected candidate.
8. Показать одно намеренное нарушение через Advanced JSON/Plan, чтобы увидеть год, величину и причину.
9. Показать reference tests V01–V10 и real-case tests как доказательство воспроизводимости.
10. Отдельно показать CSV export из CLI и честно указать текущий статус web save/XLSX.

## 17. Минимальный состав конкурсной папки

```text
01_management_memo.pdf
02_model_documentation.pdf
03_stress_and_sensitivity.pdf
04_risk_register.xlsx
05_stakeholder_matrix.pdf
06_control_test_protocol.pdf
07_exports/
   base_yearly.csv
   base_costs.csv
   base_sources.csv
   stress_yearly.csv
   stress_costs.csv
   stress_violations.csv
08_code/
   repository snapshot / branch reference
09_runbook.md
```

## 18. Ограничения текущего прототипа

- В оптимизаторе не гарантируется глобальный optimum.
- Discount rate является team assumption.
- Reliability profiles в BASE хранятся как metadata, но не применяются как независимый множитель.
- Sensitivity API для произвольных исследовательских scenarios не экспонирован в текущем web UI.
- Risk/stakeholder layers пока представлены в расчётном коде лишь частично и не оформлены отдельными конкурсными артефактами.
- Web save/reopen и XLSX отсутствуют.
- На последнем commit web-integration CI останавливается на `node --check frontend/app.js`.

## 19. Итоговое состояние

Текущая ветка уже представляет собой рабочую архитектуру из трёх уровней:

**данные кейса → расчётное ядро → операторский цифровой контур.**

Наиболее зрелыми частями являются материальный баланс, контрактная/инвестиционная логика, единый investment schedule, обязательный stress, optimizer frontier, контрольные reference vectors и FastAPI/UI интеграция.

Наименее закрытыми относительно конкурсных требований остаются не базовые формулы, а **сопроводительные доказательства решения**: научные источники и допущения, sensitivity report, risk register и mitigation, stakeholder layer, а также полное web-сохранение/выгрузка.

Эта граница важна: официальный критерий прямо указывает, что оценивается подтверждённый результат и воспроизводимость, а не количество функций или эффектность интерфейса.

## 20. Основные файлы-источники документации

- `fuel_model/model.py`
- `fuel_model/formulas.py`
- `fuel_model/engine.py`
- `fuel_model/checks.py`
- `fuel_model/validation.py`
- `fuel_model/resolve.py`
- `fuel_model/investments.py`
- `fuel_model/scenarios.py`
- `fuel_model/analysis.py`
- `fuel_model/optimizer.py`
- `fuel_model/run.py`
- `data/case_input/*.csv`
- `configs/assumptions.json`
- `configs/source_roles.json`
- `backend/api.py`
- `backend/services/optimize.py`
- `backend/services/frontier.py`
- `frontend/index.html`
- `frontend/app.js`
- `frontend/styles.css`
- `tests/test_reference_cases.py`
- `tests/test_web_api.py`
- `fuel_model/test_real_case.py`
- `.github/workflows/web-integration.yml`
- `.github/workflows/optimizer-smoke.yml`

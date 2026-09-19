# Топливный космоконтур 2035

Веб-приложение для расчёта и оптимизации топливного контура на горизонте 2035–2040 годов.

Архитектура проекта:

```text
Web UI
  │
  │ HTTP / JSON
  ▼
FastAPI
  │
  ▼
fuel_model
  │
  ├── расчёт материального баланса
  ├── проверка ограничений
  ├── расчёт затрат
  ├── сценарии BASE / MANDATORY_STRESS
  └── эвристическая оптимизация
```

## 1. Доступ к проекту

Основная рабочая ветка:

```text
feature/web-app
```

Репозиторий:

```text
https://github.com/Fenzyyy/kosmokontur/tree/feature/web-app
```

Для запуска веб-приложения Python-движок должен работать вместе с FastAPI. Статический frontend сам по себе расчётный движок не запускает.

---

## 2. Самый простой способ запуска на Windows

В корне репозитория выполните:

```powershell
python run_local.py
```

или запустите файл:

```text
start_local.bat
```

После запуска откройте:

```text
http://127.0.0.1:8000
```

FastAPI одновременно отдаёт:

- веб-интерфейс;
- API;
- статические frontend-файлы.

---

## 3. Запуск через виртуальное окружение

Рекомендуемый вариант:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
python run_local.py
```

После запуска:

```text
http://127.0.0.1:8000
```

---

## 4. Запуск на Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python run_local.py
```

После запуска:

```text
http://127.0.0.1:8000
```

---

## 5. Проверка API

После запуска backend доступны основные endpoint'ы:

```text
GET  /api/health
GET  /api/defaults
POST /api/calculate
POST /api/optimize
POST /api/frontier
```

### Health check

Откройте:

```text
http://127.0.0.1:8000/api/health
```

В ответе должна присутствовать информация о:

- состоянии API;
- версии `fuel_model`;
- горизонте расчёта;
- источниках поставок;
- вариантах хранения;
- инвестиционных опциях.

---

## 6. Веб-интерфейс

Главная страница:

```text
http://127.0.0.1:8000/
```

В интерфейсе доступны четыре основных раздела. На странице Plan также доступны сохранение/открытие JSON-плана и экспорт рассчитанного сценария в CSV:

### Plan

Редактирование:

- годовых поставок по каналам;
- резервирования мощности;
- инвестиционных решений;
- начального запаса;
- выбора BASE / MANDATORY STRESS.

### Dashboard

Показывает результаты расчёта:

- PV Cost;
- CAPEX;
- shortage;
- минимальный service level;
- годовую физику;
- запас топлива;
- CAPEX по годам;
- нарушения и проверки.

### Investment frontier

Показывает инвестиционные кандидаты, рассчитанные через существующий `fuel_model`.

Для каждого кандидата доступны:

- состав инвестиций;
- CAPEX;
- service level;
- shortage;
- статус проверки;
- отметка выбранного оптимизатором кандидата.

### Save / Open / Export

Кнопки на странице Plan позволяют:

- сохранить текущий Plan как JSON;
- открыть ранее сохранённый JSON-план;
- выгрузить рассчитанный текущий сценарий в CSV с KPI, годовой физикой и нарушениями.

### Advanced / JSON

Позволяет:

- посмотреть текущий `Plan`;
- отредактировать JSON;
- применить JSON обратно в модель;
- посмотреть последний `Result JSON`.

---

## 7. Где находятся данные

Исходные данные кейса находятся в:

```text
data/case_input/
```

Основные файлы:

```text
demand.csv
supply_sources.csv
storage_options.csv
investment_options.csv
constraints.csv
```

Конфигурационные допущения:

```text
configs/assumptions.json
configs/source_roles.json
```

По умолчанию backend загружает именно эти каталоги.

Также можно указать другие каталоги через переменные окружения:

```text
FUEL_DATA_DIR
FUEL_CONFIG_DIR
```

Например:

```powershell
$env:FUEL_DATA_DIR="C:\cases\data"
$env:FUEL_CONFIG_DIR="C:\cases\configs"
python run_local.py
```

---

## 8. Как frontend получает доступ к backend

По умолчанию frontend использует текущий origin:

```javascript
const API = window.ENGINE_API_URL || "";
```

Поэтому при запуске через FastAPI специальная настройка не требуется:

```text
http://127.0.0.1:8000
        │
        ├── /
        ├── /app.js
        ├── /styles.css
        └── /api/*
```

Если frontend размещён отдельно, например через GitHub Pages, нужно указать URL backend перед загрузкой `app.js`:

```html
<script>
  window.ENGINE_API_URL = "https://YOUR-BACKEND";
</script>
<script src="app.js"></script>
```

Тогда схема доступа становится:

```text
GitHub Pages
    │
    │ HTTPS / JSON
    ▼
Python FastAPI backend
    │
    ▼
fuel_model
```

---

## 9. GitHub Pages

GitHub Pages предназначен для статического frontend.

Он может публиковать:

```text
index.html
app.js
styles.css
```

Но Python-движок `fuel_model` на GitHub Pages не запускается.

Поэтому для полноценной работы необходимо:

1. разместить frontend на GitHub Pages или другом static hosting;
2. развернуть FastAPI backend отдельно;
3. указать URL backend через `window.ENGINE_API_URL`.

Пример:

```html
<script>
  window.ENGINE_API_URL = "https://example-backend.example.com";
</script>
<script src="app.js"></script>
```

---

## 10. CORS

Backend поддерживает CORS.

Используется переменная:

```text
ALLOW_ORIGINS
```

По умолчанию допускается:

```text
*
```

Для отдельного production-развёртывания рекомендуется указывать конкретный origin, например:

```text
ALLOW_ORIGINS=https://example.github.io
```

---

## 11. Docker

В репозитории имеется `Dockerfile`.

Сборка:

```bash
docker build -t kosmokontur-web .
```

Запуск:

```bash
docker run --rm -p 8000:8000 kosmokontur-web
```

После запуска:

```text
http://127.0.0.1:8000
```

Контейнер запускает:

```text
uvicorn backend.api:app --host 0.0.0.0 --port 8000
```

---

## 12. Доступ к расчётному движку без сайта

Основная модель находится в:

```text
fuel_model/
```

Центральный контракт:

```text
Case + Plan + Scenario → Result
```

Основная функция расчёта:

```python
from fuel_model.engine import evaluate
```

Загрузка кейса:

```python
from fuel_model.loader import load_case
```

Сценарии:

```python
from fuel_model.scenarios import get
```

Пример:

```python
from fuel_model.loader import load_case
from fuel_model.engine import evaluate
from fuel_model.model import Plan
from fuel_model.scenarios import get

case = load_case("data/case_input", "configs")

plan = Plan.from_dict({
    "plan_id": "demo",
    "name": "Demo",
    "orders": {},
    "reserved": {},
    "initial_stock": [],
    "investments": {}
})

result = evaluate(
    case,
    plan,
    get("BASE")
)

print(result.kpis)
```

---

## 13. Оптимизация

Оптимизатор находится в:

```text
fuel_model/optimizer.py
```

Он:

1. перебирает инвестиционные комбинации;
2. строит стартовый plan;
3. использует общий `investment builder`;
4. проверяет кандидатов через `fuel_model.engine.evaluate()`;
5. восстанавливает допустимость по резерву, storage и обеспечению;
6. выполняет локальный поиск;
7. сравнивает кандидатов по лексикографическому score.

Важно:

> Оптимизатор является эвристическим. Доказательство глобального оптимума не заявляется.

---

## 14. Единый investment schedule

Формирование стандартного инвестиционного графика находится в:

```text
fuel_model/investments.py
```

Основная функция:

```python
build_investment_decision(...)
```

Именно этот механизм используется и optimizer, и web API.

Это означает, что интерфейс не содержит отдельной копии инвестиционной логики.

---

## 15. Тесты

Основные тесты:

```text
fuel_model/test_control_cases.py
fuel_model/test_optimizer.py
fuel_model/test_real_case.py
tests/test_reference_cases.py
tests/test_web_api.py
```

Контрольные векторы V01–V10 находятся в:

```text
tests/reference_cases/
```

Они проверяют, в частности:

- материальный баланс;
- shortage;
- take-or-pay;
- отсутствие двойного учёта take-or-pay;
- prorating reservation;
- потери;
- 45-дневный резерв;
- превышение мощности;
- вложенность критического спроса в общий;
- stress delivery.

---

## 16. CI

В репозитории находятся workflows:

```text
.github/workflows/optimizer-smoke.yml
.github/workflows/web-integration.yml
```

Web integration workflow проверяет:

- web API;
- reference vectors;
- синтаксис frontend JavaScript;
- Docker build;
- health endpoint;
- отсутствие внешних runtime CDN-зависимостей.

Текущее состояние CI необходимо проверять непосредственно в GitHub Actions для актуального коммита ветки.

---

## 17. Где смотреть расчётные результаты

CLI позволяет получить результат непосредственно из `fuel_model`.

Пример:

```bash
python -m fuel_model.run \
  --plan path/to/plan.json \
  --scenario BASE
```

Сравнение нескольких сценариев:

```bash
python -m fuel_model.run \
  --plan path/to/plan.json \
  --compare BASE,MANDATORY_STRESS,LOW_DEMAND,HIGH_DEMAND
```

Выгрузка результатов:

```bash
python -m fuel_model.run \
  --plan path/to/plan.json \
  --scenario BASE \
  --export results/
```

Экспорт CLI формирует CSV с:

- yearly;
- costs;
- sources;
- violations;
- supply schedule;
- inventory trace;
- KPI.

---

## 18. Рекомендуемый способ доступа для демонстрации

Для локальной демонстрации жюри:

```text
1. Клонировать репозиторий
2. Перейти в feature/web-app
3. Установить backend/requirements.txt
4. Запустить python run_local.py
5. Открыть http://127.0.0.1:8000
6. Проверить /api/health
7. Открыть Plan
8. Запустить оптимизацию
9. Перейти в Dashboard
10. Проверить BASE и MANDATORY STRESS
11. Открыть Investment frontier
12. При необходимости открыть Advanced / JSON
```

---

## 19. Важные ограничения прототипа

Текущий проект является расчётным прототипом.

В частности:

- optimizer является эвристическим;
- некоторые параметры являются командными допущениями и вынесены в `configs/`;
- результат модели следует интерпретировать в рамках заданных исходных данных и допущений;
- frontend не содержит отдельной копии физики расчёта;
- для удалённого frontend необходим отдельный доступный FastAPI backend.

Полное описание ограничений, модели, тестов и соответствия критериям находится в конкурсной документации проекта.

---

## 20. Основные точки входа

```text
backend/api.py                  FastAPI
backend/services/optimize.py   web → optimizer adapter
backend/services/frontier.py   investment frontier
fuel_model/engine.py           основное расчётное ядро
fuel_model/optimizer.py        оптимизатор
fuel_model/investments.py      единый investment schedule
fuel_model/scenarios.py        сценарии
fuel_model/loader.py           загрузка данных
fuel_model/validation.py       проверка ввода
fuel_model/checks.py           проверка ограничений
frontend/index.html            UI
frontend/app.js                frontend logic
frontend/styles.css            UI styles
run_local.py                   локальный запуск
Dockerfile                     контейнерный запуск
```

---

## 21. Краткая схема доступа

### Локально

```text
Browser
   │
   ▼
127.0.0.1:8000
   │
   ▼
FastAPI
   │
   ▼
fuel_model
```

### Через отдельный frontend

```text
Browser
   │
   ├──────────────► GitHub Pages / Static Hosting
   │
   └── HTTPS/JSON ► FastAPI Backend
                         │
                         ▼
                     fuel_model
```

Для полного расчётного функционала доступ к FastAPI backend обязателен.
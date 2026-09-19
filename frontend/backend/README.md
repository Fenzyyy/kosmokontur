# Backend adapter

Этот каталог не содержит копию расчётного ядра. Он только вызывает существующий пакет `fuel_model`.

## Структура

```text
kosmokontur/
├─ fuel_model/              # НЕ МЕНЯТЬ
├─ data/case_input/         # данные движка
├─ configs/                 # конфиги движка
├─ index.html
├─ app.js
├─ styles.css
└─ backend/
   ├─ api.py
   └─ requirements.txt
```

## Запуск из корня репозитория

Windows:

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r backend\requirements.txt
uvicorn backend.api:app --reload --host 0.0.0.0 --port 8000
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.api:app --reload --host 0.0.0.0 --port 8000
```

После запуска API доступен на `http://localhost:8000`.

Откройте `index.html` через локальный HTTP-сервер, а не `file://`.
Например:

```bash
python -m http.server 5500
```

Затем откройте `http://localhost:5500`.

Если backend размещён не на localhost, перед загрузкой `app.js` задайте:

```html
<script>
  window.ENGINE_API_URL = "https://ВАШ-BACKEND";
</script>
```

## Что важно

`fuel_model` не изменяется.

Сайт использует:

```text
UI
 ↓
native Plan JSON
 ↓
POST /api/calculate
 ↓
Plan.from_dict()
 ↓
fuel_model.engine.evaluate()
 ↓
Result
 ↓
JSON
 ↓
UI / charts
```

Графики строятся по фактическим `Result.yearly` и `Result.costs`, а не по формулам, переписанным в JavaScript.

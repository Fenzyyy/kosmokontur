# Топливный космоконтур — web interface

Готовая связка сайта с существующим `fuel_model`.

## Важная архитектура

GitHub Pages публикует статические HTML/CSS/JS-файлы и не запускает Python на сервере. Поэтому Python-движок должен работать отдельным API-сервисом. Это соответствует официальной модели GitHub Pages: Pages публикует статические файлы и не поддерживает серверные языки вроде Python.

```text
GitHub Pages
    index.html
    app.js
    styles.css
          │
          │ HTTP JSON
          ▼
Python API
    backend/api.py
          │
          ▼
    fuel_model
          │
          ▼
      Result JSON
```

## Что изменено

1. `app.js` больше не ожидает несуществующий `/api/defaults` на GitHub Pages.
2. API URL вынесен в `window.ENGINE_API_URL`.
3. План передаётся в нативном формате `Plan.from_dict()`.
4. Расчёт выполняется только через `fuel_model.engine.evaluate()`.
5. В браузере нет копии формул двигателя.
6. Таблица, график запаса и CAPEX строятся из фактического `Result`.
7. Ошибки валидации движка возвращаются пользователю.
8. Сам каталог `fuel_model` не изменяется.

## Развёртывание

Frontend можно положить в корень GitHub Pages.

Backend нужно развернуть отдельно на любом Python-хостинге.

После этого в `app.js` или перед ним задайте:

```html
<script>
  window.ENGINE_API_URL = "https://ВАШ-BACKEND";
</script>
```

По умолчанию локально используется:

```text
http://localhost:8000
```

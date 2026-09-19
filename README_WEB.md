# Web application

The repository now contains a first integrated web application over the existing fuel_model.

Architecture: frontend -> FastAPI -> backend services -> fuel_model.

Main endpoints: /api/health, /api/defaults, /api/calculate, /api/optimize, /api/frontier.

Local launch (Windows): double-click `start_local.bat`.

Local launch (any OS): `python -m pip install -r backend/requirements.txt` then `python run_local.py`.

Open http://127.0.0.1:8000. The application does not require an internet connection at runtime: frontend charts are rendered with native SVG and the calculation engine runs locally.

The frontend provides visual Plan editing, BASE/STRESS dashboard, investment frontier and Advanced JSON mode.

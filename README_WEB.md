# Web application

The repository now contains a first integrated web application over the existing fuel_model.

Architecture: frontend -> FastAPI -> backend services -> fuel_model.

Main endpoints: /api/health, /api/defaults, /api/calculate, /api/optimize, /api/frontier.

Local launch: pip install -r backend/requirements.txt && uvicorn backend.api:app --reload

Open http://localhost:8000.

The frontend provides visual Plan editing, BASE/STRESS dashboard, investment frontier and Advanced JSON mode.

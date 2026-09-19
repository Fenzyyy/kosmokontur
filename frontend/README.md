Web frontend for the Kosmokontur fuel-model engine.

Local mode: uvicorn backend.api:app --reload, then open http://localhost:8000.

The frontend uses Plan JSON as the API contract and renders BASE, MANDATORY STRESS, yearly physics, violations, and investment frontier.
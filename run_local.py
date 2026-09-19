"""Local launcher for the Kosmokontur web application.

Run from the repository root:
    python run_local.py
Then open http://127.0.0.1:8000
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn


if __name__ == "__main__":
    uvicorn.run(
        "backend.api:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
    )

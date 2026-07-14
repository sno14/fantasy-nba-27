"""Serve the web UI: FastAPI backend + the built React frontend, one process.

    python scripts/serve.py                # http://127.0.0.1:8787
    python scripts/serve.py --port 9000
    python scripts/serve.py --host 0.0.0.0 # expose on the LAN (home-server use)

Frontend development instead runs `npm run dev` in frontend/ (Vite proxies /api here).
If frontend/dist is missing, only the API (and /api/docs) is served — build it with
`npm run build` in frontend/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Serve the fantasy-nba web app.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--reload", action="store_true", help="Auto-reload on code changes (dev).")
    args = ap.parse_args()

    import uvicorn

    dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if not dist.exists():
        print("note: frontend/dist not found — serving the API only. "
              "Build the UI with `cd frontend && npm install && npm run build`.")
    uvicorn.run("fantasy_nba.api.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()

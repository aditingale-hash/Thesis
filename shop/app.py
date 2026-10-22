"""FastAPI application: HTML frontend at ``/`` and JSON API at ``/api``.

Run with ``uvicorn shop.app:app --port 8000``.
"""

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from shop import db, routes_api, routes_html

SESSION_COOKIE = "shop_session"

# No interactive docs / OpenAPI schema: the shop exposes only the pages and /api routes.
app = FastAPI(title="TechDesk Shop", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SHOP_SECRET_KEY", "thesis-prototype-fixed-secret"),
    session_cookie=SESSION_COOKIE,
    same_site="lax",
    https_only=False,
)
app.mount("/static", StaticFiles(directory=db.SHOP_DIR / "static"), name="static")
app.include_router(routes_api.router, prefix="/api")
app.include_router(routes_html.router)

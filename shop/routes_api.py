"""JSON API under ``/api``: the agent tool interface.

One route per service function (plus login, used by the runner only). Request
values are passed to ``service`` unchanged; this module contains no business
rules. Errors are returned as ``{"error": {"rule": ..., "message": ...}}`` with
the same message the HTML page shows.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from shop import db, service

router = APIRouter()


async def _body(request: Request) -> dict:
    """Return the JSON body as a dict (empty dict if missing or not an object)."""
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _call(func, *args) -> JSONResponse:
    """Run a service function on a fresh connection and convert the outcome to JSON."""
    conn = db.connect()
    try:
        return JSONResponse(func(conn, *args))
    except service.ShopError as e:
        return JSONResponse({"error": {"rule": e.rule, "message": e.message}}, status_code=e.status_code)
    finally:
        conn.close()


@router.post("/login")
async def login(request: Request):
    body = await _body(request)
    conn = db.connect()
    try:
        request.session["user_id"] = service.login(conn, body.get("username"), body.get("password"))
    except service.ShopError as e:
        return JSONResponse({"error": {"rule": e.rule, "message": e.message}}, status_code=e.status_code)
    finally:
        conn.close()
    return JSONResponse({"username": body.get("username")})


@router.get("/products")
def search_products(request: Request):
    p = request.query_params
    return _call(service.search_products, p.get("query"), p.get("category"), p.get("sort"))


@router.get("/products/{product_id}")
def get_product(product_id: str):
    return _call(service.get_product, product_id)


@router.get("/cart")
def get_cart(request: Request):
    return _call(service.get_cart, request.session.get("user_id"))


@router.post("/cart/items")
async def add_to_cart(request: Request):
    body = await _body(request)
    return _call(service.add_to_cart, request.session.get("user_id"), body.get("product_id"), body.get("quantity"))


@router.put("/cart/items/{product_id}")
async def update_cart_item(product_id: str, request: Request):
    body = await _body(request)
    return _call(service.update_cart_item, request.session.get("user_id"), product_id, body.get("quantity"))


@router.delete("/cart/items/{product_id}")
def remove_from_cart(product_id: str, request: Request):
    return _call(service.remove_from_cart, request.session.get("user_id"), product_id)


@router.post("/checkout")
def checkout(request: Request):
    return _call(service.checkout, request.session.get("user_id"))

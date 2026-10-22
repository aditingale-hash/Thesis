"""Server-rendered HTML frontend.

Form values are passed to ``service`` as raw strings; this module contains no
business rules. On success, cart operations redirect to the cart page (the API
returns the cart for the same operations). On error, the page the user acted on
is shown again with the core's message in the notice area at the top.
"""

from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from shop import db, service

router = APIRouter()
templates = Jinja2Templates(directory=db.SHOP_DIR / "templates")
templates.env.filters["eur"] = lambda value: f"{value:.2f} EUR"

PRODUCT_PHOTOS = db.SHOP_DIR / "static" / "products"


def _image_url(product: dict) -> str:
    """Product photo ``static/products/<id>.jpg`` if present, else the category illustration."""
    product_id = product.get("id", product.get("product_id"))
    if (PRODUCT_PHOTOS / f"{product_id}.jpg").exists():
        return f"/static/products/{product_id}.jpg"
    if "category" in product:
        return f"/static/icons/{_slug(product['category'])}.svg"
    return "/static/icons/product.svg"  # cart items carry no category


def _slug(category: str) -> str:
    return category.lower().replace(" ", "-")


templates.env.filters["image_url"] = _image_url
templates.env.filters["slug"] = _slug


def _page(request: Request, template: str, title: str, status_code: int = 200, error: str | None = None, **context):
    return templates.TemplateResponse(
        request, template, {"title": title, "error": error, **context}, status_code=status_code
    )


def _search_url(query: str | None, category: str | None, sort: str | None) -> str:
    params = {k: v for k, v in (("q", query), ("category", category), ("sort", sort)) if v}
    return "/search?" + urlencode(params) if params else "/search"


def _cart_view(request: Request, conn, template: str, title: str, error: service.ShopError | None = None):
    """Render the cart or checkout page (both show the cart), optionally with an error notice."""
    try:
        cart = service.get_cart(conn, request.session.get("user_id"))
    except service.ShopError as e:
        return _page(request, template, title, e.status_code, e.message, cart=None)
    if error:
        return _page(request, template, title, error.status_code, error.message, cart=cart)
    return _page(request, template, title, cart=cart)


@router.get("/login")
def login_form(request: Request):
    return _page(request, "login.html", "Log in")


@router.post("/login")
async def login(request: Request):
    form = await request.form()
    conn = db.connect()
    try:
        request.session["user_id"] = service.login(conn, form.get("username"), form.get("password"))
    except service.ShopError as e:
        return _page(request, "login.html", "Log in", e.status_code, e.message)
    finally:
        conn.close()
    return RedirectResponse("/", status_code=303)


@router.get("/register")
def register_form(request: Request):
    return _page(request, "register.html", "Create account")


@router.post("/register")
async def register(request: Request):
    form = await request.form()
    conn = db.connect()
    try:
        request.session["user_id"] = service.register(
            conn, form.get("username"), form.get("password"), form.get("password_repeat")
        )
    except service.ShopError as e:
        return _page(request, "register.html", "Create account", e.status_code, e.message,
                     username=form.get("username") or "")
    finally:
        conn.close()
    return RedirectResponse("/", status_code=303)


@router.get("/")
def start(request: Request):
    conn = db.connect()
    try:
        cats = service.categories(conn)
    finally:
        conn.close()
    links = [(c, _search_url(None, c, None), False) for c in cats]
    return _page(request, "start.html", "Home", query="", category_links=links)


@router.get("/search")
def search(request: Request):
    q, category, sort = (request.query_params.get(k) for k in ("q", "category", "sort"))
    conn = db.connect()
    try:
        cats = service.categories(conn)
        try:
            result = service.search_products(conn, q, category, sort)
        except service.ShopError as e:
            return _page(request, "results.html", "Search results", e.status_code, e.message,
                         query=q or "", result=None, category_links=[], sort_links=[])
    finally:
        conn.close()
    category_links = [("All categories", _search_url(result["query"], None, result["sort"]), result["category"] is None)]
    category_links += [(c, _search_url(result["query"], c, result["sort"]), c == result["category"]) for c in cats]
    sort_links = [
        (label, _search_url(result["query"], result["category"], key), key == result["sort"])
        for key, label in service.SORT_OPTIONS.items()
    ]
    return _page(request, "results.html", "Search results", query=result["query"], result=result,
                 category_links=category_links, sort_links=sort_links)


@router.get("/products/{product_id}")
def product(request: Request, product_id: str):
    conn = db.connect()
    try:
        p = service.get_product(conn, product_id)
    except service.ShopError as e:
        return _page(request, "product.html", "Product not found", e.status_code, e.message, product=None)
    finally:
        conn.close()
    return _page(request, "product.html", p["name"], product=p)


@router.post("/cart/add")
async def add_to_cart(request: Request):
    form = await request.form()
    conn = db.connect()
    try:
        service.add_to_cart(conn, request.session.get("user_id"), form.get("product_id"), form.get("quantity"))
    except service.ShopError as e:
        try:
            p = service.get_product(conn, form.get("product_id"))
        except service.ShopError:
            return _page(request, "product.html", "Product not found", e.status_code, e.message, product=None)
        return _page(request, "product.html", p["name"], e.status_code, e.message, product=p)
    finally:
        conn.close()
    return RedirectResponse("/cart", status_code=303)


@router.get("/cart")
def cart(request: Request):
    conn = db.connect()
    try:
        return _cart_view(request, conn, "cart.html", "Cart")
    finally:
        conn.close()


@router.post("/cart/update")
async def update_cart_item(request: Request):
    form = await request.form()
    conn = db.connect()
    try:
        service.update_cart_item(conn, request.session.get("user_id"), form.get("product_id"), form.get("quantity"))
    except service.ShopError as e:
        return _cart_view(request, conn, "cart.html", "Cart", e)
    finally:
        conn.close()
    return RedirectResponse("/cart", status_code=303)


@router.post("/cart/remove")
async def remove_from_cart(request: Request):
    form = await request.form()
    conn = db.connect()
    try:
        service.remove_from_cart(conn, request.session.get("user_id"), form.get("product_id"))
    except service.ShopError as e:
        return _cart_view(request, conn, "cart.html", "Cart", e)
    finally:
        conn.close()
    return RedirectResponse("/cart", status_code=303)


@router.get("/checkout")
def checkout_form(request: Request):
    conn = db.connect()
    try:
        return _cart_view(request, conn, "checkout.html", "Checkout")
    finally:
        conn.close()


@router.post("/checkout")
def checkout(request: Request):
    conn = db.connect()
    try:
        order = service.checkout(conn, request.session.get("user_id"))
    except service.ShopError as e:
        return _cart_view(request, conn, "checkout.html", "Checkout", e)
    finally:
        conn.close()
    return _page(request, "confirmation.html", "Order confirmed", order=order)

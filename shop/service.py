"""Application core of the shop.

ALL business rules (BR1-BR8) are enforced here and only here. The HTML routes
and the JSON API are thin adapters: they pass raw request values (strings from
forms, values from JSON bodies) to these functions unchanged and render the
returned dictionaries. Because both interfaces call the same functions with the
same raw values, they produce the same results and the same error messages.

Every function takes an open SQLite connection as first argument. ``user`` is the
user id stored in the session (``None`` if not logged in).

Returned dictionaries are exactly the fields the corresponding page shows:
- product summary (search results): id, name, category, price, rating, available, badge
- product detail: summary fields + stock, description
- cart: items (product_id, name, unit_price, quantity, line_total, available), total
- order: order_id, status, created, lines (product_id, name, quantity, unit_price, line_total), total
"""

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime, timezone

from shop import db

MAX_QTY = 10

SORT_OPTIONS = {
    "price_asc": "Price: low to high",
    "price_desc": "Price: high to low",
    "rating_desc": "Rating: high to low",
}

_SORT_KEYS = {
    "price_asc": lambda p: (p["price_cents"], p["id"]),
    "price_desc": lambda p: (-p["price_cents"], p["id"]),
    "rating_desc": lambda p: (-p["rating"], p["id"]),
}


class ShopError(Exception):
    """Base class of all errors the core reports to a client.

    ``rule`` identifies the violated rule (e.g. "BR3"), ``message`` is the
    human-readable text shown on the HTML page and returned by the API.
    """

    status_code = 400

    def __init__(self, rule: str, message: str):
        super().__init__(message)
        self.rule = rule
        self.message = message


class BusinessRuleError(ShopError):
    """A business rule BR1-BR8 was violated."""

    def __init__(self, rule: str, message: str):
        super().__init__(rule, message)
        self.status_code = 401 if rule == "BR1" else 409


class NotFoundError(ShopError):
    """A referenced product (or cart item) does not exist."""

    status_code = 404

    def __init__(self, message: str):
        super().__init__("NOT_FOUND", message)


class RegistrationError(ShopError):
    """A registration request was refused (bad username/password or name taken)."""

    status_code = 422

    def __init__(self, message: str):
        super().__init__("REGISTER", message)


class InvalidInputError(ShopError):
    """A search parameter (category or sort) has an unknown value."""

    status_code = 422

    def __init__(self, message: str):
        super().__init__("INVALID_INPUT", message)


# ---------------------------------------------------------------- helpers


def _eur(cents: int) -> float:
    """Convert integer cents to a EUR amount with two decimals."""
    return round(cents / 100, 2)


def _summary(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "price": _eur(row["price_cents"]),
        "rating": row["rating"],
        "available": bool(row["available"]),
        "badge": row["badge"],
    }


def _parse_int(value) -> int | None:
    """Return ``value`` as int if it is an int or a string of digits, else ``None``.

    Booleans, floats and strings like "2.5" or "-1" are not accepted.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
        return int(value)
    return None


def _load_product(conn: sqlite3.Connection, product_id) -> sqlite3.Row:
    pid = _parse_int(product_id)
    row = None if pid is None else conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    if row is None:
        raise NotFoundError(f"Product {product_id} does not exist.")
    return row


def _cart_id(conn: sqlite3.Connection, user) -> int:
    """BR1: return the cart of the logged-in user; the cart is looked up by its owner only."""
    row = None
    if user is not None:
        row = conn.execute(
            "SELECT carts.id FROM carts JOIN users ON users.id = carts.user_id WHERE users.id = ?", (user,)
        ).fetchone()
    if row is None:
        raise BusinessRuleError("BR1", "Please log in to use the cart.")
    return row["id"]


def _cart_quantity(conn: sqlite3.Connection, cart_id: int, product_id: int) -> int | None:
    row = conn.execute(
        "SELECT quantity FROM cart_items WHERE cart_id = ? AND product_id = ?", (cart_id, product_id)
    ).fetchone()
    return None if row is None else row["quantity"]


def _check_stock(product: sqlite3.Row, quantity: int) -> None:
    """BR3: the quantity in the cart may not exceed the stock."""
    if quantity > product["stock"]:
        raise BusinessRuleError("BR3", f"Only {product['stock']} units of {product['name']} are in stock.")


def categories(conn: sqlite3.Connection) -> list[str]:
    """Category names in catalogue order (read-only helper for the category filter)."""
    return [r["name"] for r in conn.execute("SELECT name FROM categories ORDER BY position")]


# ---------------------------------------------------------------- accounts

_PBKDF2_ITERATIONS = 200_000
USERNAME_PATTERN = r"[A-Za-z0-9_.-]{3,30}"
MIN_PASSWORD_LENGTH = 8


def hash_password(password: str, salt: str | None = None) -> str:
    """Return a salted PBKDF2-SHA256 hash as ``pbkdf2_sha256$iterations$salt$hex``."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest}"


def _password_matches(password: str, stored: str) -> bool:
    _, iterations, salt, digest = stored.split("$")
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
    return hmac.compare_digest(candidate, digest)


def login(conn: sqlite3.Connection, username, password) -> int:
    """Check the credentials and return the user id."""
    row = conn.execute("SELECT id, password_hash FROM users WHERE username = ?", (str(username or ""),)).fetchone()
    if row is None or not _password_matches(str(password or ""), row["password_hash"]):
        raise BusinessRuleError("BR1", "Invalid username or password.")
    return row["id"]


def register(conn: sqlite3.Connection, username, password, password_repeat) -> int:
    """Create a user account with an empty cart and return the new user id.

    For people trying the shop only: agents never see the login or registration
    page (the runner logs in before the run), and there is no API route for it.
    Accounts live in shop.db and are deleted by every reset.
    """
    username = str(username or "")
    password = str(password or "")
    if not re.fullmatch(USERNAME_PATTERN, username):
        raise RegistrationError(
            "Username must be 3 to 30 characters: letters, digits, dot, dash or underscore."
        )
    if len(password) < MIN_PASSWORD_LENGTH:
        raise RegistrationError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if password != str(password_repeat or ""):
        raise RegistrationError("The two passwords do not match.")
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        raise RegistrationError(f"The username {username} is already taken.")
    # Random id instead of the next rowid: after a reset the ids of deleted accounts would be
    # handed out again, and an old session cookie would then open another person's cart (BR1).
    user_id = secrets.randbelow(2**62) + db.TEST_USER_ID + 1
    with conn:
        conn.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
            (user_id, username, hash_password(password)),
        )
        conn.execute("INSERT INTO carts (user_id) VALUES (?)", (user_id,))
    return user_id


# ---------------------------------------------------------------- the seven service functions


def search_products(conn: sqlite3.Connection, query=None, category=None, sort=None) -> dict:
    """Search products by name and category.

    Every whitespace-separated word of ``query`` must occur (case-insensitive) in
    the product name or category name. ``category`` restricts the result to one
    category; ``sort`` is one of ``SORT_OPTIONS`` (default: catalogue order).
    Unavailable products are listed and marked as such.
    """
    query = (query or "").strip()
    category = (category or "").strip()
    sort = (sort or "").strip()
    if category:
        match = [c for c in categories(conn) if c.lower() == category.lower()]
        if not match:
            raise InvalidInputError(f"Unknown category: {category}.")
        category = match[0]
    if sort and sort not in SORT_OPTIONS:
        raise InvalidInputError(f"Unknown sort order: {sort}.")

    rows = conn.execute("SELECT * FROM products ORDER BY id").fetchall()
    words = query.lower().split()
    hits = [
        r for r in rows
        if (not category or r["category"] == category)
        and all(w in f"{r['name']} {r['category']}".lower() for w in words)
    ]
    if sort:
        hits.sort(key=_SORT_KEYS[sort])
    return {
        "query": query,
        "category": category or None,
        "sort": sort or None,
        "results": [_summary(r) for r in hits],
    }


def get_product(conn: sqlite3.Connection, product_id) -> dict:
    """Return all information about one product."""
    row = _load_product(conn, product_id)
    return {**_summary(row), "stock": row["stock"], "description": row["description"]}


def get_cart(conn: sqlite3.Connection, user) -> dict:
    """Return the user's cart with line totals and the total (BR8: computed here)."""
    cart_id = _cart_id(conn, user)
    rows = conn.execute(
        "SELECT p.id, p.name, p.price_cents, p.available, ci.quantity"
        " FROM cart_items ci JOIN products p ON p.id = ci.product_id"
        " WHERE ci.cart_id = ? ORDER BY ci.rowid",
        (cart_id,),
    ).fetchall()
    items = [
        {
            "product_id": r["id"],
            "name": r["name"],
            "unit_price": _eur(r["price_cents"]),
            "quantity": r["quantity"],
            "line_total": _eur(r["price_cents"] * r["quantity"]),
            "available": bool(r["available"]),
        }
        for r in rows
    ]
    total_cents = sum(r["price_cents"] * r["quantity"] for r in rows)
    return {"items": items, "total": _eur(total_cents)}


def add_to_cart(conn: sqlite3.Connection, user, product_id, quantity) -> dict:
    """Add ``quantity`` units of a product to the user's cart and return the cart.

    BR1 logged in, BR2 product available, BR3 quantity 1..MAX_QTY and within stock,
    BR4 an existing line is increased instead of adding a second line.
    """
    cart_id = _cart_id(conn, user)                                       # BR1
    product = _load_product(conn, product_id)
    qty = _parse_int(quantity)
    if qty is None or not 1 <= qty <= MAX_QTY:                           # BR3
        raise BusinessRuleError("BR3", f"Quantity must be a whole number between 1 and {MAX_QTY}.")
    if not product["available"]:                                         # BR2
        raise BusinessRuleError("BR2", f"{product['name']} is not available.")
    current = _cart_quantity(conn, cart_id, product["id"]) or 0
    new_qty = current + qty                                              # BR4
    if new_qty > MAX_QTY:                                                # BR3
        raise BusinessRuleError(
            "BR3", f"At most {MAX_QTY} units of {product['name']} are allowed in the cart (currently {current})."
        )
    _check_stock(product, new_qty)                                       # BR3
    with conn:
        conn.execute(
            "INSERT INTO cart_items (cart_id, product_id, quantity) VALUES (?, ?, ?)"
            " ON CONFLICT (cart_id, product_id) DO UPDATE SET quantity = excluded.quantity",
            (cart_id, product["id"], new_qty),
        )
    return get_cart(conn, user)


def update_cart_item(conn: sqlite3.Connection, user, product_id, quantity) -> dict:
    """Set the quantity of a cart item and return the cart.

    BR5: the new quantity must be 1..MAX_QTY; quantity 0 is rejected (removal is
    ``remove_from_cart``). BR2/BR3 apply as for adding.
    """
    cart_id = _cart_id(conn, user)                                       # BR1
    product = _load_product(conn, product_id)
    if _cart_quantity(conn, cart_id, product["id"]) is None:
        raise NotFoundError(f"{product['name']} is not in the cart.")
    qty = _parse_int(quantity)
    if qty is None or not 1 <= qty <= MAX_QTY:                           # BR5
        raise BusinessRuleError(
            "BR5", f"Quantity must be a whole number between 1 and {MAX_QTY}. Use Remove to delete an item."
        )
    if not product["available"]:                                         # BR2
        raise BusinessRuleError("BR2", f"{product['name']} is not available.")
    _check_stock(product, qty)                                           # BR3
    with conn:
        conn.execute(
            "UPDATE cart_items SET quantity = ? WHERE cart_id = ? AND product_id = ?",
            (qty, cart_id, product["id"]),
        )
    return get_cart(conn, user)


def remove_from_cart(conn: sqlite3.Connection, user, product_id) -> dict:
    """Remove a product from the cart and return the cart."""
    cart_id = _cart_id(conn, user)                                       # BR1
    product = _load_product(conn, product_id)
    if _cart_quantity(conn, cart_id, product["id"]) is None:
        raise NotFoundError(f"{product['name']} is not in the cart.")
    with conn:
        conn.execute("DELETE FROM cart_items WHERE cart_id = ? AND product_id = ?", (cart_id, product["id"]))
    return get_cart(conn, user)


def checkout(conn: sqlite3.Connection, user) -> dict:
    """Place an order for the cart contents and return the order.

    BR6 the cart is not empty and every item is available; BR7 the order stores the
    current prices and total, then the cart is emptied (no payment step);
    BR8 all amounts are computed here from the product table.
    """
    cart_id = _cart_id(conn, user)                                       # BR1
    cart = get_cart(conn, user)
    if not cart["items"]:                                                # BR6
        raise BusinessRuleError("BR6", "Your cart is empty.")
    for item in cart["items"]:                                           # BR6
        if not item["available"]:
            raise BusinessRuleError(
                "BR6", f"{item['name']} is not available. Remove it from the cart before checking out."
            )
    lines = conn.execute(
        "SELECT p.id, p.price_cents, ci.quantity FROM cart_items ci JOIN products p ON p.id = ci.product_id"
        " WHERE ci.cart_id = ? ORDER BY ci.rowid",
        (cart_id,),
    ).fetchall()
    total_cents = sum(r["price_cents"] * r["quantity"] for r in lines)   # BR7, BR8
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with conn:
        order_id = conn.execute(
            "INSERT INTO orders (user_id, total_cents, status, created) VALUES (?, ?, 'confirmed', ?)",
            (user, total_cents, created),
        ).lastrowid
        conn.executemany(
            "INSERT INTO order_lines (order_id, product_id, quantity, unit_price_cents) VALUES (?, ?, ?, ?)",
            [(order_id, r["id"], r["quantity"], r["price_cents"]) for r in lines],
        )
        conn.execute("DELETE FROM cart_items WHERE cart_id = ?", (cart_id,))  # BR7
    return {
        "order_id": order_id,
        "status": "confirmed",
        "created": created,
        "lines": [
            {
                "product_id": i["product_id"],
                "name": i["name"],
                "quantity": i["quantity"],
                "unit_price": i["unit_price"],
                "line_total": i["line_total"],
            }
            for i in cart["items"]
        ],
        "total": _eur(total_cents),
    }

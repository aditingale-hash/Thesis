# Thesis prototype: web interaction approaches for SLM agents

Research prototype for the Master's thesis *"Comparing Existing Web Interaction Approaches with
Tool-Based Interaction for Small Language Model Agents"* (TU Chemnitz, VSR). The full specification
is in [`CLAUDE.md`](CLAUDE.md); decisions and deviations are logged in
[`docs/thesis_notes.md`](docs/thesis_notes.md).

Status: **M1 (shop) done.** Agent core, pipelines, tasks, runner and analysis follow in M2-M6.

## Install

```bash
python3.11 -m venv .venv && source .venv/bin/activate   # Python 3.11+
pip install -e ".[dev]"
playwright install chromium                              # skip if Chromium is already provided
```

## Run the shop

```bash
python -m shop.build_db                   # catalogue.json -> shop/snapshot.db
python -m shop.reset                      # snapshot.db -> shop/shop.db (optionally: a task file)
python -m uvicorn shop.app:app --port 8000  # http://localhost:8000  (login: testuser / testpass)
```

- HTML frontend: `/login`, `/`, `/search`, `/products/{id}`, `/cart`, `/checkout`
- JSON API (agent tool interface):

| Service function | Route |
|---|---|
| login (runner only) | `POST /api/login` `{"username", "password"}` |
| `search_products` | `GET /api/products?query=&category=&sort=` |
| `get_product` | `GET /api/products/{product_id}` |
| `get_cart` | `GET /api/cart` |
| `add_to_cart` | `POST /api/cart/items` `{"product_id", "quantity"}` |
| `update_cart_item` | `PUT /api/cart/items/{product_id}` `{"quantity"}` |
| `remove_from_cart` | `DELETE /api/cart/items/{product_id}` |
| `checkout` | `POST /api/checkout` |

`sort` is one of `price_asc`, `price_desc`, `rating_desc`. Errors:
`{"error": {"rule": "BR3", "message": "..."}}`.

## Tests

```bash
python -m pytest            # includes a headless-Chromium walk through all pages
```

The browser test writes the thesis screenshots to `docs/figures/` (search results page, cart page).

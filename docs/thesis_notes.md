# Thesis notes (input for Chapter 4, Section 4.8)

Only real entries: versions actually installed, decisions actually taken, problems actually hit.

## 1. Versions

Development environment (M1). The experiment hardware is recorded separately in `config_record.json` by the runner (M5).

| Component | Version |
|---|---|
| Python | 3.13.16 (project requires >= 3.11) |
| SQLite (Python `sqlite3`) | 3.45.1 |
| FastAPI | 0.159.1 |
| Starlette | 1.9.0 |
| Jinja2 | 3.1.6 |
| itsdangerous (session signing) | 2.2.0 |
| python-multipart (form parsing) | 0.0.32 |
| uvicorn | 0.54.0 |
| httpx | 0.28.1 |
| Playwright for Python | 1.56.0 (Chromium 141.0.7390.37, headless) |
| pytest | 9.1.1 |

Development machine for M1: Linux cloud container, 4 vCPU, 15 GB RAM, no GPU (not the experiment machine).

## 2. Decisions

### D1 Repository layout
The repository root is the `prototype/` folder of the specification.

### D2 Catalogue (M1)
- 80 products in 8 categories (Mice, Keyboards, USB Hubs, Laptop Bags, Notebooks, Desk Lamps, Headsets, Webcams), 10 per category, ids `<category digit>01-10`.
- Tie prevention is stricter than required: prices are unique across the whole catalogue, ratings unique within each category. `build_db.validate_catalogue` refuses to build otherwise.
- Every category contains (checked by `tests/test_catalogue.py`): one unavailable product (stock 0), a cheap low-rated product, a pair of similar names, plus detail-only information in descriptions (e.g. Bluetooth, Ethernet port, silent buttons, 17-inch fit).
- The design role of each distractor is stored in the catalogue field `design_note`. It is ignored by `build_db.py` and never reaches the shop database, the pages or the API.
- Prices are stored as integer cents in SQLite; amounts are converted to EUR with two decimals only for output.
- Product images: see D16.

### D3 Category filter and sort are links, not `<select>` elements
The category filter and the sort order are rendered as lists of links (`/search?q=..&category=..&sort=..`), the active one marked with `aria-current`.
Reason: native `<select>` drop-down popups are drawn outside the page and do not appear in Playwright viewport screenshots in headless Chromium, so the visual pipeline could not see the options it chooses from, while the DOM pipeline would get them as text. Links behave identically in all three representations.
Consequence: the shop has no `<select>` element, so the DOM action `select(ref, option)` has no target. **Open question for the supervisor/author (see Section 5).**

### D4 Search semantics
`search_products`: every whitespace-separated word of the query must occur (case-insensitive substring) in "product name + category name". Unavailable products are listed and marked "Not available". Default order is catalogue order (id); sorts: `price_asc`, `price_desc`, `rating_desc` with product id as tie breaker. Unknown category or sort value -> `INVALID_INPUT` error. The category parameter is the category name as shown on the page (case-insensitive).

### D5 Raw request values go to the core unchanged
Routes and API pass form strings / JSON values to `service.py` unchanged; the core parses quantities and product ids (`_parse_int`: int or digit string; booleans, floats, "2.5", "-1" are rejected). This keeps BR3/BR5 in one place and gives identical messages for both interfaces.
Forms use `novalidate` and the quantity fields have no `min`/`max`, so the browser never validates input itself (that would be a rule outside `service.py` and would behave differently from the API).

### D6 Error classes and HTTP status codes
`ShopError(rule, message)` with subclasses `BusinessRuleError` (BR1 -> 401, BR2-BR8 -> 409), `NotFoundError` (rule `NOT_FOUND`, 404: unknown product, update/remove of an item that is not in the cart) and `InvalidInputError` (rule `INVALID_INPUT`, 422: unknown category/sort). The HTML page uses the same status code and shows the same message in the notice area (`<div class="notice" role="alert">`). The rule id itself is only in the API response.
Wrong login credentials are reported as BR1 ("Invalid username or password."). Refused registrations use `RegistrationError` (rule `REGISTER`, 422; HTML only, see D14).

### D7 Response after successful operations
- HTML: add/update/remove redirect (303) to the cart page; checkout renders the confirmation page directly.
- API: add/update/remove return the cart; checkout returns the order. So each API response has the fields of the page the browser ends up on.
- On error, the HTML page the user acted on is shown again with the notice; the API returns the error object.

### D8 Fields shown on pages = fields returned by the API
Single source: the service returns dictionaries and both the templates and the API serialise exactly these dictionaries (checked by `tests/test_fields.py`).
- Search result: id, name, category, price, rating, available, badge. (The id is visible to browser users only inside the link URL `/products/{id}`; the API needs it for `get_product`.)
- Product detail: + stock ("In stock: n"), description.
- Cart: per item product_id, name, unit_price, quantity, line_total, available; total.
- Order: order_id, status, created, lines (product_id, name, quantity, unit_price, line_total), total.

### D9 Read-only helper `service.categories()`
Besides the seven service functions and `login`, the core has one read-only helper returning the category names for the filter links on the HTML pages. To keep information equal, the tool pipeline must receive the same list (planned: as an `enum` of the `category` parameter in `tool_schemas.json`, M3).

### D10 Business rule details
- `MAX_QTY = 10`.
- BR1 ownership: no request carries a cart id; the cart is always looked up through the user id stored in the signed session.
- BR3 also applies to the accumulated quantity when adding a product already in the cart (BR4), and to updates (quantity <= stock).
- BR2 is also checked on update (increasing the quantity of an unavailable product is adding it).
- Check order in `add_to_cart`: login (BR1) -> product exists -> quantity format/range (BR3) -> available (BR2) -> accumulated max and stock (BR3).
- Checkout does not decrease stock (not part of the specification).
- Order `created` is the wall-clock UTC time; the verifier must ignore it.

### D11 Session
Starlette `SessionMiddleware`, cookie `shop_session`, signed with a fixed secret (overridable with `SHOP_SECRET_KEY`) so runs are reproducible. FastAPI's `/docs` and `/openapi.json` are disabled.
Passwords are stored as salted PBKDF2-SHA256 hashes (200,000 iterations, Python standard library). The test user's hash uses a fixed salt so that `snapshot.db` is byte-for-byte reproducible from the catalogue.

### D12 Reset
`reset(task)` copies `snapshot.db` to a temporary file and atomically replaces `shop.db` (`os.replace`), so a running server never opens a half-copied file; then it inserts `initial_state.cart` directly with SQL. Pre-filled carts deliberately bypass the business rules so that a task can start with e.g. an unavailable item (needed for C6). The server opens a new SQLite connection per request, so it sees the reset immediately without restart.

### D13 Visual design of the shop
Requested by the author after M1 ("make it look like a real shop"). The design is a typical small online shop: dark header with logo, search field and cart link; start page with a banner and category tiles; results as a grid of product cards (image, category, name, star rating, price, availability, badge) with a filter/sort sidebar; two-column product page; cart with an order-summary card; centred login/registration cards.
Constraints applied so that the design does not disturb the experiment:
- No JavaScript, no animations or transitions, no web fonts (system font stack only; no network during experiments), no lazy loading, no pop-ups. Checked by `tests/test_fields.py`.
- No `:hover` styles. The visual agent's mouse stays where it last clicked, so hover effects would change later screenshots depending on cursor position.
- Clearly visible focus outline on inputs, so the visual agent can see which field receives `type(text)`.
- No information beyond the API fields (D8). In particular: no cart item counter in the header (the tool agent only learns the cart through `get_cart`), no "only n left" messages, no ads (D15), no log-out link (a browser agent could end its own session, which the tool agent cannot).
- Star ratings are drawn by CSS from the numeric rating and marked `aria-hidden`; the number ("Rating: 3.9 / 5") is always shown as text. The product image in a result card links to the product (like real shops) but is `aria-hidden` with `tabindex=-1`, because it duplicates the name link; decorative SVGs (logo, icons) are `aria-hidden`. Images have `alt=""` because the product name is always next to them. So the DOM pipeline sees the same information without duplicates.
- Added navigation: search field in the header of every page (the tool agent can always call `search_products`), breadcrumb (Home / category) on the product page, "Continue shopping" link on the confirmation page.
The new design applies to both browser-based pipelines alike; the tool pipeline is unaffected.

### D14 Registration page (people only)
Requested by the author. `/register` (username, password, repeat password) is linked only from the login page; on success the new user is logged in and gets an empty cart. Validation lives in `service.register` (username 3-30 characters of letters, digits, `.`, `-`, `_`; password at least 8 characters; passwords equal; username not taken).
It is not part of the experiment: agents never see the login page (the runner logs in before the run), there is no API route for it, and every reset deletes all registered accounts (reset copies `snapshot.db`, which contains only the test user).

### D15 No advertisements
The author asked for an ad-supported look and then decided against ads: ad banners would appear only in the two browser pipelines (the tool agent's JSON never contains them), so the interface would no longer be the only difference between conditions.

### D16 Product images
Decision of the author: real product photos. Status: **pending**. The development environment's network policy blocks the image sources (Wikimedia Commons, Openverse, Pexels, Unsplash), so no photos have been added yet. The shop already looks for `shop/static/products/<id>.jpg` and falls back to a colour illustration of the product's category (one SVG per category, no text). Requirements for the photos when they are added: freely licensed with source and licence recorded in `shop/static/products/CREDITS.md`, stored in the repository (no network at experiment time), no text, logos or prices visible in the image.

## 3. Deviations from the specification

- D3: no `<select>` elements in the shop (category filter and sort as links); affects the DOM action `select`.
- D9: one extra read-only helper `categories()` in `service.py` besides the seven service functions + login.
- D14: an extra service function `register()` and a registration page (people only, not reachable by agents).
- D16: product images: category illustrations now, real photos planned, instead of "neutral category icon only".

## 4. Problems encountered (problem, cause, solution)

- **Browser history after a rejected form submission.** Observed in the browser test: after a rejected "Add to cart", one *Back* returns to the product page (the rejected POST result is its own history entry), not to the results list. Relevant for the `go_back()` action of the DOM and visual pipelines; no change made, since this is normal browser behaviour and identical for both browser-based pipelines.

- **Category images missing from a screenshot.** A screenshot taken right after clicking "Log in" showed six of eight category tiles without their image. Cause: Playwright's `click()` returns once the navigation has started; the page's images had not finished loading. Solution for the screenshots and the browser tests: wait for the `load` event. Consequence for M3: both browser pipelines must wait for the `load` event after every action before the next observation (as the specification already requires).
- **Image sources blocked.** Downloading product photos failed: the network policy of the development environment denies Wikimedia Commons, Openverse, Pexels and Unsplash (HTTP 403 at the proxy). Photos are pending (D16).

## 5. Open questions

- DOM action `select(ref, option)`: drop it from the DOM action space (the shop has no `<select>`), or keep it for completeness (it would always be invalid)? See D3.
- Product photos (D16): which source to allow in the environment's network settings (recommended: Wikimedia Commons, `commons.wikimedia.org` and `upload.wikimedia.org`, because every file has a clear free licence and author for the credits).

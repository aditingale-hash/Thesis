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
| PyYAML | 6.0.3 |
| jsonschema (tool argument validation) | 4.26.0 |
| NumPy / pandas / SciPy / Matplotlib | 2.5.3 / 3.0.5 / 1.18.1 / 3.11.2 |
| pytest | 9.1.1 |
| Ollama and model | not available in the development environment; recorded per experiment in `config_record.json` |

Development machine for M1-M6: Linux cloud container, 4 vCPU, 15 GB RAM, no GPU, no Ollama (not the experiment machine). The experiment hardware is written to `config_record.json` by the runner.

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
Consequence: the shop has no `<select>` element, so the DOM action `select(ref, option)` would have no target. Decision (author, when asking for M2-M6 in one go; the recommended option was taken): `select` is not offered in the DOM action space (D17).

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
Requested by the author after M1 ("make it look like a real shop"). The design is a typical small online shop: dark header with logo, search field and cart link; start page with a banner and category tiles; results as a grid of product cards (image, category, name, rating, price, availability, badge) with a filter/sort sidebar; two-column product page; cart with an order-summary card; centred login/registration cards.
Constraints applied so that the design does not disturb the experiment:
- No JavaScript, no animations or transitions, no web fonts (system font stack only; no network during experiments), no lazy loading, no pop-ups. `tests/test_fields.py` checks that no page contains `<script`, `loading=` or `<dialog`, and that `style.css` has no hover, transition, animation, `@font-face`, `@import` or `url()` rules.
- No `:hover` styles. The visual agent's mouse stays where it last clicked, so hover effects would change later screenshots depending on cursor position. For the same reason the browser's own hover controls are hidden: the spin arrows of number fields and the clear button of the search field (Chromium shows them only while the cursor is over the field).
- Clearly visible focus outline on inputs, so the visual agent can see which field receives `type(text)`.
- No information beyond the API fields (D8). In particular: no cart item counter in the header (the tool agent only learns the cart through `get_cart`), no "only n left" messages, no ads (D15), no log-out link (a browser agent could end its own session, which the tool agent cannot).
- No star-bar rating graphic. The rating is shown as text ("Rating: 3.9 / 5") next to one constant, decorative star icon (`aria-hidden`). A first version drew five partially filled stars from the rating; the review found that at 15 px the fill rounds to whole stars, so 3.9 looked exactly like 4.0. Only the visual pipeline would see that graphic, and it misstates the attribute the rating tasks test (product 101 is designed as "just below 4.0"), so it was removed. The product image in a result card links to the product (like real shops) but is `aria-hidden` with `tabindex=-1`, because it duplicates the name link; decorative SVGs (logo, icons) are `aria-hidden`. Images have `alt=""` because the product name is always next to them. So the DOM pipeline sees the same information without duplicates.
- Added navigation: search field in the header of every page (the tool agent can always call `search_products`), breadcrumb (Home / category) on the product page, "Continue shopping" link on the confirmation page.
The new design applies to both browser-based pipelines alike; the tool pipeline is unaffected.

### D14 Registration page (people only)
Requested by the author. `/register` (username, password, repeat password) is linked only from the login page; on success the new user is logged in and gets an empty cart. New users get a random id (not the next row id), so that after a reset an old session cookie can never point to a different, newly registered account (BR1). Validation lives in `service.register` (username 3-30 characters of letters, digits, `.`, `-`, `_`; password at least 8 characters; passwords equal; username not taken).
It is not part of the experiment: agents never see the login page (the runner logs in before the run), there is no API route for it, and every reset deletes all registered accounts (reset copies `snapshot.db`, which contains only the test user).

### D15 No advertisements
The author asked for an ad-supported look and then decided against ads: ad banners would appear only in the two browser pipelines (the tool agent's JSON never contains them), so the interface would no longer be the only difference between conditions.

### D16 Product images
Decision of the author: real product photos. Status: **pending**. The development environment's network policy blocks the image sources (Wikimedia Commons, Openverse, Pexels, Unsplash), so no photos have been added yet. The shop already looks for `shop/static/products/<id>.jpg` and falls back to a colour illustration of the product's category (one SVG per category, no text) on the start, results and product pages, and to a generic product illustration (`icons/product.svg`) in the cart, whose items carry no category (D8). Requirements for the photos when they are added: freely licensed with source and licence recorded in `shop/static/products/CREDITS.md`, stored in the repository (no network at experiment time), no text, logos or prices visible in the image.

### D17 DOM pipeline
- Actions `click(ref)`, `type(ref, text)`, `go_back()`, `finish()`; no `select` (D3).
- Observation: page title, URL and the reduced accessibility tree of the whole page from `dom_extract.js`. Kept: visible interactive elements (`[n] link/button/searchbox/spinbutton/textbox "name"`, with `value=` for fields and `(current)` for `aria-current`), headings and visible text nodes. Dropped: `aria-hidden` subtrees, invisible or 1-px "visually hidden" boxes, decorative images, `<label>` elements (their text is the field's name). Names and texts use `textContent`, so CSS `text-transform` (e.g. upper-case category) does not change them.
- Indentation (2 spaces) per grouping element (`li`, `nav`, `form`, `aside`, `section`, `header`, `footer`, `dl`). A list item with more than one element gets a `listitem` marker line, so that the boundaries between product cards and cart lines are visible (without it a badge appeared to belong to the previous card; found while checking the example observation).
- Refs are stored as attribute `data-agent-ref="<observation number>:<n>"` at observation time (in the browser only, not in the served HTML). A ref that does not exist in the latest observation, or whose element disappeared because the page changed after the observation, is invalid.
- `type(ref, text)` replaces the field content (Playwright `fill`) and never submits; typing into a non-field is invalid.
- Truncation rule as specified: text nodes removed from the end first, interactive elements last, with the note "(observation truncated)".
- The example in the action-space text is `[7] button "OK"` (a name that never occurs in the shop), see Problems.
- Example observation: `docs/dom_observation_example.txt`.

### D18 Visual pipeline
- Observation: viewport screenshot (PNG, 1280x800) only, attached to the model message; the prompt text says only that a screenshot of 1280x800 pixels is attached. Every screenshot is saved as `results/<experiment>/<run_id>/step_<n>.png`.
- Actions `click(x, y)`, `type(text)`, `press(key)`, `scroll(direction)` (600 px), `go_back()`, `finish()`, executed with `page.mouse` / `page.keyboard` only. Coordinates are numbers (integers or decimals). Positions outside the viewport, unknown keys and directions are invalid. Allowed keys: Enter, Tab, Shift+Tab, Backspace, Delete, Escape, arrow keys, PageUp/PageDown, Home, End, Control+A.
- DECISION coordinate system: configurable in `model.yaml` (`coordinate_mode`). Default `pixels` (pixels of the screenshot), alternative `normalized_1000` (0-1000 on both axes, converted to pixels). The conversion is tested with a real click on the Cart link in both modes. Which system the chosen model actually outputs must be checked in the smoke test on the experiment machine (not possible here, no Ollama).
- `type(text)` types at the keyboard focus and adds to existing content (keyboard input cannot replace a field's content in one step); the action space says to press Control+A first. This differs from the DOM pipeline's `type`, which replaces the content; it is part of the representation (keyboard events vs. element access).
- No DOM information reaches the visual agent: its history lines contain only the action and its status, never page titles or notice texts. The status itself (executed / rejected) is determined by the harness by checking for the shop's error notice after a navigation; the notice text is kept only in the trace (`ActionResult.detail`).
- DECISION perception component (OmniParser) for text-only models: not implemented (`perception: none` is the only accepted value), because the default model is multimodal. `perception_ms` is recorded as null.

### D19 Tool pipeline
- `tool_schemas.json`: the seven tools with description and JSON-schema parameters; the action space text is generated from it. `category` and `sort` are enums; the category enum equals the catalogue categories (test), which gives the tool agent the same category list the HTML filter shows (D9). `add_to_cart` requires `quantity` (the HTML form pre-fills 1).
- Argument validation with `jsonschema` (enum values, no extra arguments) -> invalid; argument types are already checked by the common action parser.
- Any error answer of the shop core (BR1-BR8, NOT_FOUND, INVALID_INPUT) -> rejected with the core's message; the observation is the error JSON. HTTP 5xx or connection errors -> error (S5).
- Observation: `Result of <tool>:` followed by the JSON (indented). Truncation rule (not specified for the tool pipeline): drop search results from the end, otherwise cut the text.

### D20 Shared browser handling and history
- Both browser pipelines use the same helper (`pipelines/browser.py`): a fresh browser context per run with the session cookie, start page `/` (the agent never sees the login page), and the same waiting rule after an action. After clicks, key presses and back: wait up to 500 ms for a navigation to start (detected with a marker variable on the current document), then for the `load` event. Typing and scrolling do not navigate. This adds up to 0.5 s to non-navigating clicks in both browser pipelines alike.
- A rejected action in a browser pipeline = the action caused a navigation and the new page shows the shop's error notice.
- History lines: `<step>: <action>(<args>) -> <status>` plus, for DOM, `, page "<title>"`, and the message for non-executed actions (DOM: notice text; tool: core message; all: interface error such as "There is no element [12]"). Invalid responses: `<step>: invalid response -> <reason>`.

### D21 Agent core
- Model: `qwen2.5vl:3b` (multimodal, so the visual pipeline uses the same model); configurable. Ollama `/api/chat`, no streaming, `format` = the common action JSON schema, temperature 0, seed 42, `num_ctx` 16384, `num_predict` 512, request timeout 300 s (a timeout is an S5).
- The prompt is one user message (five sections, `agent/prompt_template.txt`); the screenshot is attached to it for the visual pipeline.
- Context budget: no tokenizer is available for every model, so prompt length is estimated as characters / 3.5 and a screenshot as 1,400 tokens (Qwen2.5-VL 28x28 patches at 1280x800 = ~1,330 tokens). The budget is `num_ctx - num_predict`. Actual token counts are recorded from Ollama.
- Parser: strict types (an integer must be a JSON integer, `"14"` or `14.0` are invalid; booleans are not numbers); unknown and missing arguments are invalid; `args` may be omitted for `finish`.
- Invalid = unparseable/ill-typed response or an action that is invalid at interface level; both count towards S3 (consecutive). Rejected actions reset the counter.
- Limits (`limits.yaml`): S2 25 invocations, S3 3 consecutive invalid, S4 600 s. Values to be confirmed after the pilot.
- `observation_size`: characters for text observations, bytes of the PNG for screenshots (not comparable across modalities; token counts are the comparable measure).

### D22 Tasks (M4)
- 28 tasks, 4 per category; levels: C1, C2 simple; C3-C6 medium; C7 complex. Instructions name products by their exact names or describe them by constraints, and never mention pages, buttons, clicking, coordinates or tool names (checked by a test).
- Constraint tasks (C2-C4 and C7-04) store their constraints in the task file (`category`, filters `min_rating`, `max_price`, `price_below`, `price_above`, `objective` cheapest / most_expensive / highest_rated); `goal_states.py` computes the product from the available products of the catalogue and fails on ties or no match. Constraint instructions say "available" explicitly, because unavailable products are deliberate distractors (e.g. C4-01: 106 would be the answer if it were available; the goal is 108 with rating exactly 4.0).
- C5/C6 and C7-03 start with pre-filled carts (C6-01 and C7-03 contain the unavailable product 106).
- Reference solutions (`evaluation/reference_solutions/<task>.json`) have a `browser` script shared by DOM and visual (steps like `click link "Mice"`, `fill searchbox "Search products" with "..."`) and a `tool` script. `validate_tasks.py` compiles the browser script for each pipeline at run time (DOM: the element's `[ref]`; visual: the element's centre on screen, with scroll actions if needed, followed by Control+A and typing for fields). This reads the browser and is used only for validation. Result: 84/84 succeed; maximum 7 actions in the visual pipeline (C7-04), limit 25.

### D23 Evaluation and runner (M5)
- Verifier as specified; additionally checks that order lines carry the catalogue price. Invariants: `no_order_created` (C1-C6), `exactly_one_order` and `cart_empty` (C7). "New order" = any order, because the snapshot contains none.
- Trace: `results/<experiment>/<run_id>/trace.jsonl`; `invocation` events also store the raw response; `action` events for unparseable responses have `name: null` and `parse_error`. `runs.csv` has the specified columns plus `attempts`. `n_actions` counts actions sent to the pipeline (finish and unparseable responses excluded); `n_invalid` counts invalid responses and invalid actions.
- Runner: the shop is started in-process on a free localhost port unless `shop_url` is set; one Chromium for the experiment, relaunched if it crashes; a fresh browser context or HTTP client per run. The timer covers only `run_agent` (after reset, login and attach; verification and file writing outside). S5 runs are retried up to `infrastructure_retries` times with a fresh reset; the final S5 row has an empty `success` and is excluded by the analysis. Resume skips any run id that already has a row. `run-one` writes to `results/debug/` with a time-stamped run id.
- `config_id` = first 12 hex digits of SHA-256 over the input file hashes, model info and model configuration.
- `--stub`: model that always answers finish, to check the chain without Ollama (used for the plumbing pilot below; it is not an experiment).

### D24 Analysis (M6)
- S5 runs excluded from all rates. Metrics per pipeline, per pipeline x category, per pipeline x level: success rate with Wilson 95 % CI; median and IQR of actions, invocations, execution time and total tokens (input + output), for all runs and for successful runs; invalid rate = invalid / invocations; rejected rate = rejected / actions; false completion rate; step-limit rate (S2-S4); pass^1 and pass^k with k = number of repetitions (unbiased estimator C(c,k)/C(n,k) per task, averaged over tasks); mean observation size; mean perception time.
- Statistics on per-task values (success rate over repetitions, median tokens, median time): Friedman test across the three pipelines (tasks as blocks), pairwise Wilcoxon signed-rank (`zero_method="wilcox"`) with Holm correction; if two pipelines are equal on every task the pair gets p = 1.
- Plots: one fixed colour per pipeline (validated categorical palette: blue, orange, aqua), value labels on all bars.
- Auto labels (first match): G1 if the run ended by S3 and at least half of the invalid steps were unparseable; D2 if it ended by S3 and at least half were references to non-existing elements; G4 if the same state-changing tool call or the same browser click/type occurs three times in a row; G3 if the agent finished without success. Other failed runs are left for manual labelling; manual `final_label` and `note` survive regeneration.

## 3. Deviations from the specification

- D3: no `<select>` elements in the shop (category filter and sort as links); affects the DOM action `select`.
- D9: one extra read-only helper `categories()` in `service.py` besides the seven service functions + login.
- D14: an extra service function `register()` and a registration page (people only, not reachable by agents).
- D16: product images: category illustrations (generic illustration in the cart) now, real photos planned, instead of "neutral category icon only".
- D17: no `select(ref, option)` action in the DOM pipeline.
- D18: perception component (OmniParser) not implemented; visual `type` appends while DOM `type` replaces.
- D22: DOM and visual reference solutions are compiled from one shared browser script per task instead of two separate action lists.
- D23: extra column `attempts` in `runs.csv`.

## 4. Problems encountered (problem, cause, solution)

- **Browser history after a rejected form submission.** Observed in the browser test: after a rejected "Add to cart", one *Back* returns to the product page (the rejected POST result is its own history entry), not to the results list. Relevant for the `go_back()` action of the DOM and visual pipelines; no change made, since this is normal browser behaviour and identical for both browser-based pipelines.

- **Category images missing from a screenshot.** A screenshot taken right after clicking "Log in" showed six of eight category tiles without their image. Cause: Playwright's `click()` returns once the navigation has started; the page's images had not finished loading. Solution: the browser test waits for the `load` event before taking the thesis figures. Consequence for M3: both browser pipelines must wait for the `load` event after every action before the next observation (as the specification already requires).
- **Star graphic misstated ratings near the threshold.** Found by a review of the redesign: the CSS star bar rendered 3.9 and 4.0 almost pixel-identical (one pixel difference). Cause: five star glyphs at 15 px cannot show 0.1 steps. Solution: star bar removed, rating shown as text (D13).
- **Reused user ids after reset.** Found by the same review: SQLite gives a new account the next free row id, and reset deletes all registered accounts, so a newly registered account after a reset got the same id as an earlier one, and the earlier account's session cookie opened the new account's cart. Solution: random ids for registered users (D14); test `test_old_session_cannot_open_a_new_account_after_reset`.
- **Image sources blocked.** Downloading product photos failed: the network policy of the development environment denies Wikimedia Commons, Openverse, Pexels and Unsplash (HTTP 403 at the proxy). Photos are pending (D16).

- **Clicks on two-line product names missed.** `validate_tasks.py` first failed for 5 visual reference solutions: clicking the centre of a product name that wraps onto two lines hit the empty space next to the shorter second line, so nothing happened. Cause: an inline link's box covers both lines, but only the text is clickable. Solution: the product name link in result cards is a block element, so its whole box is clickable (also for a model that clicks the middle of the name).
- **Action-space example matched a real element.** A scripted test model looked for `[n] button "Search"` in the prompt and found the example `[7] button "Search"` from the DOM action-space text instead of the real button. A small model can be misled the same way. Solution: the example now uses a name that never occurs in the shop (`[7] button "OK"`).
- **Pandas object dtype.** `runs.csv` stores `success` as text; after mapping to booleans the column kept the object dtype and SciPy's Friedman test failed. Solution: cast to bool after removing S5 rows and cast per-task measures to float.
- **Real-model smoke test and pilot not possible in the development environment.** Ollama cannot be installed there (no network access to ollama.com). The chain was checked with the stub model instead: all 84 runs of the pilot plan (28 tasks x 3 pipelines, 1 repetition) completed without crashes in 35 s, followed by metrics, statistics, plots, auto labels and viewer on that data. The smoke test (C1-01 in all three pipelines with the real model) and the pilot with the real model have to be run on the experiment machine.

## 5. Open questions
- Smoke test with the real model: does `qwen2.5vl:3b` give click coordinates in screenshot pixels? If not, set `coordinate_mode: normalized_1000` (D18).
- Number of repetitions R and the limits S2-S4: choose after the real pilot.

- Product photos (D16): which source to allow in the environment's network settings (recommended: Wikimedia Commons, `commons.wikimedia.org` and `upload.wikimedia.org`, because every file has a clear free licence and author for the credits).

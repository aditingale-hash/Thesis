# CLAUDE.md: thesis prototype

> Repository layout note: this repository root *is* the `prototype/` folder of Section 3.

## 1. Context

You are building the research prototype for my Master's thesis at TU Chemnitz (VSR group):
**"Comparing Existing Web Interaction Approaches with Tool-Based Interaction for Small Language Model Agents"**.

The prototype is an experimental system. One agent driven by one locally running small language model (SLM)
completes the same shopping tasks on the same web shop through three interaction pipelines:

1. **DOM/accessibility pipeline**: the agent reads a reduced accessibility tree and clicks/types on numbered elements (Playwright).
2. **Visual pipeline**: the agent sees only screenshots and acts with mouse/keyboard input events at screen coordinates (Playwright).
3. **Tool pipeline**: the agent calls structured shop functions (search, add to cart, ...) that return JSON.

**The interaction pipeline is the only experimental variable.** Task, initial state, shop logic, model configuration,
agent loop, stopping conditions, verification and measurement must be identical in all three conditions.
Every design decision must protect this. If something forces a difference between pipelines, stop and tell me.

This is not a product. It must be correct, reproducible, measurable and simple. Do not add features that are not listed here.

## 2. Fixed decisions (do not change without asking me)

| Topic | Decision |
|---|---|
| Language | Python 3.11+ for everything |
| Shop | FastAPI + Jinja2 server-rendered HTML (no React/SPA, no client-side JS rendering) |
| Database | SQLite file `shop.db`; reset by copying `snapshot.db` |
| Browser | Playwright for Python, headless Chromium, fixed viewport 1280x800 |
| Model runtime | Ollama via its HTTP API (`/api/chat`), temperature 0, fixed seed |
| Model | configurable in `config/model.yaml`; prefer a multimodal SLM so the visual pipeline uses the same model |
| Action format | ONE common JSON format for all pipelines: `{"thought": str, "action": str, "args": object}` enforced with Ollama structured output (`format` = JSON schema) |
| Tool transport | Tool pipeline calls the shop's JSON API over HTTP (httpx) with the session cookie. No MCP. |
| Trace format | JSON Lines file per run + one summary CSV row per run |
| Analysis | pandas, SciPy, matplotlib |

Open decisions are marked `DECISION` below. Implement the default, make it configurable, and list it in `docs/thesis_notes.md`.

## 3. Repository structure

```
prototype/
  CLAUDE.md
  README.md                    # how to install, run shop, run experiment, run analysis
  pyproject.toml               # pinned versions
  config/
    model.yaml                 # model tag, quantization note, num_ctx, temperature 0, seed, max output tokens
    limits.yaml                # S2 max invocations, S3 max consecutive invalid, S4 max seconds
    plan.yaml                  # experiment plan (tasks, pipelines, repetitions, seed, retries)
  shop/
    app.py                     # FastAPI app
    service.py                 # application core: ALL business rules live here only
    db.py                      # SQLite access
    routes_html.py             # web frontend
    routes_api.py              # JSON agent tool interface under /api
    templates/                 # Jinja2 pages
    static/                    # minimal CSS, neutral category icons
    data/catalogue.json        # fixed product catalogue
    build_db.py                # builds snapshot.db from catalogue.json
    reset.py                   # reset(task) -> copies snapshot, applies pre-filled cart
    state_reader.py            # READ-ONLY access for the verifier (sqlite mode=ro), no HTTP route
  agent/
    model_client.py            # Ollama client -> text, input_tokens, output_tokens, duration
    prompt.py                  # template with 5 sections
    prompt_template.txt
    action_parser.py
    context.py                 # history manager
    loop.py                    # control loop + stopping conditions S1-S5
  pipelines/
    base.py                    # InteractionPipeline ABC, Observation, Action, ActionResult
    dom.py
    dom_extract.js             # in-page script for the reduced accessibility tree
    visual.py
    tool.py
    tool_schemas.json
  evaluation/
    tasks/*.json               # one file per task
    goal_states.py             # computes goal states for C2-C4 from the catalogue, fails on ties
    reference_solutions/       # one per task and pipeline
    validate_tasks.py          # runs all reference solutions without the model
    verifier.py
    trace.py                   # trace recorder
    runner.py                  # experiment runner CLI
    analysis/metrics.py, stats.py, plots.py
    labelling/auto_labels.py, viewer.py
  results/                     # created at run time, git-ignored except summaries
  tests/
  docs/thesis_notes.md         # versions, decisions, deviations, challenges (for thesis Chapter 4)
```

## 4. Component specifications

### 4.1 Shop (thesis Sections 3.2 / 4.2)

**Domain model**
- Product: id, name, category, price (EUR, 2 decimals), rating (0.0-5.0, 1 decimal), available (bool), stock (int), description, badge (optional text, e.g. "Bestseller").
- User (one test user), Cart (one per user), CartItem (product, quantity), Order (id, total, status, created), OrderLine (product, quantity, unit_price).

**Catalogue** (`catalogue.json`, ~60-100 products, 6-8 categories, e.g. mice, keyboards, USB hubs, laptop bags, notebooks, desk lamps). Include deliberate distractors:
- similar names in the same category,
- products that satisfy one constraint but not another (cheap but low rating),
- unavailable products that would otherwise match,
- information only visible on the product detail page (e.g. full description).
No ties in price or rating among products that could match a constraint task. Product images: neutral category icon only (no text in images).

**Business rules (enforced ONLY in `service.py`)**. Violation raises `BusinessRuleError(rule_id, message)`:
- BR1 cart/order operations require an authenticated session; a cart is only accessible by its owner.
- BR2 only available products can be added.
- BR3 quantity is an integer 1..MAX_QTY (e.g. 10) and <= stock.
- BR4 adding a product already in the cart increases its quantity (never two lines for one product).
- BR5 updating to a quantity outside the allowed range is rejected; removal is a separate operation.
- BR6 checkout requires a non-empty cart with all items available.
- BR7 checkout creates an order with current prices and total, then empties the cart. No payment.
- BR8 prices and totals are computed only by the core; no request can set a price.

**Service functions** (exactly these seven + login):
`search_products(query, category=None, sort=None)`, `get_product(product_id)`, `get_cart(user)`, `add_to_cart(user, product_id, quantity)`,
`update_cart_item(user, product_id, quantity)`, `remove_from_cart(user, product_id)`, `checkout(user)`.

**HTML frontend** (semantic HTML, `<label>` on every field, NO `data-testid` or agent-specific attributes):
login page, start page with search field + category filter, results page with sort (price asc/desc, rating desc) showing for each product:
name (link), price, rating, availability, badge; product detail page with full info, quantity field, "Add to cart" button;
cart page with quantity field + "Update" button and "Remove" button per item, total, "Checkout" button;
checkout page with "Confirm order" button; order confirmation page. Errors are shown in a notice area at the top.
Keep pages simple and stable: no animations, no lazy loading, no pop-ups, no cookie banners.

**JSON API** under `/api`: one route per service function. Responses contain **the same fields the corresponding page shows**.
Errors: `{"error": {"rule": "BR3", "message": "<same text as on the HTML page>"}}`.

**Session**: signed session cookie. Login is done by the runner during setup, never by the agent.

**Reset**: copy `snapshot.db` -> `shop.db`, then apply the task's pre-filled cart. Only called between runs.

**State reader**: opens `shop.db` read-only; returns cart items and orders. Not exposed over HTTP.

### 4.2 Agent core (Sections 3.3 / 4.3)

**Model client**: returns `(text, input_tokens, output_tokens, duration_ms)` from Ollama's `prompt_eval_count`, `eval_count`, timings.
Supports an optional image (base64 PNG). Uses `config/model.yaml`. Temperature 0, fixed seed.

**Prompt** (`prompt_template.txt`) has exactly five sections, in this order:
1. Role and rules (shared): one action per response, output JSON format, use `finish` when the task is done.
2. Action space (from the pipeline).
3. Task instruction.
4. History: one line per previous step, e.g. `3: click(14) -> executed, page "Wireless Mouse M2"`.
5. Current observation (full).
Previous observations are never repeated. If the prompt exceeds the context budget, the pipeline truncates the current observation by its rule and the step is marked `truncated=true`.

**Action parser**: valid JSON with a known action name and arguments of the right types -> Action; otherwise -> invalid response (no action executed, error line added to history).

**Loop**: per step: observe -> build prompt -> invoke model -> record invocation -> parse -> if `finish`: stop -> else execute -> record action -> add to history.
Exactly one action per model invocation.

**Stopping conditions** (values from `config/limits.yaml`):
S1 agent issues `finish`; S2 max model invocations reached; S3 max consecutive invalid actions; S4 max task execution time; S5 infrastructure failure (browser crash, Ollama error, shop down).
Record the termination reason. `finish` never means success.

### 4.3 Pipelines (Section 3.4 / 4.4)

**Common interface** (`pipelines/base.py`):
```python
class InteractionPipeline(ABC):
    def attach(self, session) -> None
    def action_space(self) -> str
    def observe(self) -> Observation        # modality ("text"|"image"), content, size
    def execute(self, action) -> ActionResult  # status in {"executed","rejected","invalid","error"}, message
    def close(self) -> None
```
Status meaning: executed = performed and accepted; rejected = performed but refused by a business rule (message = core error text);
invalid = cannot be performed at interface level (unknown ref, bad args, off-screen target); error = infrastructure problem.
Every pipeline also accepts `finish()`.

**DOM pipeline**
- Observation: page title + URL + reduced accessibility tree of the WHOLE page from `dom_extract.js`:
  keep visible interactive elements and visible text-bearing elements, drop hidden/decorative ones,
  assign `[n]` reference numbers to interactive elements (store as an attribute on the element for lookup).
  Format like: `[9] link "Wireless Mouse M2"` followed by indented `text "19.99 EUR"` lines.
- Actions: `click(ref)`, `type(ref, text)`, `select(ref, option)`, `go_back()`, `finish()`.
- Reference from an older observation or unknown -> invalid. Wait for the load event after each action.
- Truncation rule: remove non-interactive text nodes from the end first, interactive elements last.

**Visual pipeline**
- Observation: viewport screenshot PNG (1280x800). NO DOM/accessibility information of any kind.
- Actions: `click(x, y)`, `type(text)` (into focused element), `press(key)`, `scroll(direction)` (fixed pixel amount), `go_back()`, `finish()`.
- Execute with `page.mouse` / `page.keyboard` only, never element handles.
- Coordinates outside the viewport -> invalid.
- DECISION: check which coordinate system the chosen model outputs (pixels or normalised, e.g. 0-1000) and convert. Default: pixels in the given image.
- DECISION: if the model is text-only, add an optional perception component (OmniParser) that returns numbered elements with boxes from pixels only;
  then `click(element_number)`. Measure its time separately (`perception_ms`). Default: not used.
- Save every screenshot as `results/<experiment>/<run_id>/step_<n>.png`.

**Tool pipeline**
- Seven tools mirroring the frontend exactly: `search_products`, `get_product`, `get_cart`, `add_to_cart`, `update_cart_item`, `remove_from_cart`, `checkout`.
- `tool_schemas.json`: name, description, JSON-schema parameters. The action space text is generated from this file.
- Each tool sends an HTTP request to `/api` with the run's session cookie.
- Observation = JSON result of the last call; first observation = "No tool has been called yet."
- Schema violation -> invalid; API business-rule error -> rejected with the core's message.
- No tool may offer anything the frontend does not (no batch ops, no DB access).

### 4.4 Tasks (Section 3.5 / 4.5)

Task file:
```json
{"id": "C4-02", "category": "C4", "level": "medium",
 "instruction": "Add the cheapest mouse with a rating of at least 4 and a price of at most 50 euros to the cart.",
 "initial_state": {"cart": []},
 "goal_state": {"cart": [{"product_id": 214, "quantity": 1}], "orders": []},
 "invariants": ["no_order_created"]}
```
Categories (4 instances each -> 28 tasks; DECISION: final number):
C1 direct add (simple), C2 price constraint (simple), C3 rating constraint (medium), C4 multiple constraints (medium),
C5 quantity update (medium), C6 cart correction with pre-filled cart (medium), C7 add + checkout (complex).
Instructions are pipeline-neutral: never mention clicking, pages, buttons, coordinates or tool names.

`goal_states.py`: for C2-C4, apply the constraints to `catalogue.json`, write the product id into the goal state, exit with error if more than one product matches.

Reference solutions: one per task and pipeline, as action lists. `validate_tasks.py` executes them through the pipeline interfaces WITHOUT the model,
runs the verifier, and requires success for all three pipelines with fewer actions than S2. (Visual reference solutions may read element positions from the browser to compute coordinates; this is validation only.)

### 4.5 Evaluation framework (Section 3.6 / 4.6)

**Verifier** (`verifier.py`): read-only state; cart check (set of (product_id, quantity) equals goal), order check (C7: exactly one new order with expected lines and empty cart; others: no order), invariant checks.
Returns `success`, `differences` list, `false_completion` (= terminated by S1 and not success).

**Trace recorder**: one JSONL file per run with events:
- `run_start` (run_id, task_id, pipeline, repetition, config_id, timestamp)
- `invocation` (step, input_tokens, output_tokens, duration_ms, raw_response, observation_size, truncated, perception_ms)
- `action` (step, name, args, status, message, duration_ms)
- `run_end` (termination_reason, execution_time_ms, verification result)
Plus one summary row per run in `results/<experiment>/runs.csv` with: run_id, task_id, category, level, pipeline, repetition,
success, termination_reason, false_completion, n_actions, n_invocations, n_invalid, n_rejected, input_tokens, output_tokens,
execution_time_ms, mean_observation_size.

**Measurement boundaries**: timer starts when the agent loop starts (after reset, login, attach) and stops at termination.
Reset, login, verification and file writing are outside.

**Metrics** (`analysis/metrics.py`): success rate (+ Wilson 95% CI), actions, invocations, execution time, total tokens (median + IQR, all runs and successful runs),
invalid action rate, rejected action rate, false completion rate, step-limit rate (S2-S4), pass^k, mean observation size, perception time.
Aggregate per pipeline, per category, per level.

**Stats** (`analysis/stats.py`): per task and pipeline compute success rate and medians; Friedman test across the 3 pipelines on per-task values;
pairwise Wilcoxon signed-rank with Holm correction.

**Failure labelling**: `auto_labels.py` assigns G1 (unparseable response), D2 (invalid reference), G3 (false completion), G4 (repeated identical state-changing action)
and writes `labels.csv` (run_id, auto_label, final_label, first_failing_step, note) for all failed runs. `viewer.py` prints a run step by step and lists its screenshots.
Full taxonomy for manual labels: G1-G5, T1-T2, D1-D3, V1-V4 (see thesis Table "Failure taxonomy").

### 4.6 Experiment runner (Section 3.7 / 4.7)

`python -m evaluation.runner run --plan config/plan.yaml`
1. Write `config_record.json`: package versions, Python version, Ollama version, model name + digest (`/api/show`), GPU/CPU/RAM (nvidia-smi / platform),
   git commit hash, SHA-256 of catalogue, task files, prompt template, tool schemas, limits.
2. Build all (task x pipeline x repetition) runs; shuffle with the plan's seed.
3. One warm-up model call (not recorded).
4. For each run: reset -> login -> new browser context with cookie (or tool HTTP client with cookie) -> attach -> start timer -> loop -> stop timer -> verify (unless S5) -> write record -> close.
5. Skip runs that already have a summary row (resumable). Retry S5 runs up to `infrastructure_retries`; report them separately and exclude from success rate.
Also provide `run-one --task C1-01 --pipeline dom` for debugging.

## 5. Working rules for you (Claude Code)

- Build in the milestone order of Section 6. After each milestone, run its tests, show me the result, and wait for my go before the next one.
- Business rules live only in `service.py`. Never duplicate them in routes, tools or pipelines.
- Never give one pipeline information or abilities the others lack (except the representation itself).
- Never let the agent see the verifier, the state reader, task goal states or reference solutions.
- Pin all dependency versions. No network access at experiment time except localhost.
- Keep `docs/thesis_notes.md` updated with: versions, hardware, every DECISION and what was chosen, every deviation from this spec with the reason,
  and every real problem you hit (problem, cause, solution). I copy this into thesis Section 4.8, so do not invent entries.
- Write clear docstrings; keep code simple and readable; no unnecessary abstractions.

## 6. Milestones and acceptance checklist

### M1 Shop
- [ ] `build_db.py` creates `snapshot.db` from `catalogue.json`; catalogue has distractors and no relevant ties.
- [ ] All seven service functions + login implemented; BR1-BR8 enforced only in `service.py`.
- [ ] All HTML pages work in a browser; semantic HTML; error notice area; no agent-specific attributes.
- [ ] JSON API returns the same fields as the pages and the same error messages.
- [ ] Parity tests: every business rule tested once via HTML routes and once via `/api`, same outcome and same message.
- [ ] `reset.py` restores the exact initial state (test: modify state, reset, compare) and applies pre-filled carts.
- [ ] `state_reader.py` is read-only (test: write attempt fails).

### M2 Agent core
- [ ] Ollama client returns text, input/output tokens, duration; image input works.
- [ ] Prompt has the five sections; previous observations are not repeated.
- [ ] Parser accepts valid actions and marks everything else invalid (unit tests with bad JSON, unknown action, wrong arg types).
- [ ] Loop enforces S1-S5 (unit tests with a fake model and a fake pipeline).
- [ ] Exactly one action per invocation.

### M3 Pipelines
- [ ] Common interface + statuses executed / rejected / invalid / error.
- [ ] DOM: reduced tree with refs, stale-ref detection, load-event wait, truncation rule; example observation saved in `docs/`.
- [ ] Visual: viewport screenshot only, input events only, off-screen -> invalid, coordinate conversion checked with a test click, screenshots saved.
- [ ] Tool: seven tools from `tool_schemas.json`, schema validation, rejected vs invalid correctly separated.
- [ ] Fresh browser context per run with the session cookie; agent never sees the login page.
- [ ] Smoke test: one C1 task end-to-end with the real model in all three pipelines; trace written; verifier result printed.

### M4 Tasks
- [ ] 28 task files (7 categories x 4), pipeline-neutral instructions.
- [ ] `goal_states.py` fills C2-C4 goal states and fails on ties.
- [ ] Reference solutions for every task and pipeline; `validate_tasks.py` passes 100 % with action counts below S2.

### M5 Evaluation framework and runner
- [ ] Verifier: cart, order, invariant checks; differences list; false completion flag; unit tests for success and each failure type.
- [ ] Trace JSONL + `runs.csv` exactly as specified; screenshots for visual runs.
- [ ] Timer boundaries exclude reset, login, verification.
- [ ] `config_record.json` complete.
- [ ] Runner: shuffled with seed, warm-up, resumable, S5 retries, `run-one` command.
- [ ] Pilot: 1 repetition of all tasks in all pipelines runs without crashes; report durations so we can choose R.

### M6 Analysis
- [ ] `metrics.py` produces a table per pipeline / category / level with all metrics and Wilson CIs.
- [ ] `stats.py` runs Friedman + Wilcoxon (Holm) on per-task values.
- [ ] `plots.py`: success rate per pipeline and category; tokens and time per pipeline (box plots).
- [ ] `auto_labels.py` + `labels.csv` + `viewer.py` work on the pilot data.
- [ ] README explains the full workflow from installation to final tables.

### Final deliverables for the thesis
- [ ] `docs/thesis_notes.md` with versions, hardware, decisions, deviations, challenges.
- [ ] Two screenshots: search results page and cart page (thesis Figure 4.2).
- [ ] Final code for the listings in Chapter 4: `add_to_cart` service function, pipeline interface, one DOM observation, `add_to_cart` tool schema, one task file, verifier cart check, trace events, plan file.

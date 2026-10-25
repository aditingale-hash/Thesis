# Thesis fill-in: values, listings and text corrections for Chapters 3 and 4

Everything below is taken from the code and configuration on this branch. Values marked
*(experiment host)* must be taken from `results/<experiment>/config_record.json` after the
real experiment, because the development environment is not the experiment machine.

## 1. Does the prototype satisfy the requirements (Section 2.1)?

| Requirement | Rating | Evidence in the prototype |
|---|---|---|
| FR-EXEC | ● | The same 28 tasks, initial states, goal states and verifier are used for DOM, visual and tool. Only the pipeline differs (`evaluation/runner.py`, `pipelines/`). |
| FR-STATE | ● | All task types change state: adding (C1-C4), changing quantities (C5), correcting a pre-filled cart (C6), checkout (C7). All 84 reference solutions (28 tasks x 3 pipelines) reach the goal state (`python -m evaluation.validate_tasks`). |
| FR-VERIFY | ● | `evaluation/verifier.py` reads `shop.db` read-only after every run and decides success automatically from the cart and order state. `finish` alone never counts as success; finishing without success is recorded as false completion. |
| FR-MEASURE | ● | For every run: success, interaction actions, model invocations, execution time (agent loop only; reset, login and verification excluded) and tokens (counted by Ollama), with the same definitions in all pipelines (`evaluation/trace.py`, `runs.csv`). |
| NF-REP | ● after the real runs | `config_record.json` stores hardware, OS, Python and package versions, Ollama version, model name and digest, git commit, SHA-256 of the catalogue, every task file, the prompt template, tool schemas, DOM script, limits, model configuration and plan. Temperature 0, fixed seed, reset to a snapshot before every run, run order shuffled with a fixed seed. |

Objectives: O2 (shop), O3 (three pipelines), O4 (28 tasks, simple to complex), O5 (all pipelines,
one model configuration, full traces, failure labels) and O6 (metrics, statistics, plots, error
analysis) are implemented. O1 is the literature review. The quantitative results for Chapter 5
come from the pilot and main experiment on the experiment host.

## 2. Values for the TODOs in Chapter 4

| Place | Value |
|---|---|
| 4.2.2 catalogue | 80 products in 8 categories (Mice, Keyboards, USB Hubs, Laptop Bags, Notebooks, Desk Lamps, Headsets, Webcams) |
| Table 4.1 model runtime | Ollama (confirmed) |
| Table 4.1 perception component | not used: the model accepts images (`perception: none`) |
| Table 4.1 tool transport | HTTP requests to the shop's JSON interface (no MCP) |
| 4.2.4 reset | snapshot file about 68 KB; copying takes about 1 ms on the development machine *(re-measure on the experiment host)* |
| 4.4.2 viewport | 1280 x 800 pixels (same for both browser pipelines) |
| 4.4.3 scroll | 600 pixels per `scroll(direction)` |
| 4.4.3 variant | (a) the screenshot is passed to the multimodal model; coordinates are pixels of the 1280x800 screenshot (`coordinate_mode: pixels`); alternative `normalized_1000` (0-1000 on both axes, converted by the pipeline) if the smoke test shows the model uses that |
| Table 4.3 model and version | `qwen2.5vl:3b` (Qwen2.5-VL, 3 billion parameters) *(digest: config_record.json)* |
| Table 4.3 image input | yes |
| Table 4.3 quantization | Q4_K_M (Ollama default tag) *(confirm in config_record.json, model details)* |
| Table 4.3 context window | 16384 tokens |
| Table 4.3 temperature / seed | 0 / 42 |
| Table 4.3 max output tokens | 512 |
| Table 4.4 S2 / S3 / S4 | 25 invocations / 3 consecutive invalid actions / 600 s |
| Table 4.2 | CPU, GPU, RAM, OS, Python, Ollama, Playwright/Chromium, FastAPI/SQLite *(experiment host: config_record.json)*. Development versions: Python 3.13, Playwright 1.56.0 with Chromium 141, FastAPI 0.159.1, SQLite 3.45 |
| Fig. 4.1 | shop server, model runtime, experiment process and headless Chromium run as separate processes on one host (as drawn); start the shop with `python -m uvicorn shop.app:app --port 8000` |
| Fig. 4.2 | `docs/figures/search_results.png` and `docs/figures/cart.png` |
| 4.3.2 appendix ref | prompt template: `agent/prompt_template.txt` |
| 4.3.3 context budget | estimated, because there is no tokenizer for every model: prompt characters / 3.5, a screenshot counts as 1,400 tokens (Qwen2.5-VL uses 28x28-pixel patches, about 1,330 for 1280x800); budget = context window - max output tokens; if exceeded, the pipeline truncates the current observation and the step is marked `truncated` in the trace. The real token counts reported by Ollama are what is measured. |

## 3. Text corrections (code and thesis differ; the code is the intended design)

1. **3.4.2 Actions and Table 3.6.** Remove `select(ref, option)`. Suggested sentence: *"The shop
   contains no drop-down selection fields; category filter and sort order are links. A native
   drop-down list is not visible in screenshots, so a drop-down would give the DOM pipeline
   information the visual pipeline cannot see (DP3). The DOM action space therefore consists of
   click(ref), type(ref, text), go_back() and finish()."*
2. **3.4.4 Observation.** "a search result lists the identifier, name, **category**, price, rating,
   availability, and badge of each product".
3. **4.2.2.** Keep "Product images show only a neutral category symbol". Add: *"Cart lines show one
   generic product symbol, because cart items carry no category."*
4. **4.2.3 page types.** Add: *"A login page and a registration page also exist. The agent never
   sees them, because the runner establishes the session before a run."*
5. **Listing 4.5.** The real schema has **no** `"minimum": 1`. Suggested sentence: *"The schema
   checks only types and the allowed values of enumerations. Value ranges such as the permitted
   quantity are business rules (BR3) and are checked only by the application core, so an
   out-of-range quantity is rejected with the same message in all three pipelines instead of being
   invalid only in the tool pipeline."*
6. **Listing 4.3 / Fig. 3.5.** The interface has two more methods: `action_specs()` (action names
   and argument types for the action parser) and `truncate(observation, max_chars)` (the pipeline's
   truncation rule).
7. **3.4.3 Actions and Table 3.6 (visual typing).** The visual action is now `type(target, text)`.
   Suggested text: *"type(target, text) clicks the target position, selects the content of the field
   and enters the text, using input events only. Like type(ref, text) in the DOM/accessibility
   pipeline, it names its target and replaces the content in one action; it does not submit the
   form."* Reason, for 4.8: in the first smoke tests the model typed 25 times without first
   clicking a field, because the separate focusing step did not exist in the other pipelines.
   Table 3.6, column Visual: Search = "type at search field, press Enter"; Change quantity =
   "type at quantity field, click 'Update'".
8. **4.3.2 decision to confirm with the supervisor.** The prototype uses the common JSON action
   format in all pipelines (no native function calling), to keep the agent core identical (DP1).
   The JSON schema given to the runtime is built from each pipeline's action space (allowed
   action names, exact arguments and types, fixed value lists). Suggested sentence: *"The
   structured-output schema is derived from the action space of the active pipeline, so the
   runtime only produces actions and arguments that exist in that pipeline. Format errors such as
   a list instead of an element reference are therefore excluded in all conditions alike, and the
   comparison concerns the choice of actions rather than the output format."*

## 4. Listings (final code)

### Listing 4.1: `add_to_cart` service function (`shop/service.py`)
```python
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
```

### Listing 4.3: common pipeline interface (`pipelines/base.py`)
```python
class InteractionPipeline(ABC):
    """One interaction approach (DOM, visual or tool)."""

    name: str = ""

    @abstractmethod
    def attach(self, session) -> None:
        """Connect to the shop for one run (``session``: base_url, cookie, browser, run_dir)."""

    @abstractmethod
    def action_space(self) -> str:
        """Text for prompt section 2."""

    @abstractmethod
    def action_specs(self) -> dict:
        """Action names and argument types, used by the action parser (includes finish)."""

    @abstractmethod
    def observe(self) -> Observation:
        """Current observation."""

    @abstractmethod
    def execute(self, action: Action) -> ActionResult:
        """Perform one (already parsed) action."""

    def truncate(self, observation: Observation, max_chars: int) -> str:
        """Shorten the text observation to ``max_chars``; pipelines override with their own rule."""
        return observation.prompt_text[:max_chars]

    def close(self) -> None:
        """Release browser contexts / HTTP clients."""
```

### Listing 4.4: part of a DOM observation (`docs/dom_observation_example.txt`, search for "mouse m2")
```text
Page title: Search results - TechDesk Shop
URL: http://127.0.0.1:8000/search?q=mouse+m2
  [1] link "TechDesk Shop"
    [2] searchbox "Search products" value="mouse m2"
    [3] button "Search"
    [4] link "Cart"
    heading "Categories"
      [5] link "All categories" (current)
      [6] link "Mice"
      [7] link "Keyboards"
      [8] link "USB Hubs"
      [9] link "Laptop Bags"
      [10] link "Notebooks"
      [11] link "Desk Lamps"
      [12] link "Headsets"
      [13] link "Webcams"
    heading "Sort by"
      [14] link "Price: low to high"
      [15] link "Price: high to low"
      [16] link "Rating: high to low"
  heading "Search results"
  text "4 products found for 'mouse m2'."
  listitem
    text "Bestseller"
    text "Mice"
    [17] link "Wireless Mouse M2"
    text "Rating: 3.9 / 5"
    text "19.99 EUR"
    text "Available"
  listitem
    text "Mice"
    [18] link "Wireless Mouse M2 Pro"
    text "Rating: 4.6 / 5"
    text "34.90 EUR"
    text "Available"
  ...
```

### Listing 4.5: schema of the tool `add_to_cart` (`pipelines/tool_schemas.json`)
```json
{
  "name": "add_to_cart",
  "description": "Add a quantity of a product to the cart. Returns the cart.",
  "parameters": {
    "type": "object",
    "properties": {
      "product_id": {
        "type": "integer"
      },
      "quantity": {
        "type": "integer"
      }
    },
    "required": [
      "product_id",
      "quantity"
    ],
    "additionalProperties": false
  }
}
```

Other listings for Chapter 4: a task file (`evaluation/tasks/C4-01.json`), the verifier cart check
(`check_cart` in `evaluation/verifier.py`), the trace events (`evaluation/trace.py`) and the plan
file (`config/plan.yaml`).

## 5. Material for the "Phase 2" sections

| Thesis section | Source in `docs/thesis_notes.md` and the code |
|---|---|
| 3.5 / 4.5 Task specification and task set | D22; `evaluation/tasks/*.json`, `evaluation/goal_states.py` |
| 3.6 / 4.6 Evaluation framework | D23, D24; `evaluation/verifier.py`, `evaluation/trace.py`, `evaluation/labelling/auto_labels.py` |
| 3.7 Experimental protocol | D23 (seeded shuffle, warm-up, S5 retries and exclusion, resume); R is chosen after the pilot |
| 3.8 Requirement fulfilment | Section 1 of this file |
| 4.7 Experiment runner | D23; `evaluation/runner.py` |
| 4.8 Deviations and challenges | thesis_notes Sections 3 (Deviations) and 4 (Problems) |

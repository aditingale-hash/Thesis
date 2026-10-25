# Thesis prototype: web interaction approaches for SLM agents

Research prototype for the Master's thesis *"Comparing Existing Web Interaction Approaches with
Tool-Based Interaction for Small Language Model Agents"* (TU Chemnitz, VSR).

One agent, driven by one small language model running locally in Ollama, solves the same 28 shopping
tasks in the same web shop through three interaction pipelines:

| Pipeline | The model sees | The model acts with |
|---|---|---|
| `dom` | reduced accessibility tree of the page, elements numbered `[n]` | `click(ref)`, `type(ref, text)`, `go_back()` |
| `visual` | a 1280x800 screenshot only | `click(x, y)`, `type(text)`, `press(key)`, `scroll(direction)`, `go_back()` |
| `tool` | JSON result of the last function call | 7 shop functions (`search_products`, `add_to_cart`, ...) |

Everything else (task, initial state, shop, model settings, prompt, loop, limits, verification,
measurement) is identical. The full specification is in [`CLAUDE.md`](CLAUDE.md); all decisions,
deviations and problems are logged in [`docs/thesis_notes.md`](docs/thesis_notes.md).

## 1. Install

Python 3.11+ (tested with 3.13). On Windows use `python`, on Linux/macOS `python3`.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows   (Linux/macOS: source .venv/bin/activate)
python -m pip install -e ".[dev]"
python -m playwright install chromium
```

Install **Ollama** (https://ollama.com) and download the model set in `config/model.yaml`:

```bash
ollama pull qwen2.5vl:3b
```

Keep the project folder outside OneDrive/Dropbox: they lock `shop.db` while syncing.

## 2. The shop

```bash
python -m shop.build_db                       # catalogue.json -> shop/snapshot.db
python -m shop.reset                          # snapshot.db -> shop/shop.db
python -m uvicorn shop.app:app --port 8000    # http://localhost:8000  (login: testuser / testpass)
```

Keep this server running during experiments: the runner uses it (`shop_url` in `config/plan.yaml`).

- Pages: `/login`, `/register`, `/`, `/search`, `/products/{id}`, `/cart`, `/checkout`. You can create your
  own account at `/register`; every reset deletes all accounts except `testuser`.
- JSON API (what the tool pipeline calls):

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

### Product photos (once, on your own computer)

The shop shows `shop/static/products/<id>.jpg` when it exists, otherwise a category illustration.
To download freely licensed photos from Wikimedia Commons (about 10-15 minutes):

```bash
python -m pip install -e ".[photos]"
python -m shop.tools.fetch_photos
```

Open `shop/static/products/review.html` and check every photo: no brand logos, no readable text,
no prices, right product type. Replace bad ones (repeat until all are fine):

```bash
python -m shop.tools.fetch_photos --next 101 205
```

Then commit the photos (`git add shop/static/products`), so every experiment uses the same images.
Authors and licences are listed in `shop/static/products/CREDITS.md`.

## 3. Tasks

28 tasks in `evaluation/tasks/` (7 categories x 4). Goal states of the constraint tasks are computed from
the catalogue; check that every task works in every pipeline without the model:

```bash
python -m evaluation.goal_states --check      # goal states up to date, no ties
python -m evaluation.validate_tasks           # runs all 84 reference solutions (about 2 minutes)
```

## 4. Run the experiment

First start the shop in a second terminal and leave it running (the plan's `shop_url` points to it,
so the shop runs as its own process, as in the thesis deployment):

```bash
python -m uvicorn shop.app:app --port 8000
```

Configuration: `config/model.yaml` (model, context, seed, coordinate system), `config/limits.yaml`
(S2-S4), `config/plan.yaml` (tasks, pipelines, repetitions, seed, retries). Ollama must be running.

```bash
# one task in one pipeline, for debugging (results/debug/); prints every step at the end
python -m evaluation.runner run-one --task C1-01 --pipeline dom
# the same with a visible, slowed-down browser window, to watch the agent (timings not comparable)
python -m evaluation.runner run-one --task C1-01 --pipeline dom --show

# the whole plan (results/<experiment>/); safe to stop and start again: finished runs are skipped
python -m evaluation.runner run --plan config/plan.yaml

# without Ollama: a stub model that always answers "finish" checks the whole chain (not an experiment)
python -m evaluation.runner run-one --task C1-01 --pipeline visual --stub
```

Every step is printed while a run is going. One model call can take 5-30 s (the first one
longer, while Ollama loads the model); only press Ctrl+C if nothing has been printed for several
minutes, and then check that Ollama is running. After Ctrl+C, the same command continues.

Output per experiment in `results/<experiment>/`:
- `config_record.json`: versions, model digest, hardware, git commit, SHA-256 of all inputs
- `runs.csv`: one summary row per run
- `<run_id>/trace.jsonl`: every model call and action; `<run_id>/step_<n>.png`: screenshots (visual)

Recommended order: smoke test (`run-one` for C1-01 in all three pipelines), then the pilot
(`plan.yaml` as delivered: all tasks, 1 repetition), then choose the number of repetitions R
from the pilot durations and run the main experiment under a new `experiment` name.

## 5. Analyse

```bash
python -m evaluation.analysis.metrics results/pilot     # tables per pipeline / category / level
python -m evaluation.analysis.stats results/pilot       # Friedman + Wilcoxon (Holm) on per-task values
python -m evaluation.analysis.plots results/pilot       # success rates, tokens, time
python -m evaluation.labelling.auto_labels results/pilot          # labels.csv for failed runs
python -m evaluation.labelling.viewer results/pilot C4-01_dom_r1  # one run step by step
```

Tables, test results and figures are written to `results/<experiment>/analysis/`. For manual
labelling, open `labels.csv`, look at runs with the viewer and fill in `final_label` and `note`;
re-running `auto_labels` keeps what you entered.

## 6. Tests

```bash
python -m pytest            # about 4 minutes; includes headless Chromium and all reference solutions
```

The browser tests also write the thesis figures `docs/figures/search_results.png` and `cart.png` and the
example DOM observation `docs/dom_observation_example.txt`.

## Layout

```
shop/          FastAPI shop: service.py (all business rules), HTML + JSON API, reset, read-only state reader
agent/         Ollama client, 5-section prompt, action parser, history, control loop (S1-S5)
pipelines/     common interface + DOM (dom_extract.js), visual, tool (tool_schemas.json)
evaluation/    tasks, goal states, reference solutions, verifier, traces, runner, analysis, labelling
config/        model.yaml, limits.yaml, plan.yaml
docs/          thesis_notes.md, figures, example DOM observation
```

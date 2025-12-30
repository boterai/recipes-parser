# Copilot / AI agent instructions for Recipe Parser 🧾🍳

Short, actionable guidance to help an AI coding assistant be productive in this repository.

## Big picture
- Purpose: crawl recipe websites (via Selenium), detect pages with recipes, extract structured recipe data, store it in DBs (MySQL / ClickHouse) and index in Qdrant for semantic search.
- Major components:
  - `scripts/` — high-level runnable scripts (e.g. `parse.py`, `prepare_site.py`, `translate.py`, `vectorize.py`).
  - `src/stages/parse/` — site exploration & scraping logic using Selenium (`explorer.py`, `auto_scraper.py`).
  - `extractor/` — per-site extractor modules: one `.py` per site (see conventions below).
  - `src/stages/extract/` — extractor factory (`RecipeExtractor`) that loads extractors and updates `Page` objects.
  - `src/common/` — shared utilities (GPT client, embeddings, DB connectors).
  - `parsed/`, `extracted_recipes/`, `logs/` — runtime output directories.

## Quick start & developer workflows
- Start Chrome in debug mode (examples used across scripts):
  - google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug_9222
- Run one parser (attach to Chrome on port 9222):
  - `python scripts/parse.py --modules 24kitchen_nl --ports 9222`
- Run parallel parsers on multiple ports:
  - Launch multiple Chrome instances on different ports, then `python scripts/parse.py --parallel --ports 9222 9223 9224`
- Prepare sites (DuckDuckGo + detection):
  - `python scripts/prepare_site.py --ports 9222`
  - Options: `--min-sites`, `--parallel`.
- Translate and push to ClickHouse:
  - `python scripts/translate.py` (see `scripts/translate.py` for examples).
- Vectorize / search with Qdrant:
  - `python scripts/vectorize.py` (see `get_embedding_function` in `src/common/embedding.py` for batch sizing and model choices).

## Environment & infra (must-haves in .env)
- GPT_API_KEY — required for any GPT-driven flows (query generation, translations).
- MYSQL_HOST/PORT/USER/PASSWORD/DATABASE — used by SQLAlchemy repos (see `config/db_config.py`).
- CLICKHOUSE_* and QDRANT_* — if using translation / vector search pipelines.
- PROXY (optional) — used by GPT client and Qdrant if needed.

## Project-specific conventions & patterns (very important)
- Extractors:
  - Location: `extractor/<site_module>.py`.
  - Module name must match `Site.name` (the repo uses DB mapping that maps site id → filename). See `RecipeExtractor._get_extractor_module_name`.
  - Class naming: contain `Extractor` in the class name (e.g. `AllRecipesExtractor`); factory finds the first class with `Extractor` in its name.
  - Base class: inherit `extractor.base.BaseRecipeExtractor` and implement `extract_all()` (helper functions available like `clean_text` and `process_html_file`).
  - Prefer extracting `dish_name`, `ingredients`, `instructions` as these are used to decide `is_recipe`.
- GPT usage:
  - `src/common/gpt_client.py` wraps requests; it expects the assistant to return **strict JSON** (no markdown or code fences). The code normalizes common JSON issues but prefer returning valid JSON.
  - Example: `SearchQueryGenerator` expects a JSON array of strings (no extra text).
  - Keep responses compact and exactly in the shape caller expects; follow system prompts used in those modules.
- Embeddings:
  - `src/common/embedding.py` provides `get_embedding_function` / `get_image_embedding_function`.
  - Large models (e.g., `BAAI/bge-large-en-v1.5`) may need manual download/cache setup; use the function docs for advice on cache locations and batch sizes.
- DB access:
  - Repositories use a singleton MySQL manager (`src/common/db/connection.py`) — prefer using repository APIs (`SiteRepository`, `PageRepository`) rather than raw SQL where possible.

## Where to make changes / common tasks
- Add a new extractor: create `extractor/<new_site>.py`, implement `<Name>Extractor(BaseRecipeExtractor)` and `extract_all`, make sure `Site.name == '<new_site>'` in DB or create it via `SiteRepository.create_or_get`.
- Debugging an extractor with local HTML: use helpers in `extractor/base.py`: `process_html_file(MyExtractor, 'sample.html')` to generate extracted JSON next to HTML.
- If adding GPT-driven generators (queries / translations), follow the strict JSON-return rules and mirror patterns in `search_query_generator.py`.

## Common pitfalls & debugging tips
- "Chrome not running on port X" — see `explorer.connect_to_chrome()` error message: ensure Chrome started with the correct remote debugging port or pass `--debug_port` to scripts.
- Large embedding models can OOM: reduce `batch_size` in vectorization scripts (`scripts/vectorize.py` and `get_embedding_function`).
- If GPT returns non-JSON or code fences, functions often fail JSON parsing — check `gpt_client._clean_markdown` / `_normalize_json` and prefer returning raw JSON.
- Logs are written to `logs/` and per-thread log files like `logs/<module>_<port>.log` — check them for per-run details.

## Useful files to inspect (examples)
- `scripts/parse.py` — how to run single/parallel parsing and example module/ports mapping
- `src/stages/parse/explorer.py` — Selenium exploration, saving pages to `parsed/`, `save_page_as_file()` behavior
- `src/stages/extract/recipe_extractor.py` — dynamic extractor loader and naming conventions
- `src/common/gpt_client.py` & `src/stages/parse/search_query_generator.py` — GPT integration and expected JSON formats
- `src/common/embedding.py` — embedding models, batching guidance, CPU/GPU considerations
- `config/db_config.py` — required env vars for DB and Qdrant

---
If anything in the above is unclear or you'd like me to expand a section (e.g., more examples for adding extractors, a short PR checklist, or exact run commands for common debug workflows), tell me which section to iterate on.
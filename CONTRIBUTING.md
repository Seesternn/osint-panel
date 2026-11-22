# Contributing

Thanks for helping! Bug reports, new sources, translations and fixes are all welcome.

## Ground rules

OSINT Panel only uses **public, lawful sources**. Pull requests that add any of the following will be closed:

- leaked / breached databases or "combo lists" (HIBP-style *lookups* through official APIs are fine)
- identity, address or phone-owner lookup panels (e.g. national ID panels)
- face recognition of private individuals
- logging into accounts you don't own, bypassing logins, CAPTCHAs or rate limits

## Development setup

```bash
./setup.sh --minimal                 # or the full setup
pip install -r requirements-dev.txt  # inside .venv: .venv/bin/pip …
.venv/bin/python -m pytest           # offline unit tests
.venv/bin/ruff check panel tests
./run_panel.sh                       # http://127.0.0.1:5050
```

Tests never touch your real settings or cases (they use a temporary `OSINT_DATA_DIR`) and never use the network.

## Adding a source: write a plugin

Most new sources should be a plugin — one Python file, no changes to the core.

1. Copy [`docs/plugin-template.py`](docs/plugin-template.py) to `panel/plugins/<name>.py`
   (bundled) or to your user plugin folder (`$OSINT_PLUGIN_DIR`, default `<data dir>/plugins_user`).
2. Fill in `PLUGIN`: `id`, `title`, `group`, `fields`, `run` and, to join Smart search, `accepts`.
3. Use `L(job, "Türkçe", "English")` for every text you emit, and add an `en` block for the title,
   description and field labels, so the plugin works in both languages.
4. Restart the panel. Broken plugins are skipped and listed at `/api/catalog` → `plugin_errors`.

Plugin API reference: the docstring at the top of [`panel/plugin_api.py`](panel/plugin_api.py).
Good examples: [`gaming.py`](panel/plugins/gaming.py) (simple), [`favicon.py`](panel/plugins/favicon.py) (pivot links),
[`opencorporates.py`](panel/plugins/opencorporates.py) (optional API key + settings field).

Please respect each source's terms and rate limits (timeouts, small page sizes, no parallel hammering).

## Translations

The interface is written in Turkish and translated at runtime. To translate a new UI string, add it to
[`panel/static/i18n_en.js`](panel/static/i18n_en.js) (`phrases` for fixed text, `patterns` for text with
numbers or names). Tool help texts live in [`panel/about_en.py`](panel/about_en.py).

## Pull requests

- One topic per PR, with a short description of what and why.
- Add or update tests in `tests/` when you change detection, merging, parsing or the API.
- CI must be green (lint, tests, JS/shell syntax, Docker build).
- Don't commit personal data, API keys, screenshots of real people's private profiles, or local notes.

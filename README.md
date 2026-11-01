# MarkSort

Collect what you saved across platforms, normalise it into one shape, and
browse it as a local site.

Sources are plugins. Adding a platform means adding one directory; the web
UI never learns a platform name.

## How it works

```
source plugin  ──►  Item (one contract)  ──►  sink / web UI
      │
      └─ enricher plugin (classification, summaries)
```

* **source** — fetches a platform and yields `Item` objects
* **enricher** — transforms items in place (category, summary)
* **sink** — writes items somewhere (JSON file, database)

`Item` carries the media shape, so playback is decided by `media.kind`
(`iframe` / `video` / `image` / `none`) instead of the platform name.

## Requirements

* Python 3.12, managed with [uv](https://docs.astral.sh/uv/)
* Node 20+ (frontend only)

## Quick start

```bash
uv sync                                  # create .venv, install deps
uv run python -m marksort serve           # local API on 127.0.0.1:17331

cd marksort/website
npm install
npm run dev                               # UI on http://localhost:5173
```

Then in the UI: **Settings** → fill credentials → *Fetch to data/unified.json* → **Images** → start sync.

## Configuration

Settings come in two layers, merged field by field:

| File | Tracked | Purpose |
|---|---|---|
| `settings.default.json` | yes | template: plugin keys, defaults, doc comments |
| `settings.local.json` | no | your values; gitignored |

Any string can read the environment with `${env:NAME}` or
`${env:NAME:-fallback}`, so credentials can stay out of files entirely.

| Source | Required fields |
|---|---|
| `bilibili` | `up_mid`, `sessdata` |
| `rednote` | `user_id`, `a1`, `web_session` (`web_id` optional) |

## CLI

```bash
uv run python -m marksort selftest              # kernel self-check, no network
uv run python -m marksort plugins list          # discovered plugins
uv run python -m marksort plugins show rednote  # contract + config JSON Schema
uv run python -m marksort config check          # validate settings against schemas
uv run python -m marksort fetch --out data/unified.json
uv run python -m marksort serve --port 17331
```

## HTTP API

| Endpoint | Purpose |
|---|---|
| `GET /api/items` | the fetched dataset |
| `GET /api/settings` | merged settings, plugin schemas, validation errors |
| `POST /api/settings` | merge a patch into `settings.local.json` |
| `POST /api/fetch` | run enabled sources, write the output file |
| `GET /api/image?u=<url>` | image proxy with per-host Referer and disk cache |
| `POST /api/sync/start` | background image download (`delay_ms`, `workers`, `kinds`) |
| `GET /api/sync/status` | progress, rate, ETA, recent errors |
| `POST /api/sync/stop` | stop the running sync |

## Writing a plugin

A plugin is a module. Drop `marksort/plugins/<name>/plugin.py`:

```python
from marksort.core.item import Item, Media
from marksort.core.schema import Schema

name = "example"
kind = "source"
version = "0.1.0"
description = "Example source"
inject = ["log"]                 # kernel services this plugin needs

config = {
    "token": Schema.string().secret().required().describe("API token"),
    "limit": Schema.integer().default(50).minimum(1),
}

async def fetch(ctx, cfg):
    log = ctx.service("log")
    for row in _read_something(cfg["token"], cfg["limit"]):
        yield Item(
            platform="example",
            external_id=row["id"],
            title=row["title"],
            url=row["url"],
            media=Media(kind="none"),
        )
```

Entries: `fetch` for sources (async generator), `enrich` for enrichers,
`write` for sinks. The loader rejects a plugin whose entry is not async,
whose `kind` is unknown, or whose `config` is not a `Schema` table.

External plugin directories are supported: `--plugin-path <dir>`.

## Layout

```
marksort/
  core/        # kernel: Item contract, config schema, plugin loader,
               # container, pipeline, local server, image sync
  plugins/     # source_bilibili, source_rednote, source_demo
  browser/     # in-page snippets (fetch from a logged-in tab)
  website/     # React SPA: feed, settings, image sync
settings.default.json
pyproject.toml
```

## Implementation notes

* Bilibili items play inline as an `iframe` (`aid`/`bvid`/`p`). Xiaohongshu
  has no embeddable player, so its items are `media.kind = "none"` and link
  to the original post.
* Xiaohongshu returns 10 items per request regardless of `num`; the source
  pages with a 2s delay and exponential backoff when the API answers
  `code=-3`.
* Image CDNs check `Referer`, so covers are proxied instead of loaded
  directly. The proxy caches to `data/cache/images/`.
* Images are pulled once by the sync job, not while scrolling; the UI only
  requests covers near the viewport.
* Feeds append in batches of 24 on scroll. There is no classic pagination.

## Not implemented yet

* `enricher` plugins (category / summary) — the pipeline supports them, no
  plugin ships yet
* production build is served by Vite only; `serve` exposes the API, not the
  built assets

## License

MIT

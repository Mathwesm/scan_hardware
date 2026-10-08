# Hardware Scanner

Standalone Python service that reads printed motherboard, GPU, and CPU identifiers from a photo, then looks up the matching catalog record and its reference image. No external backend or database is required: the service stores catalog records in SQLite and optional reference images on local disk.

## How it works

1. The client takes a clear photo of the printed model or part number.
2. `POST /scan` runs offline OCR and normalizes punctuation and letter case.
3. Exact identifier matches are returned as `matched`. Similar values are returned as `suggestions`; they are **never** silently treated as exact matches.
4. Each match includes the catalog item, its identifiers, the observed text, the score, and a reference image URL when available.

The matching key is a **printed alphanumeric identifier**, not an image classification of the entire board. A catalog importer is included for the two Kaggle datasets described below.

## Run locally

Requires Python 3.12 and Poetry 2.x. The OCR models ship with the Python package and run locally with ONNX Runtime.

```bash
poetry install
poetry run python -m scan_hardware
```

Open `http://127.0.0.1:8000/docs` for the interactive API. Without an import, the default database is `data/catalog.sqlite3`. After a successful import, the service follows `data/latest.json` to the latest validated, versioned database. An explicit `CATALOG_PATH` overrides this pointer. Set other values in `.env` using `.env.example` as a template.

## Import the Kaggle catalog

Download the full public archives [PC Parts by Type](https://www.kaggle.com/datasets/rohitmit98/pc-parts-by-type) and [PC Parts](https://www.kaggle.com/datasets/warcoder/pc-parts), then run:

```bash
poetry run python -m scan_hardware.catalog_import \
  --rohit "data/raw/kaggle/pc-parts-by-type.zip" \
  --warcoder "data/raw/kaggle/warcoder-pc-parts.zip"
```

On PowerShell, put the command on one line or use PowerShell's continuation syntax. The importer reads the CPU, GPU, and motherboard files from both complete archives, keeps every original column in SQLite, and records rejected rows with their reason. It joins products only when their normalized model or part code matches exactly; GPU names shared by different chipsets remain separate. An image URL is attached only when the source contains a plausible product photo URL and, for an ambiguous GPU name, the chipset also matches. Placeholder references are discarded. Import runs create separate databases under `data/processed/<run-id>/` and update `data/latest.json` only after count, rejection-rate, and image-reference checks pass. Both archives and all generated databases remain outside Git.

For an identified item, call `GET /items/{id}/sources` to retrieve every original source row and its specifications. The ordinary `/scan` and `/lookup` responses stay small. Re-running an import creates a new version and preserves the previous one. A future source refresh should be audited before changing the pointer.

The image URLs come from third-party hosts in the Kaggle data. They are not local image files or guaranteed to remain available; the dataset license does not establish reuse rights for those photographs. Items without a reliable image reference remain searchable with `image_url: null`. Manufacturer or separately licensed product images can be added through the existing image upload endpoint.

Docker is also supported:

```bash
docker compose up --build
```

The Docker port is bound to `127.0.0.1:8000`. Keep that binding or add authentication at the reverse proxy before exposing catalog write endpoints publicly.

## Try the complete flow

Register a demonstration motherboard (the values below are test data):

```bash
curl -X PUT http://127.0.0.1:8000/items/demo-board \
  -H "Content-Type: application/json" \
  -d '{"category":"motherboard","brand":"Demo","model":"B550-F Gaming","identifiers":["B550-F GAMING"]}'
```

Search text that a mobile camera has already decoded:

```bash
curl -X POST http://127.0.0.1:8000/lookup \
  -H "Content-Type: application/json" \
  -d '{"text":"B550 F GAMING"}'
```

Upload a photo of the printed identifier:

```bash
curl -X POST http://127.0.0.1:8000/scan -F "image=@label.jpg"
```

Attach a reference image and retrieve it:

```bash
curl -X PUT http://127.0.0.1:8000/items/demo-board/image -F "image=@board.jpg"
curl http://127.0.0.1:8000/items/demo-board/image --output board-reference.jpg
```

`POST /scan` returns a response like:

```json
{
  "status": "matched",
  "detected_text": ["B550-F", "GAMING"],
  "matches": [
    {
      "item": {
        "category": "motherboard",
        "brand": "Demo",
        "model": "B550-F Gaming",
        "identifiers": ["B550-F GAMING"],
        "image_url": null,
        "id": "demo-board",
        "has_local_image": true,
        "local_image_url": "/items/demo-board/image"
      },
      "matched_identifier": "B550-F GAMING",
      "observed_text": "B550-F GAMING",
      "score": 1.0,
      "is_exact": true
    }
  ]
}
```

`status` is `matched`, `suggestions`, or `not_found`. An empty catalog always returns `not_found`. The service accepts JPEG, PNG, and WebP uploads up to 8 MB and 20 megapixels.

## Integration contract

The mobile app can send an image to `/scan` or decoded text to `/lookup`. The service returns JSON only; the app renders the item details and downloads `local_image_url` when present. `PUT /items/{id}` is idempotent, so a future backend sync can safely repeat writes. Normalize stable IDs in the backend before sending them here; IDs may contain letters, digits, underscores, and hyphens.

The imported Kaggle data has no explicit release-year field, so historical decade coverage has not been verified. OCR quality on etched text, glare, tiny labels, and model revisions must be measured against real labeled photos before production use. The lookup currently loads the local catalog and ranks candidates in memory; benchmark it again if the catalog grows substantially.

## Quality checks

```bash
poetry run ruff format --check .
poetry run ruff check .
poetry run mypy src/
poetry run pytest -q
poetry run detect-secrets scan
```

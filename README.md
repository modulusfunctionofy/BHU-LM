# BHU-LM

BHU-LM is a modular Retrieval-Augmented Generation (RAG) system built for MediaWiki-style knowledge bases. It supports category-based ingestion, HTML cleaning, table-aware text chunking, versioned vector storage, hybrid retrieval, reranking, and optional multimodal processing.

The repository includes the backend pipeline in the root folder and a separate `frontend/` folder kept for UI reference and future integration.

---

## Quick edit map

If you only want to change a few things, edit these places:

* **Documents to fetch / category / processing settings** → `Master_embed.json`
* **Query / retrieval toggles / display limits** → `Master_retrieve.json`
* **HTML fetch stage** → `get_html.py`
* **HTML cleaning rules** → `clean_html.py`
* **Text chunking and embedding** → `RAG.py`
* **Text retrieval behavior** → `RAG_retrieve.py`
* **Image extraction and image retrieval** → `image_extraction.py`, `image_process.py`, `image_retrieve.py`
* **Frontend screenshots / UI visuals** → add them inside `frontend/screenshots/`

---

## Project structure

```text
repo-root/
├── clean_html.py
├── clean.py
├── get_html.py
├── image_extraction.py
├── image_process.py
├── image_retrieve.py
├── Master_count.json
├── Master_embed.json
├── Master_embed.py
├── Master_retrieve.json
├── RAG.py
├── RAG_retrieve.py
├── frontend/
│   ├── ...
│   └── screenshots/
└── README.md
```

---

## What the project does

BHU-LM follows a staged pipeline:

1. fetch MediaWiki pages
2. clean noisy HTML
3. extract and preserve useful structure such as tables
4. chunk and embed text into versioned databases
5. extract and process images for multimodal retrieval
6. retrieve relevant chunks using hybrid ranking and reranking
7. return structured results for downstream answer generation or UI display

---

## Storage structure

Storage is organized by **category** and **training set number**.

Example:

```text
wiki_html/
└── 1-Hostel/
    ├── battle_of_thermopylae.html
    ├── battle_of_thermopylae.txt
    └── processed_pages.json

cleaned_html/
└── 1-Hostel/
    ├── battle_of_thermopylae.html
    └── processed_cleaning.json

databases/
└── 1-Hostel/
    ├── 1chromadb/
    ├── 2chromadb/
    └── 3chromadb/

image_data/
└── 1-Hostel/
    ├── extracted/
    ├── processed/
    └── trackers/
```

### How the records are kept

* **Tracker JSON files** remember what has already been processed.
* **Versioned database folders** keep each training run isolated.
* **Set numbers** let you delete or replace one batch without touching the others.
* The same category can have many trained sets, and each set stays separate.

---

## Core scripts

### `get_html.py`

Fetches the raw MediaWiki HTML and source text for each page listed in the configuration. It also checks trackers so already processed pages are skipped.

### `clean_html.py`

Removes noisy layout components from the raw HTML and preserves the article content needed for downstream retrieval.

### `clean.py`

Utility cleanup script used to remove temporary files and keep the workspace tidy after processing.

### `image_extraction.py`

Extracts image assets from the source pages and tracks what has already been saved.

### `image_process.py`

Turns extracted images into searchable multimodal records for later image retrieval.

### `image_retrieve.py`

Retrieves images later using the saved image metadata and retrieval settings.

### `RAG.py`

Converts cleaned HTML into searchable text chunks, preserves useful tables, creates embeddings, and stores them in versioned ChromaDB collections.

### `RAG_retrieve.py`

Loads all available text databases for the chosen category, performs hybrid retrieval, optionally applies multi-query expansion, MMR, and reranking, and then returns the best chunks.

### `Master_embed.py`

Main orchestration script for the ingestion pipeline.

---

## Configuration files

### `Master_embed.json`

Controls ingestion-side behavior.

Typical fields:

```json
{
  "CATEGORY": "1-Hostel",
  "OPTION": 2,
  "PAGES_TO_PROCESS": [],
  "PAGES_TO_FETCH": [],
  "MAX_IMAGE_RETRIEVAL": 10,
  "HEADERS": {"User-Agent": "BHU-LM/1.0"},
  "CLASSES": ["sidebar", "navbox", "toc"]
}
```

Use this file to change:

* category
* pages to ingest
* text processing option
* image processing option
* cleanup settings
* page fetch settings

### `Master_retrieve.json`

Controls retrieval-side behavior.

Typical fields:

```json
{
  "QUERY": "Battle of Thermopylae Greek army table",
  "MMR": 0,
  "MULTI_QUERY": 1,
  "RERANKING": 1,
  "IMAGE_RETRIEVE": 0,
  "RETRIEVED_IMAGES_CHUNKS": 2,
  "MIN_CHUNKS": 3,
  "MAX_CHUNKS": 10
}
```

Use this file to change:

* retrieval query
* hybrid search behavior
* multi-query toggle
* reranking toggle
* MMR toggle
* number of chunks returned
* image retrieval toggle

### `Master_count.json`

Keeps the current set count for each category.

Example:

```json
{
  "1-Hostel": 1,
  "2-Academics": 2
}
```

This is used to keep database sets versioned.

---

## Recommended setup

* **Python 3.11**
* **Ollama** installed locally
* Playwright/Chromium for page rendering tasks

Install dependencies inside a virtual environment:

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip setuptools wheel
pip install playwright requests beautifulsoup4 chromadb llama-index llama-index-vector-stores-chroma llama-index-embeddings-ollama llama-index-llms-ollama unstructured sentence-transformers numpy pillow
playwright install chromium
```

If your local models are needed for processing, make sure Ollama is running before launching the pipeline.

---

## Typical workflow

### Ingestion

1. Edit `Master_embed.json`
2. Run `Master_embed.py`
3. The pipeline fetches, cleans, chunks, embeds, and stores data

### Retrieval

1. Edit `Master_retrieve.json`
2. Run `RAG_retrieve.py`
3. The pipeline returns the best text chunks
4. Run `image_retrieve.py` if image retrieval is enabled

---

## Frontend reference

A separate `frontend/` folder is included for UI reference and later integration.

Important note:

* it is currently a **reference UI**, not yet wired into the backend in this repository snapshot
* screenshots can be added later for documentation or presentation

### Add frontend screenshots here

Recommended folder:

```text
frontend/screenshots/
├── admin-panel.png
├── user-home.png
├── add-more-dialog.png
└── retrieval-results.png
```

Then reference them in this README like this:

```md
![Admin Panel](frontend/screenshots/admin-panel.png)
```

---

## Why this design is useful

BHU-LM is designed to keep each processed batch isolated, which makes it easier to:

* track what was trained
* delete a specific batch later
* re-run only one category
* keep clean separation between document sets
* scale into a backend-driven system

---

## Notes

* The repository is built around category-based processing.
* The backend uses JSON files to control runtime behavior.
* Tables and structured content are preserved where useful.
* Retrieval is designed to be hybrid and configurable.
* The frontend is present for reference and future connection.

---

## Short project summary

BHU-LM is a modular MediaWiki RAG system with category-based ingestion, versioned storage, table-aware chunking, hybrid retrieval, reranking, and optional image processing. It is built to support clean retraining, easy deletion of old sets, and future backend-driven productization.

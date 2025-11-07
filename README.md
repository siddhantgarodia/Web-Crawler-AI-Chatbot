# MOSDAC Crawler — README

A short guide to the MOSDAC crawler project: architecture, pipeline, modules, Playwright usage, outputs, and how to run it on Windows (PowerShell).

## Project overview

This repository contains a small web crawling and retrieval pipeline optimized for sites with both static and JavaScript-rendered content. The pipeline is composed of the following high-level stages:

1. Crawl: fetch HTML (with Playwright for JS-heavy pages) or download documents (PDF/DOCX/DOC). Save raw HTML / files and parse them into structured JSON using Unstructured and light doc parsers.
2. Clean: convert the JSON outputs into plain, readable text files for indexing.
3. Index: build a FAISS vector index from cleaned text using SentenceTransformers.
4. Query: run semantic search + hybrid link-fallback and ask a large-model (Gemini) for an answer.

Key files and roles
- `integrated.py` — The main HTTP-first, sitemap-aware integrated crawler (non-Playwright). Saves raw HTML, parses via Unstructured, downloads and parses docs, builds `link_db.json` and `crawled_resources.json`.
- `pw/crawl.py` — Sitemap-first crawler that *prefers Playwright* for rendering. Has full logic for rendering, requests fallback, file downloading, parsing, incremental saves, and link DB management.
- `crawler.py` — A simpler Playwright-based renderer for quick JS-page rendering and Unstructured parsing (useful for single-page experiments).
- `jsoncleaner.py` — Post-processing/cleaner that converts `*-output.json` (Unstructured) and `*-parsed.json` (docs) into `.txt` files stored in a `cleaned/` subfolder. These `.txt` files are what the indexer consumes.
- `index.py` — Builds the FAISS index from `.txt` files found under `results/**/cleaned/*.txt` using `sentence-transformers`.
- `query.py` — Loads the FAISS index and metadata and runs hybrid retrieval. It supports: (1) semantic search via FAISS + SentenceTransformers, (2) link-database fallback, (3) sending retrieved context to a Gemini model (via `google.generativeai`).


## How the pipeline flows (recommended order)

1. Crawling
   - Run `integrated.py` (sitemap-first / HTTP-based) or `pw/crawl.py` (sitemap-first, Playwright-enabled). These write JSON outputs and link DBs under `results/` or `results_playwright/`.
   - Alternatively use `crawler.py` for ad-hoc Playwright rendering of a single start URL.

2. Cleaning
   - Run `jsoncleaner.py` to convert the JSON outputs into plain `.txt` files placed in `results/<domain>/cleaned/`.

3. Indexing
   - Run `index.py` to read the cleaned `.txt` files and build a FAISS index in `faiss_index/`.

4. Query
   - Run `query.py` (you'll need to set the Gemini API key in the script or environment). This script loads the FAISS index and metadata and performs retrieval + generation.


## Playwright details (why and how it’s used)

Why Playwright
- Many modern sites render content client-side with JavaScript. `requests` alone returns initial HTML that may not include the dynamically inserted content.
- Playwright launches a headless Chromium, executes page JavaScript, and returns the post-render DOM. This lets Unstructured parse the actual visible content.

How Playwright is used in this project
- `pw/crawl.py` and `crawler.py` use `playwright.async_api` and the `async_playwright()` context manager.
- Typical flow in the code:
  - `async with async_playwright() as playwright:` creates the Playwright runtime.
  - `browser = await playwright.chromium.launch(headless=True)` starts Chromium headlessly.
  - `page = await browser.new_page()` and `await page.goto(url, wait_until="networkidle", timeout=...)` loads the page and waits for network idle.
  - The code then waits a little (`asyncio.sleep(1.0-1.5s)`) to let client scripts finish any final DOM updates.
  - `content = await page.content()` gets the final HTML string, which is saved and passed to `unstructured.partition_html()` for parsing.
  - If Playwright render fails, `pw/crawl.py` falls back to `requests.get()` as a secondary attempt.

Notes and tradeoffs
- Playwright is heavier (requires browser binaries), but it yields far better content coverage for JS-heavy pages.
- The code launches and closes the browser for each page in the helper functions. For higher throughput you can re-use a browser instance across pages (the `pw/crawl.py` already uses a single `async_playwright()` context; it can be further optimized to launch the browser once and re-use it for many pages).


## Outputs and file layout

Crawling produces a structured folder per domain. Expected structure (examples):

- results/ (or results_playwright/)
  - example.com/
    - raw/                # saved HTML files (Playwright-rendered or requests fallback)
      - root.html
    - files/              # downloaded PDFs / DOCX / parsed JSONs
      - report.pdf
      - report-parsed.json
    - tmp/                # temporary HTML used for parsing (may be removed after parsing)
    - link_db.json        # list of parent->child link relations
    - crawled_resources.json or crawled_playwright.json  # crawl metadata
    - <filename>-output.json  # unstructured parsed JSON per page (canonical per-URL corpus)
    - cleaned/            # produced by `jsoncleaner.py` (contains .txt files)

Indexing expects `results/**/cleaned/*.txt` (see `index.py`) — it loads all `.txt` files from `results` recursively in `cleaned` subfolders.


## Installation (Windows, PowerShell)

1) Create & activate a virtual environment (recommended):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

2) Install core dependencies (some are optional):

```powershell
pip install requests beautifulsoup4 unstructured playwright sentence-transformers numpy google-generativeai
pip install pdfplumber mammoth textract  # optional, for PDF/DOC parsing
```

Notes about FAISS:
- Installing `faiss` on Windows can be tricky. Try `pip install faiss-cpu` first, but if that fails, consider using conda:

```powershell
# Using conda (recommended on Windows if pip wheel unavailable)
conda create -n mosdac python=3.11
conda activate mosdac
conda install -c pytorch faiss-cpu -y
pip install sentence-transformers
```

3) Install Playwright browser binaries:

```powershell
python -m playwright install
# or specifically for chromium:
python -m playwright install chromium
```

4) Optional: If you plan to run the Gemini integration, install and configure `google-generativeai` and put your API key into `query.py` or read it from an environment variable.


## How to run (examples)

1) Quick single-page Playwright render (ad-hoc):

```powershell
# Render a single page and parse with Unstructured
python crawler.py
```

Note: `crawler.py` prompts for a start URL and max depth.

2) Sitemap-first Playwright crawl (recommended for JS-heavy sites):

```powershell
python pw\crawl.py
# The script will ask for sitemap URL (optional) and then run.
```

3) Integrated HTTP crawler (no Playwright):

```powershell
python integrated.py
# Provides prompts for sitemap / start URL and crawl depth.
```

4) Clean all JSON outputs to plain text:

```powershell
python jsoncleaner.py
```

5) Build FAISS index:

```powershell
python index.py
```

6) Interactive query (Gemini integration required):

```powershell
# Edit query.py to insert your API key, or set env var and modify script accordingly
python query.py
```


## Configuration tips & flags you can tweak

- `MAX_FILE_SIZE_MB` (in `pw/crawl.py` and `integrated.py`): skip very large downloads to avoid storage and parse overhead.
- `REQUEST_TIMEOUT`: request / download timeouts.
- `DOC_EXTENSIONS` / `SKIP_EXTENSIONS`: extend or shrink lists based on target site content.
- `RESULTS_ROOT`: change the output root folder.
- Playwright rendering wait times (the `asyncio.sleep` after `page.goto`) — increasing this helps pages that lazy-load after networkidle.


## Troubleshooting

- Playwright errors: ensure browser binaries installed (`python -m playwright install`). If you see timeout errors, increase the `timeout=` value in `render_page_with_playwright()`.
- faiss installation issues on Windows: prefer conda (`conda install -c pytorch faiss-cpu`) or use WSL.
- Unstructured parsing errors: ensure the `unstructured` package and its optional dependencies are installed. Unstructured may emit parsing exceptions on malformed HTML; the crawlers try to save a minimal JSON even on failures.


## Security & ethics note

- Respect `robots.txt` and site terms of service. The crawlers in this repo do not automatically respect `robots.txt` — add that logic or run only on sites you have permission to crawl.
- Be cautious with large-scale crawling: limit rate and enforce polite pauses; the sample crawlers use small sleeps but are not production-grade.


## Next steps / improvements you might want

- Reuse a Playwright browser instance across pages for higher throughput.
- Add a `requirements.txt` and/or `pyproject.toml` for reproducible installs.
- Add `robots.txt` compliance and concurrency controls.
- Add unit tests for the JSON cleaning and filename normalization logic.


---

If you want, I can also:
- Add a `requirements.txt` with pinned versions.
- Fix a small bug I noticed in `crawler.py`'s entrypoint check so `python crawler.py` works as expected.

Tell me which of the two additions you'd like me to do next.
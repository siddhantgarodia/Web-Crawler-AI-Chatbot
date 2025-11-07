"""
Playwright-based Crawler for JavaScript-heavy sites.
 - Uses Playwright headless browser for rendering
 - Integrates with Unstructured for parsing rendered HTML
 - Supports PDF/DOCX/DOC download and parsing
"""

import os
import re
import json
import time
import asyncio
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from unstructured.partition.html import partition_html
from unstructured.staging.base import elements_to_json

# Optional doc parsers
try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    import mammoth
except Exception:
    mammoth = None


from playwright.async_api import async_playwright

HEADERS = {"User-Agent": "PlaywrightCrawler/1.0 (+https://example.com)"}
RESULTS_ROOT = "results_playwright"
DOC_EXTENSIONS = [".pdf", ".docx", ".doc"]
REQUEST_TIMEOUT = 20


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def filename_for_url(url):
    parsed = urlparse(url)
    path = parsed.path.strip("/") or "root"
    safe = re.sub(r"[^A-Za-z0-9_\-\.]", "_", path)
    if parsed.query:
        safe += f"_q{abs(hash(parsed.query)) % 100000}"
    return safe


# ---------- File Parsers ----------
def parse_pdf_to_text(path):
    if not pdfplumber:
        return None
    try:
        with pdfplumber.open(path) as pdf:
            pages = [p.extract_text() for p in pdf.pages if p.extract_text()]
        return "\n\n".join(pages).strip()
    except Exception as e:
        print(f"[PDF] Error parsing {path}: {e}")
        return None


def parse_docx_to_text(path):
    if not mammoth:
        return None
    try:
        with open(path, "rb") as f:
            result = mammoth.extract_raw_text(f)
        return result.value.strip()
    except Exception as e:
        print(f"[DOCX] Error parsing {path}: {e}")
        return None





# ---------- Crawler Core ----------
async def render_and_parse_page(playwright, url, domain_dir, depth=0):
    """Render JS-heavy page using Playwright and parse with Unstructured."""
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()
    await page.goto(url, wait_until="networkidle", timeout=30000)
    await asyncio.sleep(1.5)  # wait for dynamic elements
    content = await page.content()
    await browser.close()

    fname = filename_for_url(url)
    tmp_html = os.path.join(domain_dir, "tmp", f"{fname}.html")
    ensure_dir(os.path.dirname(tmp_html))
    with open(tmp_html, "w", encoding="utf-8", errors="ignore") as f:
        f.write(content)

    # Parse via Unstructured
    try:
        elements = partition_html(filename=tmp_html)
        out_json = os.path.join(domain_dir, f"{fname}-output.json")
        elements_to_json(elements, filename=out_json)
        print(f"  ✔ Parsed and saved: {out_json}")
        os.remove(tmp_html)
    except Exception as e:
        print(f"  [UNSTRUCTURED] Error parsing {url}: {e}")
        return []

    # Extract links for crawling
    soup = BeautifulSoup(content, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        abs_url = urljoin(url, a["href"])
        links.append(abs_url)
    return links


async def crawl_playwright(start_url, max_depth=1, follow_same_domain=True):
    """Recursive crawl with Playwright for JS-heavy pages."""
    parsed_domain = urlparse(start_url).netloc
    domain_dir = os.path.join(RESULTS_ROOT, parsed_domain)
    ensure_dir(domain_dir)
    ensure_dir(os.path.join(domain_dir, "tmp"))
    ensure_dir(os.path.join(domain_dir, "files"))

    visited = set()
    queue = [(start_url, 0)]
    crawled_meta = []

    async with async_playwright() as playwright:
        while queue:
            url, depth = queue.pop(0)
            if url in visited or depth > max_depth:
                continue
            visited.add(url)

            print(f"[PLAYWRIGHT] Depth {depth}: {url}")
            try:
                links = await render_and_parse_page(playwright, url, domain_dir, depth)
                record = {"url": url, "depth": depth, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
                crawled_meta.append(record)

                # Enqueue new links
                for link in links:
                    parsed = urlparse(link)
                    if parsed.scheme not in ("http", "https"):
                        continue
                    if follow_same_domain and parsed.netloc != parsed_domain:
                        continue
                    if link not in visited:
                        queue.append((link, depth + 1))
            except Exception as e:
                print(f"  [!] Failed to process {url}: {e}")

    # Save metadata
    meta_path = os.path.join(domain_dir, "crawled_playwright.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(crawled_meta, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Done. Metadata saved to {meta_path}")


# ---------- Entrypoint ----------
if __name__ == "__main__":
    start_url = input("Enter start URL: ").strip()
    depth = int(input("Enter max depth (e.g., 1): ").strip() or "1")
    asyncio.run(crawl_playwright(start_url, max_depth=depth))
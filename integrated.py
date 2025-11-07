#!/usr/bin/env python3
"""
integrated.py  —  Final Integrated Crawler (Full Features)

Features:
 - Sitemap-first crawling, fallback to start URL
 - HTML parsed via unstructured.partition.html
 - PDFs parsed via pdfplumber
 - DOCX parsed via mammoth
 - Skip large files (>10 MB)
 - Skip images & archives/binaries
 - Builds link database (parent-child, anchor, depth)
 - Always saves JSON (even if empty text)
 - Organized filesystem per domain
"""

import os
import re
import json
import time
import shutil
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from unstructured.partition.html import partition_html
from unstructured.staging.base import elements_to_json
from xml.etree import ElementTree as ET

# optional parsers
try:
    import pdfplumber
except Exception:
    pdfplumber = None

try:
    import mammoth
except Exception:
    mammoth = None


# ------------- Configuration -------------
HEADERS = {"User-Agent": "IntegratedCrawler/1.0 (+https://example.com)"}
REQUEST_TIMEOUT = 15
RESULTS_ROOT = "results"
LINK_DB_FILENAME = "link_db.json"
CRAWL_META_FILENAME = "crawled_resources.json"
MAX_FILE_SIZE_MB = 10

DOC_EXTENSIONS = [".pdf", ".docx", ".doc"]
IMG_EXTENSIONS = [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".svg", ".webp"]
SKIP_EXTENSIONS = [".zip", ".rar", ".tar", ".tar.gz", ".7z", ".gz", ".xz", ".bz2", ".iso", ".exe", ".bin", ".msi"] + IMG_EXTENSIONS


# ------------- Helpers -------------
def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def domain_for_url(url):
    parsed = urlparse(url)
    return parsed.netloc.replace(":", "_")


def filename_for_url(url):
    parsed = urlparse(url)
    path = parsed.path.strip("/") or "root"
    safe = re.sub(r"[^A-Za-z0-9_\-\.]", "_", path)
    if parsed.query:
        safe += f"_q{abs(hash(parsed.query)) % 100000}"
    return safe


def get_resource_type(url, headers=None):
    lower = url.lower()
    for ext in DOC_EXTENSIONS:
        if lower.endswith(ext):
            return ext.lstrip(".")
    if headers:
        ctype = headers.get("content-type", "").lower()
        if "pdf" in ctype:
            return "pdf"
        if "word" in ctype or "officedocument" in ctype:
            return "docx"
        if "html" in ctype:
            return "html"
    return "html"


# ------------- Sitemap Parsing -------------
def parse_sitemap(sitemap_url):
    try:
        print(f"[SITEMAP] Fetching sitemap: {sitemap_url}")
        r = requests.get(sitemap_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        ns = re.match(r"\{.*\}", root.tag)
        namespace = ns.group(0) if ns else ""
        urls = []
        for u in root.findall(f"{namespace}url"):
            loc = u.find(f"{namespace}loc")
            if loc is not None and loc.text:
                urls.append(loc.text.strip())
        if not urls:
            for sm in root.findall(f"{namespace}sitemap"):
                loc = sm.find(f"{namespace}loc")
                if loc is not None and loc.text:
                    nested = parse_sitemap(loc.text.strip())
                    urls.extend(nested)
        print(f"  [SITEMAP] Found {len(urls)} URLs.")
        return urls
    except Exception as e:
        print(f"  [SITEMAP] Failed: {e}")
        return []


# ------------- File size check & download -------------
def check_file_size_ok(url):
    try:
        head = requests.head(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        size = head.headers.get("content-length")
        if size and int(size) > MAX_FILE_SIZE_MB * 1024 * 1024:
            print(f"    [SKIP] {url} > {MAX_FILE_SIZE_MB} MB, skipping.")
            return False
        return True
    except Exception:
        return True


def download_binary(url, dest):
    if not check_file_size_ok(url):
        return False, "too_large"
    try:
        ensure_dir(os.path.dirname(dest))
        with requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, stream=True) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                shutil.copyfileobj(r.raw, f)
        return True, "downloaded"
    except Exception as e:
        print(f"    [!] Failed to download {url}: {e}")
        return False, "error"


# ------------- Parsers -------------
def parse_pdf(path):
    if not pdfplumber:
        return None
    try:
        with pdfplumber.open(path) as pdf:
            texts = [p.extract_text() for p in pdf.pages if p.extract_text()]
        return "\n\n".join(texts).strip()
    except Exception as e:
        print(f"    [PDF] Error parsing {path}: {e}")
        return None


def parse_docx(path):
    if not mammoth:
        return None
    try:
        with open(path, "rb") as f:
            result = mammoth.extract_raw_text(f)
        return result.value.strip()
    except Exception as e:
        print(f"    [DOCX] Error parsing {path}: {e}")
        return None


# ------------- JSON Helpers -------------
def save_json(path, obj):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


# ------------- Core Crawler -------------
def crawl(seed_urls, start_domain, max_depth=2, follow_same_domain=True):
    visited = set()
    queue = [(u, 0, None, None) for u in seed_urls]
    link_db = []
    crawled_meta = []

    domain_dir = os.path.join(RESULTS_ROOT, start_domain)
    ensure_dir(domain_dir)
    ensure_dir(os.path.join(domain_dir, "raw"))
    ensure_dir(os.path.join(domain_dir, "files"))

    while queue:
        url, depth, parent, anchor = queue.pop(0)
        if url in visited or depth > max_depth:
            continue
        visited.add(url)
        print(f"[CRAWL] Depth {depth} -> {url}")

        # skip images & binaries
        lower_url = url.lower().split("#")[0]
        if any(lower_url.endswith(ext) for ext in SKIP_EXTENSIONS):
            print(f"    [SKIP] {url} (non-text type)")
            link_db.append({
                "parent": parent, "child": url, "depth": depth,
                "anchor": anchor, "note": "skipped_non_text",
                "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            })
            continue

        try:
            r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            res_type = get_resource_type(url, r.headers)
            fname = filename_for_url(url)
            record = {
                "url": url, "depth": depth, "type": res_type,
                "parent": parent, "anchor": anchor,
                "status": r.status_code, "saved": {}, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }

            # HTML case
            if res_type == "html":
                raw_path = os.path.join(domain_dir, "raw", f"{fname}.html")
                with open(raw_path, "w", encoding="utf-8", errors="ignore") as f:
                    f.write(r.text)
                record["saved"]["raw_html"] = raw_path

                try:
                    elements = partition_html(filename=raw_path)
                    out_json = os.path.join(domain_dir, f"{fname}-output.json")
                    elements_to_json(elements=elements, filename=out_json)
                    record["saved"]["parsed_json"] = out_json
                except Exception as e:
                    print(f"    [UNSTRUCTURED] Error parsing HTML: {e}")
                    out_json = os.path.join(domain_dir, f"{fname}-output.json")
                    save_json(out_json, {"url": url, "text": "", "note": "parse_error"})
                    record["saved"]["parsed_json"] = out_json

                # link extraction
                try:
                    soup = BeautifulSoup(r.content, "html.parser")
                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        text = (a.get_text() or "").strip()
                        abs_url = urljoin(url, href)
                        parsed = urlparse(abs_url)
                        if parsed.scheme not in ("http", "https"):
                            continue
                        if follow_same_domain and parsed.netloc != start_domain:
                            continue
                        link_db.append({
                            "parent": url, "child": abs_url, "depth": depth + 1,
                            "anchor": text, "discovered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        })
                        if abs_url not in visited:
                            queue.append((abs_url, depth + 1, url, text))
                except Exception as e:
                    print(f"    [LINK_PARSE] Failed: {e}")

            # Document case
            elif res_type in ("pdf", "docx", "doc"):
                ext = os.path.splitext(urlparse(url).path)[1] or f".{res_type}"
                dest = os.path.join(domain_dir, "files", f"{fname}{ext}")
                ok, status = download_binary(url, dest)
                record["saved"]["download_status"] = status
                if ok and status == "downloaded":
                    if res_type == "pdf":
                        text = parse_pdf(dest)
                    elif res_type == "docx":
                        text = parse_docx(dest)
                    else:
                        text = None
                    parsed_path = os.path.join(domain_dir, "files", f"{fname}-parsed.json")
                    save_json(parsed_path, {"url": url, "text": text or ""})
                    record["saved"]["parsed_text"] = parsed_path
                elif status == "too_large":
                    record["note"] = f"Skipped (>{MAX_FILE_SIZE_MB} MB)"
                else:
                    record["note"] = "Download failed"

            crawled_meta.append(record)
            save_json(os.path.join(domain_dir, CRAWL_META_FILENAME), crawled_meta)
            save_json(os.path.join(domain_dir, LINK_DB_FILENAME), link_db)
            time.sleep(0.1)

        except requests.exceptions.RequestException as e:
            print(f"    [HTTP] Error: {e}")
        except Exception as e:
            print(f"    [!] Unexpected error: {e}")

    return crawled_meta, link_db


# ------------- Entrypoint -------------
print("=== Integrated Crawler (Final Version) ===")
sitemap = input("Enter sitemap URL (leave blank to skip): ").strip()
start_url = input("Enter start website URL (used if sitemap fails): ").strip()
try:
    max_depth = int(input("Enter max crawl depth (e.g., 2): ").strip() or "2")
except ValueError:
    max_depth = 2

seeds = []
if sitemap:
    seeds = parse_sitemap(sitemap)
if not seeds and start_url:
    seeds = [start_url]
if not seeds:
    print("No seed URLs found. Exiting.")
    exit(1)

domain = urlparse(seeds[0]).netloc
meta, links = crawl(seeds, domain, max_depth=max_depth)
save_json(os.path.join(RESULTS_ROOT, domain, CRAWL_META_FILENAME), meta)
save_json(os.path.join(RESULTS_ROOT, domain, LINK_DB_FILENAME), links)
print(f"\n Crawl complete! Results stored in results/{domain}")
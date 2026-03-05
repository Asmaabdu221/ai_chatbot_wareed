import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

import pandas as pd
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm
from app.core.paths import LINKS_XLSX_PATH, SOURCES_WEB_DIR


# ----------------------------
# Helpers
# ----------------------------

def normalize_ws(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text

def is_probably_noise(text: str) -> bool:
    if not text:
        return True
    # very short chunks are often navigation or labels
    return len(text) < 40

def pick_best_column(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols_lower = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in cols_lower:
            return cols_lower[cand.lower()]
    return None

def safe_filename(s: str) -> str:
    s = re.sub(r"[^\w\-\.]+", "_", s)
    return s[:150]


# ----------------------------
# Scraper
# ----------------------------

@dataclass
class ScrapeResult:
    url: str
    status_code: Optional[int]
    title: str
    text: str
    meta_description: str
    h1: str
    lang: str
    error: str


def extract_main_text(html: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "lxml")

    # remove obvious noise
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    # remove common layout elements
    for sel in ["header", "footer", "nav", "aside"]:
        for tag in soup.select(sel):
            tag.decompose()

    title = normalize_ws(soup.title.get_text()) if soup.title else ""

    meta_desc = ""
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        meta_desc = normalize_ws(md["content"])

    h1 = ""
    h1_tag = soup.find("h1")
    if h1_tag:
        h1 = normalize_ws(h1_tag.get_text())

    lang = ""
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        lang = html_tag.get("lang", "")

    # Heuristic: try main/article first, else body
    container = soup.find("main") or soup.find("article") or soup.body or soup

    # Pull paragraphs + list items (often medical pages use bullets)
    parts: List[str] = []
    for el in container.find_all(["p", "li", "h2", "h3", "h4"]):
        t = normalize_ws(el.get_text(" ", strip=True))
        if not is_probably_noise(t):
            parts.append(t)

    text = normalize_ws(" \n".join(parts))

    return {
        "title": title,
        "meta_description": meta_desc,
        "h1": h1,
        "lang": lang,
        "text": text,
    }


def classify_url(url: str) -> str:
    u = (url or "").lower()
    # tune these to your site patterns
    if any(k in u for k in ["package", "paket", "packages", "bundle", "pakage"]):
        return "package_page"
    if any(k in u for k in ["analysis", "test", "تحاليل", "analiz"]):
        return "test_page"
    if any(k in u for k in ["branch", "branches", "فرع", "sube"]):
        return "branch_page"
    if any(k in u for k in ["faq", "questions", "سؤال", "اسئلة"]):
        return "faq_page"
    if any(k in u for k in ["blog", "news", "privacy", "terms", "policy", "login", "signup"]):
        return "low_priority"
    return "general_page"


def scrape_one(session: requests.Session, url: str, timeout: int) -> ScrapeResult:
    try:
        r = session.get(url, timeout=timeout, allow_redirects=True, headers={
            "User-Agent": "WareedKnowledgeBot/1.0 (+https://wareed.com.sa)"
        })
        status = r.status_code
        if status != 200:
            return ScrapeResult(url, status, "", "", "", "", "", f"HTTP {status}")

        data = extract_main_text(r.text)
        return ScrapeResult(
            url=url,
            status_code=status,
            title=data["title"],
            text=data["text"],
            meta_description=data["meta_description"],
            h1=data["h1"],
            lang=data["lang"],
            error=""
        )
    except Exception as e:
        return ScrapeResult(url, None, "", "", "", "", "", str(e))


# ----------------------------
# Main
# ----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(LINKS_XLSX_PATH), help="Path to LINKS.xlsx")
    ap.add_argument("--out_dir", default=str(SOURCES_WEB_DIR), help="Output directory")
    ap.add_argument("--url_col", default="", help="URL column name (optional)")
    ap.add_argument("--status_col", default="", help="Status column name (optional)")
    ap.add_argument("--only_200", action="store_true", help="Only scrape rows with 200 status")
    ap.add_argument("--include_patterns", default="", help="Comma-separated substrings; keep URLs containing any")
    ap.add_argument("--exclude_patterns", default="", help="Comma-separated substrings; drop URLs containing any")
    ap.add_argument("--sleep", type=float, default=0.2, help="Sleep seconds between requests")
    ap.add_argument("--timeout", type=int, default=20, help="Request timeout seconds")
    ap.add_argument("--max", type=int, default=0, help="Max URLs (0 = all)")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    out_jsonl = os.path.join(args.out_dir, "site_knowledge.jsonl")
    out_csv = os.path.join(args.out_dir, "site_knowledge_summary.csv")
    out_state = os.path.join(args.out_dir, "scrape_state.json")

    df = pd.read_excel(args.input)

    # guess columns if not provided
    url_col = args.url_col or pick_best_column(df, ["Address", "URL", "Url", "Link", "Links"])
    if not url_col:
        raise ValueError(f"Could not find URL column. Columns: {list(df.columns)}")

    status_col = args.status_col or pick_best_column(df, ["Status Code", "Status", "HTTP Status", "Code"])

    urls = df[url_col].astype(str).tolist()

    # filter: only_200
    if args.only_200 and status_col:
        mask_200 = df[status_col].astype(str).str.strip().eq("200")
        urls = df.loc[mask_200, url_col].astype(str).tolist()

    include = [s.strip().lower() for s in args.include_patterns.split(",") if s.strip()]
    exclude = [s.strip().lower() for s in args.exclude_patterns.split(",") if s.strip()]

    def keep(u: str) -> bool:
        lu = u.lower()
        if include and not any(p in lu for p in include):
            return False
        if exclude and any(p in lu for p in exclude):
            return False
        return True

    urls = [u for u in urls if keep(u)]

    if args.max and args.max > 0:
        urls = urls[:args.max]

    # resume support
    done = set()
    if os.path.exists(out_state):
        try:
            state = json.load(open(out_state, "r", encoding="utf-8"))
            done = set(state.get("done", []))
        except Exception:
            done = set()

    session = requests.Session()

    records_for_csv = []

    with open(out_jsonl, "a", encoding="utf-8") as f:
        for url in tqdm(urls, desc="Scraping"):
            if url in done:
                continue

            res = scrape_one(session, url, timeout=args.timeout)
            page_type = classify_url(url)

            knowledge_obj: Dict[str, Any] = {
                "type": "web_page",
                "page_type": page_type,
                "url": res.url,
                "status_code": res.status_code,
                "title": res.title,
                "h1": res.h1,
                "meta_description": res.meta_description,
                "lang": res.lang,
                "content": res.text,
                "error": res.error,
                "source": "LINKS.xlsx"
            }

            f.write(json.dumps(knowledge_obj, ensure_ascii=False) + "\n")
            f.flush()

            records_for_csv.append({
                "url": res.url,
                "page_type": page_type,
                "status_code": res.status_code,
                "title": res.title,
                "content_chars": len(res.text or ""),
                "error": res.error
            })

            done.add(url)
            json.dump({"done": sorted(done)}, open(out_state, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

            time.sleep(args.sleep)

    # write summary csv
    pd.DataFrame(records_for_csv).to_csv(out_csv, index=False, encoding="utf-8-sig")

    print(f"Done.\nJSONL: {out_jsonl}\nCSV:   {out_csv}\nState: {out_state}")


if __name__ == "__main__":
    main()

from pathlib import Path

# CWD-agnostic project root: .../<repo>/app/core/paths.py -> parents[2] == <repo>
BASE_DIR = Path(__file__).resolve().parents[2]

DATA_DIR = BASE_DIR / "app" / "data"
SOURCES_DIR = DATA_DIR / "sources"
SOURCES_EXCEL_DIR = SOURCES_DIR / "excel"
SOURCES_WEB_DIR = SOURCES_DIR / "web"
RUNTIME_DIR = DATA_DIR / "runtime"

EXCEL_ANALYSES_PATH = SOURCES_EXCEL_DIR / "analyses_with_prices.xlsx"
EXCEL_PRAACISE_PATH = SOURCES_EXCEL_DIR / "praacise.xlsx"
EXCEL_PACKAGES_PATH = SOURCES_EXCEL_DIR / "PAKAGE1.xlsx"
EXCEL_FAQ_PATH = SOURCES_EXCEL_DIR / "faq.xlsx"
EXCEL_BRANCHES_PATH = SOURCES_EXCEL_DIR / "branches.xlsx"
LINKS_XLSX_PATH = SOURCES_EXCEL_DIR / "LINKS.xlsx"

SITE_SCRAPED_JSONL_PATH = SOURCES_WEB_DIR / "site_scraped.jsonl"

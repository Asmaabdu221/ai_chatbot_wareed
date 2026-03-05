from app.core.paths import (
    RUNTIME_DIR,
    SITE_SCRAPED_JSONL_PATH,
    SOURCES_DIR,
    SOURCES_EXCEL_DIR,
    SOURCES_WEB_DIR,
)


def main() -> int:
    checks = {
        "SOURCES_DIR": SOURCES_DIR.exists(),
        "SOURCES_EXCEL_DIR": SOURCES_EXCEL_DIR.exists(),
        "SOURCES_WEB_DIR": SOURCES_WEB_DIR.exists(),
        "RUNTIME_DIR": RUNTIME_DIR.exists(),
        "SITE_SCRAPED_JSONL_PATH(parent)": SITE_SCRAPED_JSONL_PATH.parent.exists(),
    }
    for name, ok in checks.items():
        print(f"{name}: {'OK' if ok else 'MISSING'}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

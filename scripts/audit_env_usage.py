from __future__ import annotations

import io
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "venv", "node_modules", "__pycache__", ".pytest_cache"}
TEXT_EXTS = {
    ".py",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".ini",
    ".env",
    ".json",
    ".ps1",
    ".toml",
}


def is_skipped(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def iter_files() -> list[Path]:
    files: list[Path] = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if is_skipped(p):
            continue
        if p.suffix.lower() in TEXT_EXTS or p.name.startswith(".env"):
            files.append(p)
    return files


def collect_env_defs(text: str) -> set[str]:
    out = set()
    for m in re.finditer(r"^\s*([A-Z][A-Z0-9_]+)\s*=", text, flags=re.MULTILINE):
        out.add(m.group(1))
    return out


def collect_env_refs(text: str) -> set[str]:
    out = set()
    patterns = [
        r"os\.getenv\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]",
        r"os\.environ\.get\(\s*['\"]([A-Z][A-Z0-9_]+)['\"]",
        r"os\.environ\[\s*['\"]([A-Z][A-Z0-9_]+)['\"]\s*\]",
        r"load_dotenv\(",
        r"getattr\(\s*settings\s*,\s*['\"]([A-Z][A-Z0-9_]+)['\"]",
        r"\bsettings\.([A-Z][A-Z0-9_]+)\b",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text):
            if m.lastindex:
                out.add(m.group(1))
    # Capture BaseSettings-style declarations: VAR_NAME: type = Field(...)
    for m in re.finditer(r"^\s*([A-Z][A-Z0-9_]+)\s*:\s*[^=\n]+\s*=\s*Field\(", text, flags=re.MULTILINE):
        out.add(m.group(1))
    return out


def main() -> int:
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    findings: dict[str, list[tuple[str, int, str]]] = {}

    for path in iter_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        refs = collect_env_refs(text)
        defs = collect_env_defs(text) if path.name.startswith(".env") else set()
        names = refs | defs
        if not names:
            continue

        for i, line in enumerate(text.splitlines(), start=1):
            for name in names:
                if name in line:
                    findings.setdefault(name, []).append((str(path.relative_to(ROOT)), i, line.strip()))

    for name in sorted(findings):
        print(f"[{name}]")
        for rel, line_no, src in findings[name]:
            redacted = re.sub(r"=\s*.+$", "=[REDACTED]", src)
            print(f"  - {rel}:{line_no}: {redacted}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

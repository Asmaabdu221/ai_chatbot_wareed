from pathlib import Path

content = '''"""Deprecated compatibility shims for Arabic normalization. Use WareedNormalizer."""
from __future__ import annotations
import warnings
from app.services.runtime.unified_normalizer import get_wareed_normalizer

def normalize_arabic(text: str) -> str:
    warnings.warn("Deprecated. Use WareedNormalizer.normalize()", DeprecationWarning, stacklevel=2)
    return get_wareed_normalizer().normalize(text)

def normalize_for_matching(text: str) -> str:
    warnings.warn("Deprecated. Use WareedNormalizer.normalize()", DeprecationWarning, stacklevel=2)
    return get_wareed_normalizer().normalize(text)
'''

p = Path('app/utils/arabic_normalizer.py')
try:
    p.write_text(content, encoding='utf-8')
    print('overwrite_ok')
except PermissionError:
    p.unlink(missing_ok=True)
    p.write_text(content, encoding='utf-8')
    print('recreate_ok')

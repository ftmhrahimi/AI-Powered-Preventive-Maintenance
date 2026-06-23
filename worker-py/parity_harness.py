"""Parity harness: prints the Python engine's raw item extraction so it can be
compared against the browser's getTextContent dump. Run with a PDF path.

LLM-dependent stages (clean/checkbox/validate) require a live vLLM endpoint and
are compared separately by running the full pipeline against a known report.
"""
import sys
from engine.pdf_items import extract_raw_items, fix_persian


def normalize_for_compare(s: str) -> str:
    import re, unicodedata
    s = re.sub(r'[‌​‎‏­]', '', s)
    s = re.sub(r'[ً-ٟ]', '', s)
    s = unicodedata.normalize('NFKC', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python parity_harness.py <pdf>")
        sys.exit(1)
    out = extract_raw_items(sys.argv[1])
    print(f"is_english={out['is_english']}  items={len(out['items'])}")
    print("-" * 70)
    for t in out["items"]:
        norm = normalize_for_compare(t["desc"])
        print(f'[{t["num"]:>2}] {norm[:200]}')

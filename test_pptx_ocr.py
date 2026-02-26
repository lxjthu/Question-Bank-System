#!/usr/bin/env python3
"""
Standalone test script for the PPTX OCR pipeline.

Usage:
    # Test smallest PPTX in test/ directory (default)
    python test_pptx_ocr.py

    # Test a specific file
    python test_pptx_ocr.py "test/林业经济学-第一讲-绪论-2024.pptx"

    # Test all files in test/
    python test_pptx_ocr.py --all

    # Keep intermediate files (PDF/images) for debugging
    python test_pptx_ocr.py --keep-temp

Prerequisites:
    1. Fill in PADDLEOCR_TOKEN in .env
    2. pip install requests python-dotenv
    3. For PPTX→PDF conversion: pip install pywin32  (requires MS Office)
       OR install LibreOffice: https://www.libreoffice.org/
"""
import sys
from pathlib import Path

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).parent))

from pptx_ocr.config import PADDLEOCR_API_URL, PADDLEOCR_TOKEN
from pptx_ocr.pipeline import process_pptx


def main():
    args = sys.argv[1:]
    run_all = "--all" in args
    keep_temp = "--keep-temp" in args
    positional = [a for a in args if not a.startswith("--")]

    print("=" * 60)
    print("PPTX OCR Pipeline — Standalone Test")
    print("=" * 60)
    print(f"API  : {PADDLEOCR_API_URL}")
    print(f"Token: {'(set)' if PADDLEOCR_TOKEN else '** NOT SET — check .env **'}")
    print()

    if not PADDLEOCR_TOKEN:
        print("[ERROR] PADDLEOCR_TOKEN is empty.")
        print("Open .env and add your token:")
        print("  PADDLEOCR_TOKEN=your_token_here")
        sys.exit(1)

    test_dir = Path(__file__).parent / "test"

    # Determine files to process
    if positional:
        targets = [Path(p) for p in positional]
    else:
        all_files = sorted(test_dir.glob("*.pptx")) + sorted(test_dir.glob("*.ppt"))
        if not all_files:
            print(f"[ERROR] No PPTX files found in {test_dir}")
            sys.exit(1)

        # Sort by size so the smallest (fastest) runs first
        all_files.sort(key=lambda p: p.stat().st_size)

        if run_all:
            targets = all_files
        else:
            targets = [all_files[0]]
            print(f"Found {len(all_files)} files. Testing smallest first.")
            print("Use --all to process all files.\n")

    for i, pptx_path in enumerate(targets, 1):
        if len(targets) > 1:
            print(f"\n{'='*60}")
            print(f"File {i}/{len(targets)}")
        print(f"{'='*60}")
        try:
            out = process_pptx(pptx_path, keep_temp=keep_temp)
            print(f"\n[SUCCESS] → {out}")
        except Exception as exc:
            print(f"\n[FAILED] {exc}")
            if "--traceback" in args:
                import traceback
                traceback.print_exc()
        print()


if __name__ == "__main__":
    main()

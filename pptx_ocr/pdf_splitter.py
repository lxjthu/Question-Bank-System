"""
Split a PDF into fixed-size page chunks using pymupdf.
"""
from pathlib import Path
import fitz  # pymupdf


def split_pdf(
    pdf_path: Path,
    output_dir: Path,
    chunk_size: int = 10,
) -> list[Path]:
    """
    Split pdf_path into chunks of chunk_size pages each.

    Returns a sorted list of chunk PDF paths:
      chunk_001.pdf  (pages 0-9)
      chunk_002.pdf  (pages 10-19)
      ...
    """
    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    src = fitz.open(str(pdf_path))
    total = src.page_count
    chunks: list[Path] = []

    for start in range(0, total, chunk_size):
        end = min(start + chunk_size, total)   # exclusive
        idx = start // chunk_size + 1
        out_path = output_dir / f"chunk_{idx:03d}.pdf"

        dst = fitz.open()
        dst.insert_pdf(src, from_page=start, to_page=end - 1)
        dst.save(str(out_path))
        dst.close()
        chunks.append(out_path)

    src.close()
    return chunks


def pdf_page_count(pdf_path: Path) -> int:
    doc = fitz.open(str(pdf_path))
    n = doc.page_count
    doc.close()
    return n

"""
Main pipeline: PPTX → PDF → split into 10-page chunks → Layout Parsing API → Markdown.

Output directory structure:
  <stem>_ocr/
  ├── result.md       — full markdown with local image references
  ├── images/         — images downloaded from API response
  ├── checkpoint.json — chunk progress (for resume on timeout)
  └── _chunks/        — per-chunk markdown cache (cleaned on success)
"""
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from .api_client import LayoutParsingClient, ParseResult
from .config import PADDLEOCR_API_URL, PADDLEOCR_TOKEN, PADDLEOCR_TIMEOUT
from .converter import convert_to_images, convert_to_pdf
from .pdf_splitter import split_pdf, pdf_page_count

# API limit: max 10 pages per request
PDF_CHUNK_SIZE = 10


def process_pptx(
    pptx_path: Path,
    output_dir: Optional[Path] = None,
    *,
    keep_temp: bool = False,
    use_chart_recognition: bool = False,
    api_url: Optional[str] = None,
    api_token: Optional[str] = None,
    api_timeout: Optional[int] = None,
) -> Path:
    """
    Run the full OCR pipeline on a PPTX file.

    Args:
        pptx_path: Input PPTX/PPT file.
        output_dir: Where to write results (default: <pptx_stem>_ocr/ next to file).
        keep_temp: Keep intermediate PDF/image files for debugging.
        use_chart_recognition: Ask the API to analyze charts (slower).
        api_url: Override PADDLEOCR_API_URL from .env.
        api_token: Override PADDLEOCR_TOKEN from .env.
        api_timeout: Override PADDLEOCR_TIMEOUT from .env.

    Returns:
        Path to result.md.
    """
    pptx_path = Path(pptx_path)
    if not pptx_path.exists():
        raise FileNotFoundError(f"File not found: {pptx_path}")

    if output_dir is None:
        output_dir = pptx_path.parent / (pptx_path.stem + "_ocr")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _url = api_url or PADDLEOCR_API_URL
    _token = api_token or PADDLEOCR_TOKEN
    _timeout = api_timeout or PADDLEOCR_TIMEOUT

    if not _token:
        raise ValueError(
            "PADDLEOCR_TOKEN is not set.\n"
            "Open .env and fill in: PADDLEOCR_TOKEN=your_token_here"
        )

    client = LayoutParsingClient(_url, _token, _timeout)

    print(f"File : {pptx_path.name}  ({pptx_path.stat().st_size // 1024} KB)")
    print(f"API  : {_url}")
    print(f"Out  : {output_dir}")
    print()

    tmp_dir = Path(tempfile.mkdtemp(prefix="pptx_ocr_"))
    try:
        results = _convert_and_parse(
            pptx_path, tmp_dir, client, use_chart_recognition
        )
        md_path = _save_results(pptx_path, results, output_dir)
    finally:
        if not keep_temp:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        else:
            print(f"[DEBUG] Temp dir kept: {tmp_dir}")

    print(f"\n[DONE] {md_path}")
    return md_path


def _convert_and_parse(
    pptx_path: Path,
    tmp_dir: Path,
    client: LayoutParsingClient,
    use_chart: bool,
) -> list[ParseResult]:
    # --- Step 1: PPTX → PDF ---
    print("[1/2] Converting to PDF...")
    pdf_path = convert_to_pdf(pptx_path, tmp_dir)

    if pdf_path:
        total_pages = pdf_page_count(pdf_path)
        size_kb = pdf_path.stat().st_size // 1024
        n_chunks = (total_pages + PDF_CHUNK_SIZE - 1) // PDF_CHUNK_SIZE
        print(f"      PDF ready: {total_pages} pages, {size_kb} KB")
        print(f"      Splitting into {n_chunks} chunks of {PDF_CHUNK_SIZE} pages each")

        # --- Step 2: split + send each chunk ---
        chunks = split_pdf(pdf_path, tmp_dir / "chunks", chunk_size=PDF_CHUNK_SIZE)
        print(f"\n[2/2] Sending {len(chunks)} PDF chunks to API...")
        results: list[ParseResult] = []
        for i, chunk_path in enumerate(chunks, 1):
            page_start = (i - 1) * PDF_CHUNK_SIZE + 1
            page_end = min(i * PDF_CHUNK_SIZE, total_pages)
            chunk_kb = chunk_path.stat().st_size // 1024
            print(
                f"  Chunk {i:>3}/{len(chunks)}  "
                f"(slides {page_start}-{page_end}, {chunk_kb} KB) ...",
                end="  ",
                flush=True,
            )
            chunk_results = client.parse_file(
                chunk_path, file_type=0, use_chart_recognition=use_chart
            )
            results.extend(chunk_results)
            total_lines = sum(len(r.markdown_text.splitlines()) for r in chunk_results)
            print(f"→ {len(chunk_results)} result(s), {total_lines} lines")

        return results

    # --- Fallback: PPTX → PNG per slide ---
    print("      PDF unavailable, switching to per-slide images...")
    print("\n[1/2] Exporting slides as images...")
    images = convert_to_images(pptx_path, tmp_dir / "slides")
    print(f"      {len(images)} slides exported")

    print(f"\n[2/2] Sending {len(images)} slides to API...")
    results = []
    for i, img_path in enumerate(images, 1):
        print(f"  Slide {i:>3}/{len(images)}: {img_path.name}", end="  ", flush=True)
        slide_results = client.parse_file(
            img_path, file_type=1, use_chart_recognition=use_chart
        )
        results.extend(slide_results)
        total_lines = sum(len(r.markdown_text.splitlines()) for r in slide_results)
        print(f"→ {total_lines} lines")

    return results


def process_pdf(
    pdf_path: Path,
    output_dir: Optional[Path] = None,
    *,
    keep_temp: bool = False,
    use_chart_recognition: bool = False,
    api_url: Optional[str] = None,
    api_token: Optional[str] = None,
    api_timeout: Optional[int] = None,
    resume: bool = True,
    progress_callback=None,
) -> Path:
    """
    直接处理 PDF（不经过 PPTX 转换）。支持断点续传。

    Args:
        pdf_path: Input PDF file.
        output_dir: Where to write results (default: <pdf_stem>_ocr/ next to file).
        keep_temp: Keep intermediate files for debugging.
        use_chart_recognition: Ask the API to analyze charts (slower).
        api_url: Override PADDLEOCR_API_URL from .env.
        api_token: Override PADDLEOCR_TOKEN from .env.
        api_timeout: Override PADDLEOCR_TIMEOUT from .env.
        resume: If True, load existing chunk checkpoints and skip completed chunks.
        progress_callback: Optional callable(done, total, msg) for progress updates.

    Returns:
        Path to result.md.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"File not found: {pdf_path}")

    if output_dir is None:
        output_dir = pdf_path.parent / (pdf_path.stem + "_ocr")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _url = api_url or PADDLEOCR_API_URL
    _token = api_token or PADDLEOCR_TOKEN
    _timeout = api_timeout or PADDLEOCR_TIMEOUT

    if not _token:
        raise ValueError(
            "PADDLEOCR_TOKEN is not set.\n"
            "Open .env and fill in: PADDLEOCR_TOKEN=your_token_here"
        )

    client = LayoutParsingClient(_url, _token, _timeout)

    print(f"File : {pdf_path.name}  ({pdf_path.stat().st_size // 1024} KB)")
    print(f"API  : {_url}")
    print(f"Out  : {output_dir}")
    print()

    # Checkpoint paths
    ck_dir = output_dir / "_chunks"
    ck_file = output_dir / "checkpoint.json"
    img_dir = output_dir / "images"
    ck_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(exist_ok=True)

    # Load existing checkpoint
    done_chunks: set[int] = set()
    if resume and ck_file.exists():
        try:
            ck = json.loads(ck_file.read_text(encoding="utf-8"))
            done_chunks = set(ck.get("done", []))
            _total_ck = ck.get("total", "?")
            print(f"[RESUME] Checkpoint found: {len(done_chunks)}/{_total_ck} chunks already done")
        except Exception:
            done_chunks = set()

    tmp_dir = Path(tempfile.mkdtemp(prefix="pptx_ocr_"))
    try:
        total_pages = pdf_page_count(pdf_path)
        size_kb = pdf_path.stat().st_size // 1024
        n_chunks = (total_pages + PDF_CHUNK_SIZE - 1) // PDF_CHUNK_SIZE
        print(f"[1/2] PDF ready: {total_pages} pages, {size_kb} KB")
        print(f"      Splitting into {n_chunks} chunks of {PDF_CHUNK_SIZE} pages each")

        chunks = split_pdf(pdf_path, tmp_dir / "chunks", chunk_size=PDF_CHUNK_SIZE)
        total_chunks = len(chunks)
        print(f"\n[2/2] Sending {total_chunks} PDF chunks to API...")

        for i, chunk_path in enumerate(chunks):
            page_start = i * PDF_CHUNK_SIZE + 1
            page_end = min((i + 1) * PDF_CHUNK_SIZE, total_pages)
            chunk_kb = chunk_path.stat().st_size // 1024
            ck_md_path = ck_dir / f"chunk_{i:04d}.md"

            # Skip already-done chunks
            if i in done_chunks and ck_md_path.exists():
                print(
                    f"  Chunk {i+1:>3}/{total_chunks}  "
                    f"(pages {page_start}-{page_end}) [cached, skip]"
                )
                if progress_callback:
                    progress_callback(len(done_chunks), total_chunks,
                                      f"续传: 已跳过 {len(done_chunks)} 块，正在处理第 {i+2} 块...")
                continue

            print(
                f"  Chunk {i+1:>3}/{total_chunks}  "
                f"(pages {page_start}-{page_end}, {chunk_kb} KB) ...",
                end="  ",
                flush=True,
            )
            if progress_callback:
                progress_callback(len(done_chunks), total_chunks,
                                  f"OCR 处理第 {i+1}/{total_chunks} 块 (第 {page_start}-{page_end} 页)...")

            chunk_results = client.parse_file(
                chunk_path, file_type=0, use_chart_recognition=use_chart_recognition
            )
            total_lines = sum(len(r.markdown_text.splitlines()) for r in chunk_results)
            print(f"-> {len(chunk_results)} result(s), {total_lines} lines")

            # Localize images and save immediately to output_dir/images/
            chunk_md_parts: list[str] = []
            for r in chunk_results:
                md_text = r.markdown_text
                for rel_path, img_bytes in r.images.items():
                    local_name = Path(rel_path).name
                    (img_dir / local_name).write_bytes(img_bytes)
                    md_text = md_text.replace(rel_path, f"images/{local_name}")
                chunk_md_parts.append(md_text.strip())

            # Persist chunk markdown to checkpoint
            ck_md_path.write_text("\n\n---\n\n".join(chunk_md_parts), encoding="utf-8")

            # Update checkpoint index
            done_chunks.add(i)
            ck_file.write_text(
                json.dumps({"total": total_chunks, "done": sorted(done_chunks)}, ensure_ascii=False),
                encoding="utf-8",
            )

        # All chunks done — assemble final result.md from chunk files
        md_path = _assemble_from_chunks(pdf_path, total_chunks, ck_dir, output_dir)

        # Clean up checkpoint artifacts on success
        if not keep_temp:
            shutil.rmtree(ck_dir, ignore_errors=True)
            if ck_file.exists():
                ck_file.unlink(missing_ok=True)

    finally:
        if not keep_temp:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        else:
            print(f"[DEBUG] Temp dir kept: {tmp_dir}")

    print(f"\n[DONE] {md_path}")
    return md_path


def _assemble_from_chunks(
    source_path: Path,
    total_chunks: int,
    ck_dir: Path,
    output_dir: Path,
) -> Path:
    """从检查点分块文件组装最终 result.md。"""
    img_dir = output_dir / "images"
    img_dir.mkdir(exist_ok=True)

    header = "\n".join([
        f"# {source_path.stem}",
        "",
        f"> Source: `{source_path.name}`",
        f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> Chunks processed: {total_chunks}",
        "",
        "---",
        "",
    ])

    body_parts: list[str] = []
    page_num = 1
    for i in range(total_chunks):
        ck_md_path = ck_dir / f"chunk_{i:04d}.md"
        if not ck_md_path.exists():
            continue
        chunk_md = ck_md_path.read_text(encoding="utf-8").strip()
        # Each chunk may contain multiple pages separated by "---"
        for page_md in chunk_md.split("\n\n---\n\n"):
            page_md = page_md.strip()
            if page_md:
                if total_chunks > 1:
                    body_parts.append(f"## Page {page_num}\n")
                body_parts.append(page_md)
                body_parts.append("\n\n---\n")
                page_num += 1

    md_path = output_dir / "result.md"
    md_path.write_text(header + "\n".join(body_parts), encoding="utf-8")

    img_count = len(list(img_dir.iterdir())) if img_dir.exists() else 0
    print(f"\nSaved: {md_path.name}  ({md_path.stat().st_size // 1024} KB)")
    if img_count:
        print(f"       {img_count} image(s) in images/")

    return md_path


def _save_results(
    pptx_path: Path,
    results: list[ParseResult],
    output_dir: Path,
) -> Path:
    img_dir = output_dir / "images"
    img_dir.mkdir(exist_ok=True)

    header = "\n".join([
        f"# {pptx_path.stem}",
        "",
        f"> Source: `{pptx_path.name}`",
        f"> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"> Pages/slides processed: {len(results)}",
        "",
        "---",
        "",
    ])

    body_parts: list[str] = []
    for i, result in enumerate(results, 1):
        md_text = result.markdown_text

        # Download and localise image references
        for rel_path, img_bytes in result.images.items():
            local_name = Path(rel_path).name
            (img_dir / local_name).write_bytes(img_bytes)
            # Replace whatever path/URL the API used with a local reference
            md_text = md_text.replace(rel_path, f"images/{local_name}")

        if len(results) > 1:
            body_parts.append(f"## Page {i}\n")
        body_parts.append(md_text.strip())
        body_parts.append("\n\n---\n")

    md_path = output_dir / "result.md"
    md_path.write_text(header + "\n".join(body_parts), encoding="utf-8")

    img_count = len(list(img_dir.iterdir()))
    print(f"\nSaved: {md_path.name}  ({md_path.stat().st_size // 1024} KB)")
    if img_count:
        print(f"       {img_count} image(s) in images/")

    return md_path

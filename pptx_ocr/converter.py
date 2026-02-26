"""
PPTX → PDF or PPTX → PNG images conversion.

Priority:
  1. Windows COM (requires Microsoft Office / pywin32) — best quality
  2. LibreOffice headless — good quality, free
  Raises RuntimeError if neither is available.

PDF is preferred over per-slide images: one API call vs. N calls.
"""
import subprocess
import shutil
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# PPTX → PDF
# ---------------------------------------------------------------------------

def _win32com_to_pdf(pptx_path: Path, pdf_path: Path) -> bool:
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return False
    try:
        ppt = win32com.client.Dispatch("PowerPoint.Application")
        ppt.Visible = True
        presentation = ppt.Presentations.Open(str(pptx_path.resolve()))
        presentation.SaveAs(str(pdf_path.resolve()), 32)  # 32 = ppSaveAsPDF
        presentation.Close()
        ppt.Quit()
        return pdf_path.exists()
    except Exception as e:
        print(f"  [win32com→PDF] {e}")
        return False


def _libreoffice_to_pdf(pptx_path: Path, pdf_path: Path) -> bool:
    out_dir = pdf_path.parent
    for cmd in ["libreoffice", "soffice"]:
        if not shutil.which(cmd):
            continue
        try:
            subprocess.run(
                [cmd, "--headless", "--convert-to", "pdf",
                 "--outdir", str(out_dir), str(pptx_path)],
                check=True,
                capture_output=True,
                timeout=180,
            )
            generated = out_dir / (pptx_path.stem + ".pdf")
            if generated.exists():
                if generated != pdf_path:
                    generated.rename(pdf_path)
                return True
        except Exception as e:
            print(f"  [LibreOffice→PDF] {e}")
    return False


def convert_to_pdf(pptx_path: Path, output_dir: Path) -> Optional[Path]:
    """
    Convert PPTX to PDF. Returns the PDF path on success, None if unavailable.
    """
    pptx_path = Path(pptx_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / (pptx_path.stem + ".pdf")

    print("  Trying Windows COM (PowerPoint)...", end=" ", flush=True)
    if _win32com_to_pdf(pptx_path, pdf_path):
        print("OK")
        return pdf_path
    print("not available")

    print("  Trying LibreOffice...", end=" ", flush=True)
    if _libreoffice_to_pdf(pptx_path, pdf_path):
        print("OK")
        return pdf_path
    print("not available")

    return None


# ---------------------------------------------------------------------------
# PPTX → PNG per slide (fallback when PDF conversion is unavailable)
# ---------------------------------------------------------------------------

def _win32com_to_images(pptx_path: Path, output_dir: Path) -> Optional[list[Path]]:
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return None
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        ppt = win32com.client.Dispatch("PowerPoint.Application")
        ppt.Visible = True
        presentation = ppt.Presentations.Open(str(pptx_path.resolve()))
        paths: list[Path] = []
        for i in range(1, presentation.Slides.Count + 1):
            img_path = output_dir / f"slide_{i:03d}.png"
            presentation.Slides(i).Export(str(img_path.resolve()), "PNG")
            paths.append(img_path)
        presentation.Close()
        ppt.Quit()
        return paths or None
    except Exception as e:
        print(f"  [win32com→images] {e}")
        return None


def convert_to_images(pptx_path: Path, output_dir: Path) -> list[Path]:
    """
    Export each slide as a PNG image.
    Returns sorted list of image paths.
    Raises RuntimeError if conversion is not possible.
    """
    pptx_path = Path(pptx_path)
    output_dir = Path(output_dir)

    print("  Trying Windows COM (slide export)...", end=" ", flush=True)
    result = _win32com_to_images(pptx_path, output_dir)
    if result:
        print("OK")
        return sorted(result)
    print("not available")

    raise RuntimeError(
        "Cannot convert slides to images.\n"
        "Options:\n"
        "  1. Install Microsoft Office + pip install pywin32\n"
        "  2. Install LibreOffice (https://www.libreoffice.org/)"
    )

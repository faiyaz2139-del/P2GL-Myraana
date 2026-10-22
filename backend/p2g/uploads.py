"""Classify shop uploads. Only PDF bytes enter the print-ready pipeline.

Raster images are placed at their own pixel size and DPI, never stretched
to the job. AI, EPS and PSD are stored and blocked until exported to PDF.
"""
import io

from p2g.catalog_seed import SpecError


_TYPES = {"jpg", "jpeg", "gif", "png", "eps", "ai", "pdf", "psd"}


def classify_upload(filename, data, accepted):
    accepted = {item.lower() for item in (accepted or _TYPES)}
    ext = ""
    name = filename or ""
    if "." in name:
        ext = name.rsplit(".", 1)[-1].lower()
    if ext not in accepted or ext not in _TYPES:
        raise SpecError("Upload a JPG, JPEG, GIF, PNG, EPS, AI, PDF or PSD file.")
    kind = _magic(data)
    if kind == "pdf" and ext in {"pdf", "ai"}:
        return "pdf"
    if ext in {"jpg", "jpeg"} and kind == "jpeg":
        return "raster"
    if ext == "png" and kind == "png":
        return "raster"
    if ext == "gif" and kind == "gif":
        return "raster"
    if ext == "pdf" and kind == "pdf":
        return "pdf"
    if ext == "psd" and kind == "psd":
        return "psd"
    if ext == "eps" and kind in {"eps", "unknown"}:
        return "eps"
    if ext == "ai" and kind in {"eps", "unknown"}:
        return "ai"
    raise SpecError("The file contents do not match its extension. Export a fresh file and upload it again.")


def _magic(data):
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data.startswith(b"8BPS"):
        return "psd"
    if data.startswith(b"%!PS") or data.startswith(b"\xc5\xd0\xd3\xc6"):
        return "eps"
    return "unknown"


def raster_to_pdf(data, fallback_dpi=300):
    """Place a raster image on a PDF page at its native size. No scaling."""
    from PIL import Image
    import pymupdf

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as error:
        raise SpecError("The image could not be read. Export a fresh JPG, PNG or GIF.") from error
    dpi_info = image.info.get("dpi") or (fallback_dpi, fallback_dpi)
    try:
        dpi_x = float(dpi_info[0] or fallback_dpi)
        dpi_y = float(dpi_info[1] or dpi_x)
    except (TypeError, ValueError):
        dpi_x = dpi_y = float(fallback_dpi)
    if dpi_x < 1 or dpi_y < 1:
        dpi_x = dpi_y = float(fallback_dpi)
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    width = image.width / dpi_x * 72
    height = image.height / dpi_y * 72
    document = pymupdf.open()
    try:
        page = document.new_page(width=width, height=height)
        page.insert_image(page.rect, stream=buffer.getvalue())
        return document.tobytes()
    finally:
        document.close()


def prepare_artwork(data, source_kind, output_dpi):
    if source_kind == "pdf":
        return data
    if source_kind == "raster":
        return raster_to_pdf(data, output_dpi or 300)
    raise SpecError(
        "Export AI, EPS and PSD artwork to PDF before preflight. "
        "The original file is saved. Myraana does not convert those formats."
    )

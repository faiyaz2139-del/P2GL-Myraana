import io
import tempfile
from pathlib import Path

from PIL import Image
from reportlab.lib.colors import blue
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from p2g.pdfcheck import inspect


RECIPE = {
    "width": 3.5,
    "height": 2.0,
    "bleed": 0.125,
    "safe": 0.125,
    "minDpi": 300,
}


def artwork(width=3.75, height=2.25, pages=1, text=None, low_resolution=False):
    output = io.BytesIO()
    document = canvas.Canvas(output, pagesize=(width * 72, height * 72))
    for _ in range(pages):
        document.setFillColor(blue)
        document.rect(0, 0, width * 72, height * 72, fill=1, stroke=0)
        if text:
            document.setFillColorRGB(1, 1, 1)
            document.drawString(text[0], text[1], text[2])
        if low_resolution:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                image_path = Path(handle.name)
            try:
                Image.new("RGB", (50, 50), "red").save(image_path)
                document.drawImage(ImageReader(str(image_path)), 20, 20, width=3 * 72, height=2 * 72)
            finally:
                image_path.unlink(missing_ok=True)
        document.showPage()
    document.save()
    return output.getvalue()


def test_valid_double_sided_artwork_passes_preflight():
    report = inspect(artwork(pages=2), RECIPE, 2)
    assert report["errors"] == []


def test_missing_bleed_requires_human_decision_without_stretching():
    report = inspect(artwork(width=3.5, height=2.0), RECIPE, 1)
    assert report["errors"] == []
    assert report["bleed"] == "missing"


def test_unsafe_text_stops_with_corrective_action():
    report = inspect(artwork(text=(2, 2, "Trim risk")), RECIPE, 1)
    assert any("protected safe margin" in item for item in report["errors"])
    assert any("Move essential text" in item for item in report["actions"])


def test_low_resolution_image_stops():
    report = inspect(artwork(low_resolution=True), RECIPE, 1)
    assert any("minimum is 300 dpi" in item for item in report["errors"])


def test_wrong_dimensions_stop_without_scaling():
    report = inspect(artwork(width=4, height=3), RECIPE, 1)
    assert any("does not match the recipe" in item for item in report["errors"])


def test_unembedded_text_font_stops():
    report = inspect(artwork(text=(40, 60, "Font evidence")), RECIPE, 1)
    assert any("not embedded" in item for item in report["errors"])
"""Render a checklist row's checkbox strip to a JPEG (base64 data URL) for the
vision checkbox detector. Port of the SPA getCheckboxStripImage.

NOTE: the crop offsets below mirror the pdf.js version (cropX=170, cropW=160,
PADDING=30 at scale 2). pdf.js uses a bottom-left origin; PyMuPDF a top-left one.
The Y conversion must match engine.pdf_items. ** Needs visual calibration on
real PDFs before relying on it. **
"""
import io
import base64
import fitz

SCALE = 2.0
CROP_X = 170 * SCALE
CROP_W = 160 * SCALE
PADDING = 30 * SCALE


def strip_for_anchor(page, anchor_y_pdfjs):
    """anchor_y_pdfjs is in bottom-left (pdf.js) space, as produced by
    engine.pdf_items. Returns a base64 'data:image/jpeg' URL."""
    H = page.rect.height
    # Render full page at SCALE, then crop the checkbox band around the anchor.
    pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE))
    # Convert anchor to top-left device space.
    canvas_y = (H - anchor_y_pdfjs) * SCALE - PADDING
    crop_h = PADDING * 2
    clip = fitz.IRect(int(CROP_X), int(canvas_y), int(CROP_X + CROP_W), int(canvas_y + crop_h))
    clip = clip & fitz.IRect(0, 0, pix.width, pix.height)
    sub = pix.pixmap_from_clip(clip) if hasattr(pix, "pixmap_from_clip") else None
    img_bytes = (sub or pix).tobytes("jpeg")
    return "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode()

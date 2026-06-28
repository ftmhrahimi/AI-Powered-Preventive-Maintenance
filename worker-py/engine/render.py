"""Render a checklist row's checkbox strip to a JPEG (base64 data URL) for the
vision checkbox detector. Port of the SPA getCheckboxStripImage.

Geometry mirrors the pdf.js version exactly: the browser cropped a 160pt-wide,
60pt-tall band (PADDING=30 above/below the row) starting at x=170pt, rendered at
2× scale. pdf.js uses a bottom-left origin; PyMuPDF a top-left one, so we convert
the anchor with `H - anchor_y` (same as engine.pdf_items). The crop is applied
via get_pixmap(clip=…) so ONLY the row's strip is sent to the LLM — sending the
whole page would make the "which checkbox is ticked" question unanswerable.
"""
import base64
import fitz

SCALE = 2.0
CROP_X = 170      # pdf points (unscaled); matches browser cropX/SCALE
CROP_W = 160      # pdf points
PADDING = 30      # pdf points above and below the anchor row


def strip_for_anchor(page, anchor_y_pdfjs):
    """anchor_y_pdfjs is in bottom-left (pdf.js) space, as produced by
    engine.pdf_items. Returns a base64 'data:image/jpeg' URL of just the row."""
    H = page.rect.height
    top = (H - anchor_y_pdfjs) - PADDING          # top-left Y of the strip
    clip = fitz.Rect(CROP_X, top, CROP_X + CROP_W, top + PADDING * 2) & page.rect
    pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE), clip=clip)
    return "data:image/jpeg;base64," + base64.b64encode(pix.tobytes("jpeg")).decode()

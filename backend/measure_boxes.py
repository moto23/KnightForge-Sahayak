"""Detect the printed box grid on a raster form page by pixel projection.

HDFC's PDF carries no text and no vector drawings - it is one scanned image per
page - so layout rectangles cannot be derived from the document model. They are
recovered here from the pixels instead: long dark runs are ruled lines, and the
cells they bound are the comb boxes a value must be written into.

Throw-away measuring aid, not part of the application.
"""
import sys
import fitz

SCALE = 4.0  # render at 4 px per point for sub-point accuracy


def load(form: str, pno: int):
    d = fitz.open(f"../samples/forms/{form}.pdf")
    pix = d[pno].get_pixmap(matrix=fitz.Matrix(SCALE, SCALE), colorspace=fitz.csGRAY)
    # stride, not width: PyMuPDF pads rows. The rules on this scan are light
    # grey (~150-200), never black, so the darkness threshold must be generous.
    out = pix.stride, pix.height, pix.samples
    d.close()
    return out


def lines(form: str, pno: int, y0: float, y1: float, x0: float, x1: float):
    w, h, buf = load(form, pno)
    px0, px1 = int(x0 * SCALE), min(w, int(x1 * SCALE))
    py0, py1 = int(y0 * SCALE), min(h, int(y1 * SCALE))
    span = px1 - px0

    # Horizontal rules: rows where most pixels across the span are dark.
    hrows = []
    for y in range(py0, py1):
        dark = sum(1 for x in range(px0, px1, 2) if buf[y * w + x] < 215)
        if dark > span * 0.30 / 2:
            hrows.append(y)
    # Vertical rules: columns dark down most of the band.
    vcols = []
    height = py1 - py0
    for x in range(px0, px1):
        dark = sum(1 for y in range(py0, py1, 2) if buf[y * w + x] < 215)
        if dark > height * 0.55 / 2:
            vcols.append(x)

    def group(values):
        out, run = [], []
        for v in values:
            if run and v - run[-1] > 2:
                out.append(sum(run) / len(run)); run = []
            run.append(v)
        if run:
            out.append(sum(run) / len(run))
        return [round(v / SCALE, 1) for v in out]

    return group(hrows), group(vcols)


if __name__ == "__main__":
    form, pno = sys.argv[1], int(sys.argv[2])
    y0, y1, x0, x1 = (float(v) for v in sys.argv[3:7])
    hz, vt = lines(form, pno, y0, y1, x0, x1)
    print(f"{form} p{pno}  y[{y0},{y1}] x[{x0},{x1}]")
    print(f"  horizontal rules ({len(hz)}): {hz}")
    print(f"  vertical rules  ({len(vt)}): {vt[:60]}")
    if len(vt) > 1:
        widths = [round(vt[i+1] - vt[i], 2) for i in range(len(vt) - 1)]
        print(f"  cell widths: {widths[:20]}")

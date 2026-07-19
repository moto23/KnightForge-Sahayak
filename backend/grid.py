"""Render a form page with a POINT-coordinate grid overlaid, for measuring
layout rectangles by eye. Throw-away measuring aid."""
import sys, fitz
form, pno = sys.argv[1], int(sys.argv[2])
step = int(sys.argv[3]) if len(sys.argv) > 3 else 50
crop = [float(v) for v in sys.argv[4:8]] if len(sys.argv) > 7 else None
src = fitz.open(f"../samples/forms/{form}.pdf")
page = src[pno]
out = fitz.open(); dst = out.new_page(width=page.rect.width, height=page.rect.height)
dst.show_pdf_page(page.rect, src, pno)
for x in range(0, int(page.rect.width) + 1, step):
    dst.draw_line(fitz.Point(x, 0), fitz.Point(x, page.rect.height),
                  color=(1, 0, 0), width=0.4)
    dst.insert_text(fitz.Point(x + 1, 9), str(x), fontsize=6, color=(1, 0, 0))
for y in range(0, int(page.rect.height) + 1, step):
    dst.draw_line(fitz.Point(0, y), fitz.Point(page.rect.width, y),
                  color=(0, 0.5, 1), width=0.4)
    dst.insert_text(fitz.Point(1, y - 1), str(y), fontsize=6, color=(0, 0.5, 1))
clip = fitz.Rect(*crop) if crop else None
pix = dst.get_pixmap(dpi=190 if crop else 130, clip=clip)
pix.save(f"../samples/rendered/_grid-{form}-p{pno}.png")
print("saved", f"_grid-{form}-p{pno}.png", "clip", crop or "full")
src.close(); out.close()

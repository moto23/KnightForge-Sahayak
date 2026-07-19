"""Locate a choice option's printed caption and derive its tick-box rectangle.

On every one of these forms the box sits immediately to the LEFT of its
caption, on the same baseline. This reports each candidate with its page and
derived rectangle so mappings can be recorded as verified `option_rects`
instead of guessed at runtime.

Throw-away measuring aid.
"""
import sys
import fitz
from app.infrastructure.pdf.form_placement_engine import FormPlacementEngine

E = FormPlacementEngine()


def find(form: str, caption: str, page_filter=None):
    d = fitz.open(f"../samples/forms/{form}.pdf")
    out = []
    for page in d:
        if page_filter is not None and page.number != page_filter:
            continue
        for x0, y0, x1, y1 in E._find_caption(page, caption):
            size = max(6.0, min(10.0, y1 - y0 + 2))
            out.append((page.number,
                        round(x0 - size - 3.0, 1), round(y0 - 1, 1),
                        round(x0 - 2.0, 1), round(y1 + 1, 1)))
    d.close()
    return out


if __name__ == "__main__":
    form = sys.argv[1]
    for caption in sys.argv[2:]:
        hits = find(form, caption)
        tag = "UNIQUE" if len(hits) == 1 else (f"x{len(hits)}" if hits else "MISSING")
        print(f"  {caption:26} {tag:8} {hits[:4]}")

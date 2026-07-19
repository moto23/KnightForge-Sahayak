# Performance notes

Measurements taken on a dev workstation (fast multi-core CPU). Absolute numbers
on Render Free are considerably worse; the *ratios* are what matter here.

## Auth restore vs. cold starts

The frontend already models auth as three states (`restoring | authenticated |
anonymous`) with a Strict-Mode-safe boot guard — that part was correct and is
unchanged.

The defect was the timeout. `/auth/refresh` inherited the API client's 20s
default, but a sleeping free-tier backend does not *refuse* the first request —
it queues it and answers a cold start later. Reproduced against a stub that
answers after 25s:

| attempt | ceiling | outcome |
| --- | --- | --- |
| old | 20s | fails at 20.0s → valid session silently demoted to guest |
| new | 75s | succeeds at 25.0s → session preserved |
| guest (401) | 75s | fails at 0.0s → no added delay |

**Retrying is not an option.** `AuthService.refresh` rotates the refresh token
single-use and treats a replayed token as theft, revoking *every* session for
that user. After an ambiguous timeout the client cannot know whether the server
already rotated, so a retry risks signing the user out everywhere. A longer
ceiling on a single attempt is the safe fix; POSTs remain un-retried.

## OCR is genuinely CPU-bound (confirmed)

Per page, `samples/forms/cvl.pdf` at the configured 300 DPI:

| stage | time |
| --- | --- |
| PDF open/parse | 0.04s |
| render to PNG @300 DPI | 0.34s |
| **Tesseract recognition** | **4.10s** |

Of that 4.10s: the OSD orientation probe is **2.05s** and the actual
recognition pass is 1.53s. So orientation detection — which only decides
*whether to rotate* — costs more than reading the page.

### Rejected: running OSD on a downscaled copy

Tempting, because OSD does not obviously need 300 DPI. Tested across 8 sample
documents × 4 rotations (32 cases), full-resolution OSD vs. a copy capped at
1600px on the long edge: **~40% faster, but 5/32 verdicts disagreed.**

Most disagreements are harmless once `_OSD_MIN_CONFIDENCE = 2.0` is applied
(both resolutions fall below the gate, so neither rotates), and one case
(`pan` @270) actually improves. But **`hdfc` @90 regresses for real**: full
resolution returns 270 at confidence 11.20 (correctly rotated), while the
downscaled copy returns 90 at 0.83 — under the gate, so a genuinely rotated
page would be OCR'd sideways.

A two-stage variant (downscaled probe, falling back to full resolution when
inconclusive) preserves accuracy on all 32 cases, but pays *both* costs
whenever the probe is inconclusive — some documents get slower, not faster —
and adds a branch to the most accuracy-critical path. Not shipped: the win is
inconsistent and the corpus is only 8 documents.

**Conclusion:** OCR latency here is real CPU work, not waste. The remaining
levers are more CPU or a cloud OCR adapter (the `OCRProvider` port already
allows the latter as a one-line binding change) — not tuning.

## Backend cold start

`import app.main` costs ~8.3s locally, dominated by the import graph rather
than by composition:

- `google.genai` ~2.4s, `chromadb` ~1.8s, `sqlalchemy.orm` ~0.8s
- singleton construction is already cheap: `OnnxEmbedder()` and
  `ChromaVectorStore()` are lazy (0.000s), Tesseract's version probe 0.05s

Uvicorn binds the port only after this import, so it directly delays readiness
after a cold start. Both heavy imports already sit behind `try/except
ImportError` guards with graceful degradation, so deferring them is
*architecturally* feasible — but it would move the cost onto the first chat
request and risks the verified-working Knowledge Chat path. Left alone
deliberately; revisit only with a measured cold-start budget.

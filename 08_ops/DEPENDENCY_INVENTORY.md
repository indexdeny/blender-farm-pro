> Historical inherited record; not current two-SKU certification. Not independently revalidated. Current status: [release report](../FINAL_PORTFOLIO_RELEASE_REPORT.md).

# Dependency Inventory

> The complete dependency surface, with the versions this deployment was **tested
> with**. For external software whose support window we don't control (Chrome,
> Gemini), the policy is "tested with", not "supported range".

## Runtime — core pipeline (required)

| Dependency | Role | Tested version | Required |
|---|---|---|---|
| Python | Interpreter | 3.10.11 | ✅ (3.10+) |
| selenium | Stage 2 — browser automation | 4.44.0 | ✅ |
| webdriver-manager | Stage 2 — provisions matching chromedriver | 4.1.1 | ✅ |
| Pillow | Stage 3 — image processing → WEBP | 12.2.0 | ✅ |
| PyYAML | `config.yaml` loading | 6.0.3 | ✅ (falls back to defaults if absent) |
| rich | Console logging + run summary | 15.0.0 | ✅ (degrades to plain logging if absent) |
| pydantic | Stage 1 schema models (`schemas/common.py`, via `pharma_pkg` routing) | 2.13.x | ✅ (required for routing) |

Pinned loosely in [`requirements.txt`](../requirements.txt).

## System / external (required for Stage 2)

| Dependency | Role | Tested with | Notes |
|---|---|---|---|
| Google Chrome | Stage 2 browser | current stable channel | Must match a chromedriver (auto via webdriver-manager). |
| Gemini UI (`gemini.google.com`) | Image generation backend | as-is (no version) | **Architectural dependency** — UI changes can break Stage 2 (see Disaster Recovery DR-3). |
| Blender | Stage 2 — the `blender` engine, this fork's **default** (`render.engine` in `config.yaml`) | 5.1.2, `C:\Program Files\Blender Foundation\Blender 5.1\blender.exe` | External executable, never imported — `import bpy` appears only inside `05_assets/blender/render_driver.py`, which runs inside Blender's own bundled interpreter. Not on PATH; `config.yaml`'s `blender.executable` gives the absolute path. `blender.engine_type` must be a real identifier (`CYCLES`, not `EEVEE`) — see CLAUDE.md's "Fork-specific gotchas". |
| Windows | OS | 10/11 | Profile/Downloads paths in `config.yaml` are Windows-shaped. |
| Authenticated Google/Gemini session | Real credential | n/a | Lives in the Chrome profile, **not** an API key. |

## Optional

| Dependency | Tested version | Location | Notes |
|---|---|---|---|
| pytesseract | 0.3.13 | Python package | Installed but commented out in `requirements.txt` — not needed by the core pipeline. Install by hand (`pip install pytesseract`) to run `scripts/render_qa.py` and its test coverage in `tests/test_render_qa.py`. |
| Tesseract OCR | 5.4.0.20240606 | System binary, `C:\Program Files\Tesseract-OCR\tesseract.exe` | Post-render QA (`scripts/render_qa.py`). NOT on PATH; `render_qa` probes the absolute path. Install: `winget install --id UB-Mannheim.TesseractOCR`. Absent → the OCR tests skip. |

## Present but NOT used by the production pipeline

| Dependency | Where used | Status |
|---|---|---|
| opencv-python | `02_processing/cv/` (legacy Stage 0 detection) | Installed (4.13.0.92) but the 3 production Stages do not import it. |
| numpy | `02_processing/cv/`, plus pixel measurement in `tests/` and `scripts/catalogue_sweep.py` | Installed (2.2.6) and now declared in requirements.txt. |
| ultralytics (YOLO) | `02_processing/cv/detect.py` + `yolov8n.pt` | Installed (8.4.47) but undeclared; the legacy CV code is not imported by any of the three stages. |

> Stage 0 (source photo → JSON passport) is a **manual Gemini-in-IDE workflow**
> (`.agents/workflows/analyze-pharma.md`); the `02_processing/cv/` code is legacy from
> an earlier OCR/CV approach and is not part of the automated pipeline.

## Version policy

- **Core pip deps:** upgrade together; re-run the [Acceptance Test](ACCEPTANCE_TEST.md) after any change.
- **Chrome:** record the working version here after each verified upgrade; test Stage 2 after Chrome updates.
- **Gemini UI:** unversioned and outside our control — treated as a monitored fragility.

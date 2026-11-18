> Historical inherited record; not current two-SKU certification. Not independently revalidated. Current status: [release report](../FINAL_PORTFOLIO_RELEASE_REPORT.md).

# Disaster Recovery

> Per-failure playbooks. Each entry: **symptom → impact → recovery → prevention.**
> Backups referenced here are defined in [BACKUP_STRATEGY.md](BACKUP_STRATEGY.md).
> The golden rule: rendered images are **not reproducible** — recover them from
> backup, never assume re-rendering returns the same images.

## DR-1 — SSD / disk failure
- **Symptom:** machine won't boot, or `01_input_raster/gemini_renders_final/` / `01_input_raster/` / `03_knowledge_graph/` unreadable.
- **Impact:** total loss of code + data if not backed up.
- **Recovery:** new machine → follow [DEPLOYMENT.md](DEPLOYMENT.md) → restore from backup: `03_knowledge_graph/`, `04_passports/passports_json/`, `01_input_raster/gemini_renders_final/`, `01_input_raster/gemini_renders_raw/`, `00_PROJECT_STATE/gemini_rpa_progress_v23.txt`, `config.yaml` → run [Acceptance Test](ACCEPTANCE_TEST.md) → `main.py --full --resume`.
- **Prevention:** scheduled backups (3-2-1); keep `01_input_raster/gemini_renders_final/` off the single working SSD.

## DR-2 — Chrome failure or auto-update
- **Symptom:** Stage 2 cannot launch the driver, or every SKU fails at driver init.
- **Impact:** rendering stops (Stages 1 and 3 unaffected).
- **Recovery:** ensure Chrome is installed and reachable; `webdriver-manager` provisions a matching chromedriver automatically — re-run `--render-only --resume`. If a Chrome update broke the matching, clear the webdriver-manager cache so it re-downloads.
- **Prevention:** pin/record the working Chrome version in [DEPENDENCY_INVENTORY.md](DEPENDENCY_INVENTORY.md); test after Chrome updates.

## DR-3 — Gemini changed its DOM / UI
- **Symptom:** repeated failures at the **same stage across many SKUs** (e.g. `send_message`, `wait_for_image_generation`, blob download), not random per-SKU timeouts.
- **Impact:** rendering is fully blocked — this is the highest-risk architectural dependency (browser RPA, no API).
- **Recovery:** stop the run. The selectors live in `src/rpa_orchestrator.py` (`send_message`, `wait_for_image_generation`, `download_blob_image`, response counters). They must be re-aligned to the new Gemini UI — a **development task**, not an operator action. Until then, rendering cannot proceed.
- **Prevention:** treat the selector layer as a known fragility (see Bus Factor audit); keep `01_input_raster/gemini_renders_final/` backed up so a UI outage never costs delivered assets.

## DR-4 — Lost / corrupted progress tracker
- **Symptom:** `00_PROJECT_STATE/gemini_rpa_progress_v23.txt` missing or garbled; resume re-processes everything.
- **Impact:** low — Stage 2 also rebuilds "done" state by **scanning `01_input_raster/gemini_renders_raw/`**, so already-rendered SKUs are still skipped even without the tracker.
- **Recovery:** restore the tracker from backup if available; otherwise just re-run `--render-only --resume` — the raw-dir scan reconstructs progress; only genuinely missing PNGs are re-rendered.
- **Prevention:** include the tracker in backups; never delete `01_input_raster/gemini_renders_raw/`.

## DR-5 — Corrupted SSOT
- **Symptom:** `main.py` pre-flight aborts (exit 2) on `SKU.csv`/`master.json`; or odd routing if a CSV row is malformed.
- **Impact:** Stage 1 cannot run / produces wrong routing.
- **Recovery:** restore `03_knowledge_graph/` from backup; re-run `--passports-only`; confirm `04_passports/passports_markdown/` regenerates identically.
- **Prevention:** `03_knowledge_graph/` is the system of record for inputs — back it up on every change; edit it directly; the one-off sync scripts that used to maintain it were removed as dead (see `scripts/README.md`).

## DR-6 — No network
- **Symptom:** Stage 2 SKUs fail as Selenium timeouts / WebDriver errors.
- **Impact:** rendering only (Stages 1 and 3 are offline-capable).
- **Recovery:** restore connectivity → `--render-only --resume`. Progress is preserved; only un-rendered SKUs run.
- **Prevention:** run rendering on a stable connection; the built-in backoff already absorbs short blips.

## DR-7 — Windows update / reboot mid-run
- **Symptom:** the run is killed; partial output on disk.
- **Impact:** low — equivalent to an interruption.
- **Recovery:** `main.py --full --resume` (or the relevant stage). Per-SKU progress was saved; no duplication.
- **Prevention:** pause Windows updates during long render runs; rely on resume otherwise.

---

## Recovery quick-reference

| Lost | Recoverable? | How |
|---|---|---|
| Code | ✅ | git |
| `04_passports/passports_markdown/` | ✅ | regenerate Stage 1 (deterministic) |
| `00_PROJECT_STATE/gemini_rpa_progress_v23.txt` | ✅ | rebuilt from `01_input_raster/gemini_renders_raw/` scan |
| `03_knowledge_graph/`, `04_passports/passports_json/` (inputs) | ⚠️ backup only | not regenerable in-repo (Stage 0 is manual) |
| `01_input_raster/gemini_renders_raw/`, `01_input_raster/gemini_renders_final/` (images) | 🔴 backup only | **non-deterministic** — re-render yields *different* images |

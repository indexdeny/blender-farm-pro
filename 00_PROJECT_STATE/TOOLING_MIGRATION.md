# Tooling migration — vtracer, scikit-image/shapely, perceptual colour

Three installed-but-unwired tools brought into the design-transfer chain
(reference photograph → `design_spec` → manifest → curves in Blender), one at a
time, each with a measured delta and a named rollback.

Rules this document is kept under, taken from the brief:

- **One cause per measuring event.** Two changes in one report attribute nothing.
- A step is accepted only if the group figure rises, no carton loses more than
  the threshold named in that step, and every loser is listed here by name.
- Figures are recomputed by their scripts, never edited by hand.
- `00_PROJECT_STATE/baseline_2026-08-24/` is the only source for a "before"
  column and does not change once written.

---

## Phase 0 — Discovery

Read-only. No code changed. Completed 2026-08-24.

### 0.1 Installed versions (measured by import, not by reading a lockfile)

| import | distribution | version | declared in `requirements.txt` today |
|---|---|---|---|
| `numpy` | numpy | 2.2.6 | yes (`>=1.24`) |
| `PIL` | Pillow | 12.2.0 | yes (`>=10.0.0`) |
| `jsonschema` | jsonschema | 4.26.0 | yes (`>=4.0`) |
| `yaml` | PyYAML | 6.0.2 | yes (`>=6.0`) |
| `pydantic` | pydantic | 2.13.3 | yes (`>=2.0`) |
| `scipy` | scipy | 1.15.3 | **no** |
| `skimage` | scikit-image | 0.25.2 | **no** |
| `cv2` | opencv-python | 4.10.0 | **no** |
| `shapely` | shapely | 2.1.2 | **no** |
| `vtracer` | vtracer | 0.6.15 | **no** |

Python 3.10.11. Note `vtracer` reports **0.6.15** as a distribution while the SVG
it emits is stamped `VTracer 0.6.12` in its generator comment — the wheel bundles
an older core. The generator string is what a future reader should compare
against, since it is what actually drew the paths.

### 0.2 Baseline test run (before any change)

```
python -m unittest discover -s tests
Ran 354 tests in 579.358s
OK (skipped=5)
```

Green. No pre-existing failure, so the brief's "stop if it was already broken"
condition does not fire.

Re-run after `requirements.txt` gained its four lines (Phase 0 step 5) —
**354 tests, OK, 5 skipped, 567.518s**. Declaring a dependency changes nothing,
as expected: nothing imports `requirements.txt`. Recorded because the brief asks
for the check, and because a formality that is skipped is indistinguishable from
one that failed.

### 0.2a Baseline design figures

`python scripts/design_coverage.py --out
00_PROJECT_STATE/baseline_2026-08-24/design_coverage.json`, over 28 folders:

| figure | baseline |
|---|---|
| `pixel_agreement` | **99.18%** |
| `print_agreement` | **52.79%** |
| `truth_agreement` | **95.36%** |
| `spec_off_print_pct` | **0.76%** |

`151-min`, `230-min` and `346-min` return `n/a` rather than `0.0` for
`truth_agreement`: they carry no `print` component, so there is nothing to agree
about. Excluded from every acceptance test here **by name**.

This 95.36% is not the 95.59% `CLAUDE.md` quotes. That figure was taken at an
earlier moment; 95.36% is what the instrument returns against today's tree, and
it is what "before" means for this migration.

### 0.3 `scripts/fit_design_spec.py` — the order `fit()` actually runs in

```
segment(folder)                          # D-1 partition, shared with measure_reference_face
  -> load_truth(folder)                  # print_truth.json; absent -> SystemExit
  -> front_face_px equality check        # stale corners -> SystemExit
  -> hole_min_frac equality check        # relabelled at another floor -> SystemExit
  -> components(lab == j, min_region)    # per role, area-descending, 4-connected
      -> label_of[key] != "print"  -> dropped (counted by class), never drawn
      -> trace_outline(part)             # Moore boundary of the largest blob
      -> _simplify_to_a_region(...)      # Douglas-Peucker + simple_ring backoff
      -> trace_holes(part, ...)          # enclosed_background -> only `window` cut
      -> part_kind(pts, holes)           # "block" | "field"
      -> _smoothness(pts)                # written to spec
  -> verify(...)                         # pixel_agreement, iou_by_field, vertices
  -> carry `type_rows` / `type_rows_note` forward from the spec on disk
  -> write design_spec.json
```

**Dead after Phase B, confirmed by grep over the whole tree:** `is_design_field`,
`fills_its_box`, `_despeckle`, `_runs_off_face`, and the constants
`MIN_REGION_FRAC`, `MIN_FILL_CONTRAST`, `BOX_FILL_MIN`. Nothing calls them; they
survive as prose recording the rule the label replaced. `_despeckle` is reachable
only through `fills_its_box`, so it is dead too.

**Live:** `trace_outline` (outer ring and every hole), `components`,
`enclosed_background`, `simplify`, `_simplify_to_a_region`, `part_kind`,
`_smoothness`, `part_region`, `rasterise`, `verify`.

`_smoothness` is **computed, stored in the spec, copied into the manifest,
described in the schema — and read by nobody.** Confirmed by grep: the only
non-data hits are its own definition and documentation. This is the field the
brief asks for a decision on in step 29.

### 0.4 `src/design_group.py`

- `TEMPLATE_SAMPLE` — 28 folders; `FOLDER_BY_STEM` its inverse.
- `load_design(sku_id)` — the single loader. Returns `None` outside the group,
  raises `MissingDesignSpec` inside it. Repairs tangled rings **at load**, not on
  disk, and records `simplified_from` / `holes_simplified_from`.
- `simple_ring(poly)` / `RingRepairFailed` — drops the fewest vertices that
  untangle a ring, scored on the ring's **even-odd fill** (`_filled` ->
  `_fill_iou`), refusing below `RING_REPAIR_MIN_IOU = 0.90`.
- `ring_crossings(poly)` — grid-indexed all-pairs edge crossing test. Operates on
  a **polyline**; two cubic Béziers can cross without any of their flattening
  segments crossing at a coarse step, which is why step 18 exists.

### 0.5 The manifest contract

- `src/render_manifest.py`: `MANIFEST_VERSION = "1.8"`; `_design_block()` trims
  the spec to `spec_version`, `face_aspect`, `substrate`, `fields`, `type_rows`,
  `source_image`.
- `schemas/render_manifest.schema.json`: `manifest_version` is pinned with
  `"const": "1.8"`. Inside `design.fields[].parts[]`, **`outline` and `holes` are
  both required**; `area_pct`, `smoothness`, `kind` are optional.
- Self-intersection is **not** expressible in JSON Schema, so
  `validate_manifest()` calls `_reject_tangled_outlines()` after the schema
  validator, on both write and load, over the outline and every hole.

### 0.6 `05_assets/blender/render_driver.py`

- `build_design_fields()` (line 1710) is the only place design geometry is built.
  Per part it creates one `CURVE`, `dimensions="2D"`, `fill_mode="BOTH"`,
  `extrude=half_thick`; `_ring()` adds a **`POLY`** spline with
  `use_cyclic_u = True`, outer ring first and each hole as a further spline of the
  **same** curve. Missing `z` -> `SystemExit`; missing `holes` -> `SystemExit`.
- `--dump-scene` emits per design object: `name`, `bounds_in_carton_frame`,
  `base_color`, `roughness`, `splines` (count), `fill_area_m2`.
- `setup_render()` (line 2261) assigns `scene.render.engine` inside `try/except`
  and raises `SystemExit` on failure. For `CYCLES` it sets `samples` and
  `use_denoising = True` and **nothing else** — no `cycles.device`, no
  `denoising_use_gpu`, no `preferences` initialisation. Rendering is therefore
  CPU, as the brief states.

### 0.7 The QA instruments

- `scripts/design_qa.py` -> `00_PROJECT_STATE/design_qa.json`. `--sku`
  deliberately does **not** write the report.
- `scripts/design_coverage.py` -> stdout, or a file with `--out`. Produces
  `truth_agreement`, `print_agreement`, `spec_off_print_pct`, `print_iou`.
- `scripts/calibrate_render.py` -> `00_PROJECT_STATE/render_calibration.json`.

### 0.8 `driver_fingerprint()` — a sequencing constraint the brief does not name

```python
h = hashlib.sha256(resolve_path(_BL["driver_script"]).read_bytes())
h.update(repr([_BL["engine_type"], _BL["samples"], _BL["resolution"]]).encode())
return h.hexdigest()[:16]
```

The fingerprint is **the SHA-256 of the whole driver file**. Any edit to
`render_driver.py` — including a one-line change in `setup_render()` — changes
it, and `load_curve()` then exits with *"was measured against a different driver
or render settings"*. `design_qa` calls `load_curve()` per SKU, so:

> **Every phase that edits the driver invalidates the calibration, and
> `scripts/calibrate_render.py` must be re-run (one extra render per carton)
> before `design_qa` can produce any figure at all.**

This affects Phase 1 (GPU in `setup_render`) and Phase 3 (BEZIER splines). It is
not optional and it is not a fallback — `load_curve()` raises. Budgeted here so
it is not discovered as a failure mid-phase.

### 0.9 Tests that pin what this migration touches

| test | pins |
|---|---|
| `test_render_manifest.TestSchema.test_schema_pins_the_manifest_version` | `const` == `MANIFEST_VERSION` |
| `…test_a_manifest_from_the_previous_contract_is_rejected` | a stale manifest fails validation |
| `…test_every_manifest_on_disk_satisfies_the_current_contract` | no stale file on disk |
| `…test_every_spec_field_is_a_component_a_person_called_print` | spec fields == `print` set, **both ways**, matched on `area_pct` ±0.06 and `bbox_uv` ±0.02 |
| `…test_every_hole_the_spec_cuts_is_one_a_person_called_a_window` | cut rings == `window` set, **both ways**, bbox ±0.01 |
| `…test_a_hole_is_only_ever_asked_about_inside_a_printed_component` | holes enumerated only inside `print` components |
| `…TestAnOutlineIsARegion.test_no_manifest_on_disk_carries_a_ring_that_crosses_itself` | no tangled ring ships |
| `…test_the_manifest_carries_the_type_rows_the_spec_measured` | the fitter did not erase `measure_type_rows`' work |
| `test_reference_templates.py` (400–490) | `part_region` is the exact inverse of the normalisation |
| `test_design_qa.py` | `segment`/`rectified_face` agree; no `.flat.png` read; nulls are null |
| `test_blender_carton.py` | scene invariants from `--dump-scene`; **slow gate** at line 1083 |
| `test_render_qa.TestOCRAgainstAFreshRender` | OCR against fresh pixels; **slow gate** at line 753 |

Both slow gates need `PHARMAGEN_SLOW_TESTS=1`.

---

## Phase 0 — measurements taken during Discovery

Read-only probes of vtracer against the group's real component masks. Recorded
here because they decide how Phase 2 can be built at all.

### M1 — vtracer's output shape, per component mask

Called as `convert_pixels_to_svg(colormode="binary", mode="spline",
filter_speckle=4, corner_threshold=60, length_threshold=4.0, path_precision=8,
hierarchical="stacked")` on the component painted **black on white**.

Over all **75** `print` components in the 28 folders:

| property | measured |
|---|---|
| `<path>` elements returned per component | **1**, on every one of the 75 |
| outer ring | subpath 0 |
| holes | subpaths 1..n of the **same** path |
| paths carrying `transform="translate(...)"` | **75 of 75** |
| paths containing an implicit command repeat (`C` with >6 numbers) | **0 of 75** |

**Polarity matters and is not documented by vtracer.** Painted white-on-black,
`binary` traces the *background*: the first path came back as the whole
1100×1412 frame with the component as an inner subpath, followed by 26 separate
paths, one per black island. Painted black-on-white it returns the single
41-subpath path above. The mask must be **black on white**.

**The `transform` trap is real and universal.** vtracer writes every path's `d`
from the origin and carries the position in `transform="translate(dx,dy)"`,
which appears **after** the `d` attribute. A reader that takes `d` and stops is
off by the component's own offset — the failure the brief records as "IoU near
zero".

**The implicit-repeat trap is real in SVG and did not fire here.** `C` followed
by twelve numbers is two cubics by the SVG grammar, and a parser that reads six
and discards the rest silently drops half the ring. vtracer 0.6.12 as bundled
emits one command per segment, so **0 of 75** components exercised it. It is
still handled and still tested, because the guarantee is about the parser, not
about the version that happens to be installed — but it is recorded as a
*latent* trap, not an observed one.

### M2 — do vtracer's holes correspond to the holes a person classified?

`print_truth.json` enumerates holes with `enclosed_background()` filtered at
`MIN_HOLE_FRAC = 0.0001` of the face. Comparing vtracer's subpaths 1..n, filtered
at the same area floor, against that enumeration:

| | parts |
|---|---|
| vtracer subpath count **equals** the enumerated hole count | **70 of 75** |
| it does not | **5 of 75** |

The five, with the number of `window`-classified holes each carries:

| folder | part | vtracer | enumerated | windows |
|---|---|---|---|---|
| `155_Imovane` | `highlight#0` | 2 | 0 | 0 |
| `221_Inderal` | `brand#0` | 28 | 26 | 0 |
| `340_Xanax_Pfizer` | `brand#0` | 19 | 12 | 0 |
| `59_Cialis` | `highlight#0` | 5 | 4 | 0 |
| `64_Kamagra` | `highlight#5` | 2 | 1 | **1** |

Every disagreement is vtracer returning **more** rings than the pixel
enumeration, never fewer. Without the area floor the two never agree — vtracer's
`filter_speckle=4` removes sub-4-pixel islands that `enclosed_background` counts,
so the raw counts differ on 30 of 75 (e.g. `59_Cialis highlight#0`: 447 against
1289).

### M3 — `part_kind` cannot survive the change of vertex density

`part_kind` returns `block` only when `len(outline) <= 12` **and**
`(outline area − cut hole area) / bbox >= 0.85`. The vertex cap is a proxy for
"a simple shape", and a vectoriser sets vertex count by its own resolution, so
the cap has to go. Three replacements were measured against today's 11 blocks
and 64 fields:

| candidate | result |
|---|---|
| drop the cap, keep the 0.85 fill | **16 parts flip** `field` -> `block` (blocks 11 -> 27) |
| cap on vtracer's *segment* count instead of vertices | **no threshold separates them** — today's blocks run nseg 10–78 at fill 0.606–0.989, while fields with fill ≥ 0.85 run nseg 22–91. `362_Hydrocodone brand#0` is a block at nseg 78 / fill 0.798; `133_Ambien brand#0` is a field at nseg 89 / fill 0.969. The populations overlap on both axes. |
| Douglas-Peucker the vtracer flattening at the existing `SIMPLIFY_TOLERANCE`, then run `part_kind` unchanged | **70 of 75 identical**; 5 flip `field` -> `block`: `135_Ativan brand#0`, `156_Xanax brand#0`, `158_Klonopin brand#0`, `357_Adderall highlight#1`, `365_Tapentadol brand#0` |

The second row is the finding that matters: **`block` and `field` are not
separable by any geometry available after vectorisation.** This is the same shape
of result the project already reached twice — for component admission in Phase B
and for hole class in contract 1.8 — a geometric proxy for a human judgement,
measured failing.

`kind` is not cosmetic. The driver collects every `block` into `blocks`, sorts by
area, and hands the largest to the dosage row as `dosage_block`; the brand's
re-fit is judged against it. Changing which parts are blocks changes where type
lands on four or more cartons.

---

## Phase 1 — GPU, measured and declined

**Outcome: no GPU configuration is enabled.** Every one of them changes the
pixels, and the brief's step 8 rule is unambiguous about what that means — a
configuration that does not reproduce the current image is not switched on in
this phase, and any later decision to switch it on is a measuring event of its
own with a full re-measure behind it.

### 1.1 How the three configurations were measured without touching the driver

`scripts/probe_render_device.py`. The seam it uses is the very defect Phase 1
then closes: `setup_render()` never assigned `scene.cycles.device`, so the device
was whatever the process started with. Blender accepts more than one `--python`,
so a prelude running ahead of the driver sets the device and the driver inherits
it — no driver edit, no fingerprint change, and the control column is produced by
literally the command `blender_renderer` issues today.

Editing `setup_render()` first and measuring afterwards would have compared the
new driver against itself, and would have invalidated `render_calibration.json`
before there was a decision to justify the re-measure.

### 1.2 Byte comparison is the wrong instrument, and the brief's rule has to be read as pixels

Two runs of the **same** driver on the same job produce **bit-identical pixels
and different files**: `64-min` re-rendered against its baseline gives
`max_channel_delta = 0` over 0.0000% of pixels while the PNG bytes differ,
because the encoder stamps metadata into the container. So step 8's
"byte-identical" is read here as "identical in the image", which is the quantity
it was plainly reaching for. Both figures are reported by the probe; no decision
rests on the byte one.

### 1.3 The measurement

RTX 2060 SUPER, Blender 5.1.2, CYCLES, 16 samples, 2048², compared against the
CPU render of the same SKU.

| SKU | config | seconds | speed-up | max channel delta | pixels differing | pixels >2 levels |
|---|---|---|---|---|---|---|
| `1-min` | cpu | 28.0 | — | control | — | — |
| `1-min` | optix | 20.9 | 1.34× | 19 | 0.2253% | — |
| `1-min` | optix+gpudenoise | 5.2 | **5.38×** | 19 | 17.5663% | — |
| `1-min` | cuda | 19.3 | 1.45× | 21 | 0.1755% | — |
| `64-min` | cpu | 32.6 | — | control | — | — |
| `64-min` | optix | 24.4 | 1.34× | 26 | 0.2616% | — |
| `64-min` | optix+gpudenoise | 10.3 | 3.17× | 26 | 16.0077% | — |
| `64-min` | cuda | 24.5 | 1.33× | 23 | 0.2202% | — |
| `357-min` | cpu | 60.0 | — | control | — | — |
| `357-min` | optix | 51.4 | 1.17× | 43 | 0.9082% | — |
| `357-min` | optix+gpudenoise | 36.6 | 1.64× | 43 | 13.9069% | — |
| `357-min` | cuda | 51.0 | 1.18× | 23 | 0.6934% | — |

Full figures in `baseline_2026-08-24/device_probe.json`.

**Two readings worth keeping.**

*The GPU buys much less on sampling than it looks like it should* — 1.17× to
1.45×. That is not a surprise once `R006_STARTUP_COST` is read beside it: the
denoiser is ~14.9s of a 28s render and Blender's own startup another 2.6s, so
accelerating the sampling alone can only reach part of the frame. The large
number, up to 5.4×, is entirely the GPU **denoiser**.

*And the denoiser is where the pixels move.* GPU sampling disagrees with CPU on
0.2–0.9% of pixels — the signature of a different intersection back-end
disagreeing in the last bits, which is expected and arguably neither one being
wrong. GPU denoising disagrees on **14–18%**, which is a different picture, not a
rounding difference. The cheap win and the expensive change are the same setting.

### 1.4 What was entered into the driver instead

The accepted configuration is the current one, so the change is not a new device
— it is making the existing device **stated instead of inherited**, which is what
step 10 asks for and what the probe demonstrated was missing.

- `config.yaml` gains `blender.device`, `blender.device_backend`,
  `blender.denoising_device`, all recording today's measured behaviour, with the
  table above in the comment.
- `render_driver.setup_device()` assigns `scene.cycles.device` and
  `denoising_use_gpu` explicitly, enables **only** the accelerator when on GPU
  (a hybrid render is a third thing with its own pixels), and raises
  `SystemExit` on an unavailable back-end rather than falling back — the rule
  the engine already followed one function down.
- `--dump-scene` gains a `device` block, **read back off the scene** after the
  assignment rather than echoed from the flags. A dump that repeated its own
  input would agree with itself whatever Blender did.
- On CPU the block reports `backend: null` and `enabled_devices: []`. Blender
  leaves GPU devices flagged `use` in its own preferences, so reporting that list
  on a CPU render reads as though the card were doing the work.
- `tests/test_render_driver.TestComputeDeviceIsStatedAndNotInherited` — five
  tests, all passing.

**The edit is pixel-neutral, and that was checked rather than assumed:**
`64-min` re-rendered through the modified driver sits at **max channel delta 0
over 0.000000% of pixels** against `baseline_2026-08-24/renders/64-min.png`.

### 1.5 A scope gap, named rather than worked around

The driver cannot read `config.yaml` — it runs inside Blender's interpreter and
may not import project code (invariant 6) — so the three values can only reach it
as command-line flags, and the launcher that would pass them is
`src/blender_renderer.py`, which is **not in this task's allowed changes**.

Rather than edit an unlisted file, or ship a config key that silently does
nothing, the two sides are welded by a test:
`test_the_drivers_defaults_are_what_config_declares` parses the driver's flag
defaults out of its source and asserts they equal the config. Changing the
config therefore does not change a render — it **fails the suite** until the
driver's default is changed to match and the flag is wired through.

That is a deliberate half-measure and it is worth saying so plainly. This project
already carries one example of a value that is computed and read by nobody
(`smoothness`); a key that stops the suite until the wiring exists is a statement
with teeth, but it is not the same thing as a live setting. Wiring it properly
needs `src/blender_renderer.py` — one line in the `cmd` list — and is left for
the owner to authorise.

### 1.6 `scripts/probe_render_device.py` is kept

Step 11 offers deleting it. It stays, as a reproducible instrument rather than a
one-off: the question it answers ("does this device change the picture?") comes
back every time the hardware, the Blender version or the sample count moves, and
it is the only thing in the tree that can answer it. It renders into
`02_processing/device_probe/` and cleans up after itself unless `--keep`.

### 1.7 Calibration re-run, and the stale row it turned up

Forced by D3: the fingerprint moved from `351a55dbff2d837c` to
`6f66b770a5e700fd` because it is the SHA-256 of the whole driver file.
`scripts/calibrate_render.py` re-run over all 28.

**27 of the 28 rows came back byte-identical**, which is the expected result and
a second, independent confirmation that the driver edit is pixel-neutral: the
chart is a render, and an unchanged chart is an unchanged renderer.

**One row moved, and it was already wrong.** `74-min`:

| | before | after |
|---|---|---|
| `colour_residual_median` | 0.0230 | **0.0149** |
| `colour_residual_worst` | 0.0585 | **0.0406** |
| `ramp` | — | max abs delta **0.0314** |

Both residuals *improved*, which is the giveaway: this is not the driver edit,
it is the row having been stale on disk. `render_calibration.json` was last
written at `68961a6` (2026-08-23) and `74_Viagra`'s face corners changed at
`6d37b89` (2026-08-24) — after it. The chart is built from that SKU's own
carton, so a reshaped carton is a different chart, and the committed row was
measured against a carton that no longer exists.

**`driver_fingerprint()` cannot see this**, and that is a real gap rather than a
detail of this phase. It hashes the driver file plus `engine_type`, `samples`
and `resolution`. It does **not** cover the manifest the chart is built from, so
a corner re-set, a reshape or a re-fit moves the chart and leaves the
fingerprint matching. `load_curve()` then applies a curve measured against
different geometry, in silence, which is precisely the failure mode the
fingerprint exists to prevent — it just guards the wrong half.

Not fixed here: `scripts/calibrate_render.py` is outside this migration's
allowed changes, and widening a staleness guard is a decision with its own
blast radius. Recorded so it is a known gap rather than a surprise, and noted
that the honest repair is for the fingerprint to cover the design spec's own
`verification` block or the manifest hash.

### 1.8 The `design_qa` baseline had to be retaken, and the committed one is historical

`00_PROJECT_STATE/design_qa.json` as committed was written on 2026-08-19.
`CLAUDE.md` already states that five driver commits, a re-measured calibration
curve and a re-fit all landed after it, so it does not describe the tree this
migration starts from and cannot serve as a "before" column.

Retaken with `python scripts/design_qa.py` against the current driver and the
fresh calibration, saved as `baseline_2026-08-24/design_qa.fresh.json`. The
committed 2026-08-19 file is kept beside it as `design_qa.json`; invariant 8
holds because the predecessor was in the baseline directory before anything
overwrote it.

**Exactly one row of 28 moved**, and it is `74-min` again:

| figure | committed | retaken |
|---|---|---|
| `render~spec` agreement | 0.9999 | 0.9996 |
| `render~spec` iou field 1 | 0.994 | 0.998 |
| `field_iou_worst` | 99.4% | **99.8%** |
| `render~ref` agreement | 0.9441 | 0.9451 |
| `render~ref` iou field 0 | 0.943 | 0.929 |
| `render~ref` iou field 1 | **0.312** | **0.806** |

The other 27 are identical to the last digit. So the committed report was less
stale than `CLAUDE.md` implies — the five driver commits after it were pixel-
neutral for these figures — and the single real staleness was the `74_Viagra`
corner change, which reached `design_qa` through the calibration curve. Its
second field goes from matching its own photograph on a third of its pixels to
matching on four fifths.

### 1.9 Phase 1 verdict against the acceptance rule

The step's rule does not apply in its usual form, because nothing about the
image changed: the accepted configuration is the one already running, and the
driver edit is pixel-neutral to `max_channel_delta = 0`. No carton lost anything
because no carton moved. What the phase delivered is a device that is **chosen
and visible** rather than inherited and unlogged, plus two staleness findings
that were not what it went looking for.

---

## Phase 2 — vtracer, measured and REJECTED

**Outcome: rolled back in full.** The step failed its own acceptance rule, and
then the premise underneath it failed too. Both are recorded here because a
negative result that is not written down gets re-attempted.

### 2.1 What was built, and what it did to the numbers

`src/vectorise.py` (the tracer and the SVG parser), wired into `fit()` so that
`trace_outline` + `_simplify_to_a_region` + `trace_holes` were replaced by a
cubic-Bézier fit per component mask, with the hole *enumeration* left on
`enclosed_background()` per decision D1.

Everything the brief asked to be checked before applying came out clean:

| check (step 19) | result |
|---|---|
| keys that moved across all 28 specs | **only `fields` and `verification`**, on the 25 that carry a field |
| `type_rows` | **identical on all 28** — the fitter did not erase `measure_type_rows`' work |
| `face_aspect`, `substrate`, `sku`, `source_image`, `dropped_by_class`, `holes_filled_by_class` | unchanged everywhere |
| the three fieldless cartons | byte-identical |
| holes cut, group | **10 → 10**, and the same ten |
| vertices, group | 5041 → 12381 (**×2.46**, under the brief's ×6 stop) |

And then the figures moved the wrong way. `scripts/design_coverage.py` against
the candidate specs, scored by exactly the instrument that produced the
baseline:

| group figure | baseline | vtracer | |
|---|---|---|---|
| `truth_agreement` | 95.36% | **94.19%** | **−1.17** |
| `print_agreement` | 52.79% | 52.70% | −0.09 |
| `pixel_agreement` | 99.18% | 99.10% | −0.08 |
| `spec_off_print_pct` | 0.76% | **0.91%** | +0.15 (worse) |

**Cartons that lost `truth_agreement`, by name**, as the brief requires:

| SKU | folder | before | after | delta |
|---|---|---|---|---|
| `304-min` | `304_Sonata` | 90.91% | 73.47% | **−17.44** |
| `155-min` | `155_Imovane` | 84.49% | 78.81% | **−5.68** |
| `134-min` | `134_Atarax` | 96.31% | 93.76% | −2.55 |
| `59-min` | `59_Cialis` | 97.73% | 95.94% | −1.79 |
| `62-min` | `62_Cialis_Super_Active` | 99.25% | 97.93% | −1.32 |
| `64-min` | `64_Kamagra` | 98.93% | 97.91% | −1.02 |
| `133-min` | `133_Ambien` | 98.69% | 98.06% | −0.63 |
| `152-min` | `152_Artvigil` | 98.18% | 97.45% | −0.73 |
| `158-min` | `158_Klonopin` | 94.35% | 93.60% | −0.75 |
| `60-min` | `60_Cialis_Professional` | 98.77% | 97.90% | −0.87 |
| `157-min` | `157_Valium` | 99.09% | 98.50% | −0.59 |
| `74-min` | `74_Viagra` | 94.18% | 93.77% | −0.41 |
| `221-min` | `221_Inderal` | 84.23% | 84.03% | −0.20 |
| `135-min` | `135_Ativan` | 92.60% | 92.51% | −0.09 |

The two worst are the two cartons whose printed design is a thin sliver —
Sonata's field is **0.12%** of its face and Imovane's **0.67%** — and a curve
fit rounds a sliver's ends. That is the same effect `_simplify_to_a_region`
already documents from the other direction: *"Coarser is SAFER for a strip,
which is the opposite of the intuition a tolerance usually carries."*

The group figure fell, fourteen cartons lost, and two lost by more than a
hundred times the step's 0.02 threshold. **The rule says the step is rolled
back whole and not tuned per carton, and it was.**

### 2.2 The brief's premise does not reproduce, and this is the important half

The brief states, as an established fact: *"vtracer в режиме `spline`,
запущенный по маске каждой детали, даёт групповой IoU против исходной маски
0.954 против 0.888 у штатного тракта."*

Measured here over all **75** printed components, filling each ring and scoring
against the component's own pixels:

| what is filled | mean IoU |
|---|---|
| **polyline, outer ring only** — what ships today | **0.8855** |
| **polyline, EVERY hole cut** | **0.9536** |
| vtracer, outer ring only | 0.8649 |
| vtracer, EVERY hole cut | 0.9236 |

**0.8855 and 0.9536 are the brief's 0.888 and 0.954 — and both are the POLYLINE.**
The comparison in the audit is not vtracer against the shipped tracer. It is
*every hole cut* against *outer ring only*, on the same tracer, with the
vectoriser incidental to the number attributed to it.

Two consequences, and neither is small.

**The 0.954 is not a figure this project may reach.** It requires cutting every
hole, which is exactly what contract 1.8 forbids and for a reason nothing here
changes: `404_Ritalin`'s 72 holes spell "Ritalin® 10 mg Tabletten" and "50
Tabletten/N2", and cutting them shows board through our field in the shape of
another package's brand and dose. Ten of the group's 238 holes are windows; the
other 228 stay filled by decision, not by oversight.

**Like for like, vtracer is worse on both footings** — 0.8649 against 0.8855 on
the ring, 0.9236 against 0.9536 with holes. It does not lose on thin strips
only; it loses on 75 of 75.

### 2.3 What was ruled out before concluding that

- **A half-pixel offset.** vtracer writes pixel EDGE coordinates (a mask
  spanning columns 40–119 comes back as x 40.000–120.000) while the project
  fills by pixel index, so a systematic half-pixel dilation was the obvious
  suspect. Swept: shift 0.00 → 0.8649, −0.25 → 0.8641, −0.50 → 0.8626, −0.75 →
  0.8582. It is real but it is not the cause, and correcting it makes matters
  slightly worse.
- **The parameters.** Eight settings of `filter_speckle` (0/1/4),
  `corner_threshold` (30/60/90) and `length_threshold` (0.5/1.0/4.0), measured
  as a GROUP figure and never per carton. The whole range is **0.8588 to
  0.8649**, and the defaults this module already used are the best of them.
  Nothing in vtracer's parameter space reaches the polyline.
- **Tuning for the losers.** Not attempted. The brief forbids it and so does
  the evidence: the losses are not concentrated where a parameter would help.

### 2.4 The project had already reached this conclusion, with a different fitter

`SIMPLIFY_TOLERANCE`'s own comment in `scripts/fit_design_spec.py`:

> *NOT a curve problem, which is what this was expected to be. A cubic fit was
> built and measured against the same traces: it needs 3.5x MORE control points
> than the polyline at WORSE and unstable accuracy... These outlines are
> boundaries of RASTER regions — long near-straight runs carrying pixel noise —
> which is Douglas-Peucker's home ground and a cubic's worst case.*

That was written about a hand-built cubic fit. This is an independent
measurement, with a different fitter, reaching the same verdict on the same
data. The reason is stated there and holds: these outlines are boundaries of
raster regions, and a spline fitted to quantisation noise smooths away real
geometry along with the staircase.

### 2.5 What was kept, and what was reverted

**Reverted in full:** `scripts/fit_design_spec.py` and
`tests/test_reference_templates.py` are back to their committed state. The 28
candidate `design_spec.vtracer.json` files are deleted. No spec, manifest or
figure on disk carries anything from this phase.

**Kept:** `src/vectorise.py` and `tests/test_vectorise.py` (16 tests, passing) —
the instrument that produced the measurement, unwired from the pipeline. Both
SVG traps the brief names are implemented and pinned by tests, and the synthetic
disc-with-a-square-hole reproduces the brief's own reference run exactly: **IoU
0.9908 at 33 control points**, against a stated 0.9909 and 33.

`requirements.txt` declares `vtracer` for that module and nothing else.
`scipy`, `scikit-image`, `shapely` and `opencv-python` are installed and remain
undeclared, because after this rollback nothing in the tree imports them.

### 2.6 Phases 3, 4 and 5 are not started

Phase 3 (contract 1.9, Bézier curves in the manifest) exists to carry the output
of Phase 2 into the scene. With Phase 2 rejected there is no curve to carry:
bumping the contract to transport a flattening of a fit that scores worse than
the polyline it replaced would be a contract change with a negative payload.

Phase 4 (perceptual colour) is independent of the tracer and is still open. It
is a hypothesis with its own acceptance rule — the count of `blend` components
before and after — and nothing measured here bears on it.

Phase 5 closes the work and cannot run before them.

---

## Phase 4 — Discovery

Read-only. No code changed.

### 4.0.1 How the partition is actually built

`measure_reference_face.segment()`:

```
rectified_face(folder)                    # perspective warp of one JPEG
  -> raw = pixels / 255                   # sRGB-encoded, 0..1
  -> a = _flatten_illumination(raw, 6.0)  # divide out the lighting gradient
  -> labels = _kmeans(a.reshape(-1,3), 4) # in the corrected RGB
  -> per cluster: mean (from `a`), colour (MEDIAN of RAW px), sat/val from _hsv(mean)
  -> merge any two clusters within SAME_SURFACE_MAX = 0.08 of each other
     in RGB, on `colour` -- NOT in the clustering space
  -> roles: darkest -> `type` if val < 0.35 AND share < 15%
            largest remaining -> `substrate`
            most saturated of the rest -> `brand`
            brightest of the rest -> `highlight`
            anything still unnamed -> `secondary_N`
```

Two things that bound how far each change can reach:

- **The merge is in RGB on the raw median, not in the clustering space.** So
  changing `_kmeans`' space does not automatically change the merge, and
  `SAME_SURFACE_MAX` keeps meaning what it meant.
- **Role naming reads `_hsv(mean)` on the corrected RGB.** So a change to
  `_kmeans` only reassigns *labels*; a change to `_flatten_illumination` moves
  `mean` and can therefore reassign *roles* as well. Event A has the wider blast
  radius of the two, which is the opposite of what the ordering suggests.

### 4.0.2 `_flatten_illumination` has five callers, not two

`segment()` calls it once at `radius_div = 6.0`. `scripts/design_qa.py` calls it
at **five** sites with three different radii — `FLATTEN_RADIUS_DIV`, `2.0` and
`2.5` — including inside `_substrate_residual()`'s plane-vs-blur choice. So
event A moves D-6's illumination model selection as well as D-1's partition, and
both must be measured inside event A or the movement will surface in event B and
be attributed to the wrong cause.

### 4.0.3 The replacement for `rgb.max(-1)` is already this project's convention

`max(-1)` is V of HSV. The project already has one perceived-luminance formula
and uses it in four places — `render_driver._reverse_ink` (line 414),
`design_qa.LUMA` (line 218), `src/passport_generator.py` (line 101) and
`tests/test_blender_carton._perceived`:

```
luma = 0.2126 R + 0.7152 G + 0.0722 B     # Rec.709, on sRGB-encoded values
```

Adopting it here makes the estimate perceptual **and** removes a second
convention rather than adding one. Note it is deliberately taken on the encoded
values, not linearised: that is what the other four callers do, and
`_reverse_ink`'s docstring records why the distinction bit this project once
already (sRGB 0.5 is linear 0.21, and judging in linear called almost everything
dark).

### 4.0.4 The class census, and a problem with the acceptance criterion

Measured across all 28 `print_truth.json`, excluding entries marked `vanished`
(4 components and 3 holes are). Saved as
`baseline_2026-08-24/phase4_class_census.json`.

| components | n | | holes | n |
|---|---|---|---|---|
| `type` | 484 | | `lettering` | 199 |
| `print` | **75** | | `object` | 12 |
| `object` | 40 | | `blend` | 10 |
| `mark` | 27 | | `window` | **10** |
| `unrepresentable` | 26 | | `mark` | 8 |
| **`blend`** | **9** | | | |
| total | **661** | | total | **239** |

(`CLAUDE.md` says 664 components and 238 holes; the difference is the `vanished`
entries and is not a discrepancy in the data.)

**The acceptance criterion for event B is thinner than the brief implies.** Only
**9** components in the whole group are classified `blend`, spread one apiece
across eight folders (`308_Lexotanil` has two):

```
149_Modalert 1 · 308_Lexotanil 2 · 340_Xanax_Pfizer 1 · 344_Modafinil_Generic 1
357_Adderall 1 · 362_Hydrocodone 1 · 365_Tapentadol 1 · 64_Kamagra 1
```

So the maximum possible improvement is 9 out of 661, and a movement of one
component is within the noise of a partition change. This is recorded **before**
the measurement rather than after it, so that a result of "8 instead of 9" is
read as what it is — a single component moving — and not as a win. The criterion
is kept because the brief names it, and it is reported alongside
`truth_agreement`, which has 25 cartons behind it.

### 4.0.5 Tests that read the partition, the palette or the truth file

`test_blender_carton.py`, `test_calibrate_render.py`, `test_design_qa.py`,
`test_reference_templates.py`, `test_render_manifest.py`.
`tests/test_vectorise.py` matches the grep only because it mentions `substrate`
in a comment.

### 4.0.6 Versions

Unchanged from §0.1. `scikit-image` **0.25.2** is installed and remains
undeclared; whether it is needed is decided by measurement in event B.

---

## Phase 4 — perceptual colour, measured and REJECTED (both events)

**Outcome: both events rolled back. Neither reached the point of producing a
figure**, because both fail the precondition the figures depend on. That is the
finding, and it is larger than the phase that went looking for it.

### 4.1 The precondition, and why it is the whole phase

`print_truth.json` keys a hand-made class to `role#i`. Both halves of that key
are **outputs of the partition**: `role` is the name `segment()` gave a cluster,
`i` is the index a component takes after `components()` filters by area and sorts
by descending area. Move the partition and the keys address different surfaces.

`fit()` stops on a key it has never seen. It cannot stop on a key that still
exists and now means something else, and `label_print --verify` cannot either —
it asks whether every component *has* a class, not whether it is the *right*
one. So the check had to be built: `scripts/probe_partition_shift.py`
enumerates the same faces twice, once with the change and once with it swapped
back, and reports gained keys, lost keys, and roles whose colour or area share
moved materially.

### 4.2 Event A — the lightness estimator

`_flatten_illumination` estimated lightness as `rgb.max(-1)`, which is V of HSV:
it calls `#0000FF` and `#FFFFFF` equally bright and ignores two thirds of the
pixel. The image is then *divided* by a heavy blur of that quantity, so the
estimator decides where the code thinks a lighting gradient is.

Replaced with the formula this project already uses in four other places —
Rec.709 luma `0.2126 R + 0.7152 G + 0.0722 B` on sRGB-encoded values. This is a
defect fix, not a preference: no colour model calls `max` a lightness.

**The partition moved on 21 of 28 folders.** Full detail in
`baseline_2026-08-24/phase4A_partition_shift.json`. The worst:

| folder | matched | gained | lost | worst area drift | roles that changed surface |
|---|---|---|---|---|---|
| `362_Hydrocodone` | 8 | **55** | **51** | 6.4 pts | brand, highlight, substrate, secondary_1, type |
| `357_Adderall` | 22 | 9 | 26 | **28.9 pts** | brand, highlight, substrate, secondary_1 |
| `308_Lexotanil` | 4 | 24 | 22 | 1.3 pts | brand, highlight, substrate, secondary_1, type |
| `64_Kamagra` | 3 | 0 | 23 | 8.1 pts | **`highlight` vanished entirely** |
| `157_Valium` | **1** | 18 | 19 | 0.7 pts | brand, type vanished |
| `340_Xanax_Pfizer` | 18 | 2 | 8 | **18.0 pts** | highlight, substrate, secondary_1 |
| `346_Modvigil` | 46 | 2 | 1 | 11.1 pts | highlight, substrate |

Seven folders were stable. Twenty-one were not.

### 4.3 Event B — the clustering space

`_kmeans` clustered in the illumination-corrected sRGB values. Euclidean
distance there is not a distance a viewer agrees with, so the partition it finds
is a partition of the encoding rather than of the appearance. Replaced with
**OKLab**, written out in eleven lines of numpy rather than taken from
scikit-image — the transform is exact, and this module already writes out
`trace_outline`, `components` and `enclosed_background` for the same reason.
Verified against the standard: white → `L=1, a=0, b=0`, black → `0`, mid grey →
`L=0.598`.

Measured against the **unchanged** tree, not on top of event A, because event A
was rejected and stacking a measurement on a rejected change attributes nothing.

**The partition moved on 27 of 28 folders.** Only `134_Atarax` survived. Detail
in `baseline_2026-08-24/phase4B_partition_shift.json`. The worst:

| folder | matched | gained | lost | worst area drift | roles that changed surface |
|---|---|---|---|---|---|
| `362_Hydrocodone` | 4 | **48** | **55** | 13.3 pts | five roles, `type` appeared |
| `64_Kamagra` | 4 | 25 | 22 | 7.0 pts | `highlight` vanished, `type` appeared |
| `357_Adderall` | 22 | 3 | 26 | **24.5 pts** | four roles |
| `59_Cialis` | 2 | 7 | 22 | 7.3 pts | `highlight` and `secondary_1` vanished |
| `230_Slimex` | 4 | 9 | 8 | **17.6 pts** | brand, highlight |
| `340_Xanax_Pfizer` | 15 | 0 | 11 | 16.5 pts | three roles |
| `158_Klonopin` | 2 | 16 | 17 | 0.03 pts | brand, highlight |

### 4.4 What this means, stated plainly

**The segmentation is frozen by the labelling, and the labelling is the more
expensive artefact.** 661 components and 239 holes were classified by hand
against one particular partition. Any change to how that partition is computed —
including fixing an estimator that is provably the wrong quantity — invalidates
the classification on most of the group. There is no version of either change
that avoids this: `_flatten_illumination` divides every pixel by a function of
the estimator, and `_kmeans` groups pixels by distance in the space. Both touch
every pixel by construction.

So the cost of improving the segmentation is not a code change. It is
re-classifying 28 folders by hand, and doing it in the knowledge that
`label_print --init` **merges old classes onto new components**, which is exactly
how stale labels survived a corner change once before. A re-label has to be a
deliberate human pass, not a merge.

**The acceptance criterion the brief named could never have decided this.** Only
**9** of 661 components carry the class `blend`, one apiece across eight folders.
Even a perfect outcome moves that figure by at most 9, and a movement of one is
inside the noise of any partition change. Recorded in §4.0.4 before the
measurement, so it is a prediction rather than an excuse. In the event the
criterion was never reached: the precondition failed first, on both events.

**`64_Kamagra`'s "false diagonal" was not examined**, because examining it needs
the new partition to be labelled, and it is not. The `--aid` render of an
unlabelled partition shows classes that no longer describe it.

### 4.5 What was kept

- `scripts/probe_partition_shift.py` — kept as a reproducible instrument. It is
  the only thing in the tree that can answer "does this change invalidate the
  labelling?", and that question comes back for every future change to
  `segment()`. With the seams reverted it now says so by name instead of
  throwing.
- `baseline_2026-08-24/phase4_class_census.json`,
  `phase4A_partition_shift.json`, `phase4B_partition_shift.json` — the evidence.
- `baseline_2026-08-24/print_truth/` — all 28 truth files as they stood.

Reverted to committed state: `scripts/measure_reference_face.py`. No spec, no
manifest, no `print_truth.json` and no figure carries anything from Phase 4.
`design_coverage` re-run afterwards returns **99.18% / 52.79% / 95.36% / 0.76%**,
the baseline to the last digit.

### 4.6 The `src/vectorise.py` decision (steps 4–5)

**Kept, unwired, and now guarded.** It is the only implementation in the tree of
the two SVG traps that cost three earlier runs of the Phase 2 experiment, and
deleting it means the next attempt derives them again. The cost is one declared
dependency.

Two new tests in `tests/test_vectorise.py` make the wiring fail rather than
happen quietly: a static scan of `src/`, `scripts/`, `05_assets/blender/` and
`tests/` for any import of it outside its own test, and a subprocess check that
importing the design pipeline does not pull it into `sys.modules`. A module
sitting in `src/` beside the real stages, one line away from being used, is a
module that gets used.

---

## State of the tree at the end of this run

### Verification, run after both rollbacks

```
python -m unittest discover -s tests
Ran 377 tests in 587.717s          OK (skipped=5)

PHARMAGEN_SLOW_TESTS=1 python -m unittest tests.test_blender_carton
Ran 85 tests in 390.951s           OK

PHARMAGEN_SLOW_TESTS=1 python -m unittest tests.test_render_qa.TestOCRAgainstAFreshRender
Ran 3 tests in 955.192s            OK
```

377 against the 354 this started with: +18 `tests/test_vectorise.py` (16 for the
tracer, 2 guarding it against being wired in), +5
`tests/test_render_driver.TestComputeDeviceIsStatedAndNotInherited`.

The two slow gates were run after the **only** change that reaches the renderer —
the Phase 1 driver edit. Nothing has touched `05_assets/blender/render_driver.py`
since, and Phase 2 and Phase 4 are reverted to their committed state, so those
results still describe this tree. **The OCR fixtures needed no rebuild**, which
is a third independent confirmation the driver edit did not move a pixel, after
`max_channel_delta = 0` on `64-min` and 27 of 28 calibration rows returning
byte-identical.

**The OCR fixtures needed no rebuild.** That gate re-renders the whole 28-SKU
sample and re-reads it, so passing against the committed fixtures is a third
independent confirmation that the Phase 1 driver edit did not move a pixel —
after `max_channel_delta = 0` on `64-min` and 27 of 28 calibration rows coming
back byte-identical.

`scripts/design_coverage.py` re-run after the rollback returns **99.18% /
52.79% / 95.36% / 0.76%** — the baseline to the last digit, so the revert is
complete rather than approximately complete.

### Files this run changed

| file | why | allowed by |
|---|---|---|
| `config.yaml` | `blender.device`, `device_backend`, `denoising_device` | blender device keys |
| `05_assets/blender/render_driver.py` | `setup_device()`, one call in `setup_render()`, `_device_report()` in `--dump-scene`, three flag defaults | setup_render, --dump-scene |
| `tests/test_render_driver.py` | 5 device tests | tests |
| `tests/test_vectorise.py` | 18 tests, new file | tests |
| `src/vectorise.py` | new file, unwired | named in the brief |
| `scripts/probe_render_device.py` | new file | mandated by Phase 1 step 6 |
| `scripts/probe_partition_shift.py` | new file | mandated by Phase 4 step 8 |
| `requirements.txt` | declares `vtracer` only | yes |
| `CLAUDE.md`, `CHANGELOG.md` | the two findings and one line per event | yes |
| `00_PROJECT_STATE/TOOLING_MIGRATION.md` | this document | yes |
| `00_PROJECT_STATE/baseline_2026-08-24/` | the baseline and the evidence | yes |
| `00_PROJECT_STATE/design_qa.json` | regenerated by its script; predecessor in the baseline | figures, script-only |
| `00_PROJECT_STATE/render_calibration.json` | regenerated by its script; predecessor in the baseline | figures, script-only |

`audit.md` shows as modified and was **already modified before this work began**
— it is untouched here.

Reverted to their committed state: `scripts/fit_design_spec.py`,
`scripts/measure_reference_face.py`, `tests/test_reference_templates.py`. No
`design_spec.json`, no `metadata.json`, no `print_truth.json`, no manifest and no
render on disk carries anything from Phase 2 or Phase 4.

**One file outside the project root was written**, and it is not project work:
the assistant's own memory note under `~/.claude/projects/…/memory/`, which had
recorded the vtracer premise as established and now records that it does not
reproduce. Named here rather than left implicit.

### Invariants, checked one by one

1. **Admission is the person's.** No geometric criterion restored; the fitter is
   at its committed state, and the rejected branch never touched `label_of`.
2. **Only `window` holes cut.** Held throughout — the candidate specs cut 10
   holes, the same ten, and the enumeration stayed on `enclosed_background()`.
3. **`front_face_px` check intact.** Untouched.
4. **`label_print --init` was never run.** No merge of old classes onto new
   components took place, which is the mechanism that once carried stale labels
   through a corner change.
5. **`print_truth.json` unchanged in all 28 folders**, and snapshotted into the
   baseline before anything ran. Confirmed by `git status`.
6. **`sku_id` keeps its extension, `product_code` is not `sku_id`, LOT/EXP
   empty.** Untouched.
7. **Determinism.** vtracer takes no seed and its parameters are module
   constants, pinned by a test. The OKLab transform is a fixed matrix and a cube
   root, verified against the standard (white → L=1, black → 0, mid grey →
   0.598) and reverted regardless. `k` stayed 4 throughout; quantile seeding was
   never replaced by random points.
8. **The driver imports no project module and no new library.** `setup_device`
   and `_device_report` use `bpy` only.
9. **No required manifest field changed**, so no version bump was owed. The
   contract stays at 1.8.
10. **No figure overwritten without its predecessor in the baseline.**
    `design_qa.json` and `render_calibration.json` were both snapshotted first.
11. **`type_rows` survives the fitter.** Verified across all 28 in the Phase 2
    dry run, before anything was written — and the fitter is now back at its
    committed state regardless.
12. **`baseline_2026-08-24/` was added to only between phases**, never edited:
    the Phase 4 evidence files were new names, and nothing already in it changed.
13. **Nothing imports `src/vectorise.py`.** Enforced by two tests rather than
    asserted here.
14. **The manifest polyline is not an independent geometry.** Not reached;
    contract 1.9 was not started.

---

## Decisions taken on the Discovery findings

Three, raised rather than guessed, per the brief's closing instruction, and
settled by the owner on 2026-08-24 before any code changed.

### D1 — the hole ENUMERATION stays with the person (steps 15–16)

**Decided: `enclosed_background()` remains the only enumerator of holes.**
vtracer supplies geometry and nothing else: it vectorises the component's outer
ring, and then — separately, once per hole — the mask of each hole the label
already classified `window`.

The reasoning is M2. Step 16 as written asks for a geometric matcher between two
enumerations, and a matcher is a new proxy for an identity the project already
has for free: a hole's identity is `role#i/hole#j`, assigned by the enumerator
the person looked at. Keeping that enumerator means

- correspondence is exact **by construction**; there is no matcher to tune and
  none to get wrong,
- invariant 2 (only `window` is cut) holds because `window` is a class only the
  truth file can assign, and nothing else is ever handed to the vectoriser,
- the five parts of M2 do not stop the migration, because vtracer's extra rings
  are never enumerated in the first place,
- `print_truth.json`'s `hole_min_frac` guard keeps working unchanged — it exists
  precisely to stop the two sides enumerating differently.

What is given up, stated rather than glossed: vtracer's own view of where a hole
is never reaches the spec, so if its spline fit disagrees with the pixel
enumeration about a `window`'s **shape**, the spec takes vtracer's shape of that
hole's own mask, not vtracer's subpath from the component trace. Those are the
same region traced twice; they are not guaranteed identical, and the difference
is unmeasured.

### D2 — `part_kind` keeps its instrument, on a Douglas-Peucker'd flattening (step 17)

**Decided: run the existing `part_kind` unchanged over
`simplify(flatten(vtracer ring), SIMPLIFY_TOLERANCE * w)`.**

M3 shows there is no density-independent geometric criterion to move to: `block`
and `field` overlap on every axis available after vectorisation. Douglas-Peucker
at the project's existing tolerance fixes the input's vertex density by a
*tolerance* rather than by the vectoriser's resolution, which is the property
step 17 actually asks for, and it reproduces 70 of 75 of today's answers.

**Five parts flip `field` -> `block` and are accepted as part of the Phase 2
delta**, listed here so the change is attributable rather than discovered later:

| folder | part |
|---|---|
| `135_Ativan` | `brand#0` |
| `156_Xanax` | `brand#0` |
| `158_Klonopin` | `brand#0` |
| `357_Adderall` | `highlight#1` |
| `365_Tapentadol` | `brand#0` |

These are cartons whose boundary vtracer smooths enough that the shape reads as
the simple filled region it is; the old answer was partly an artefact of the
pixel staircase the Moore trace leaves. They change which part the driver offers
as `dosage_block`, so any movement in those five cartons' type placement in the
Phase 2 report belongs to this decision and not to the vectoriser.

### D2a — `requirements.txt` declares intent now, and is trimmed to fact at Phase 5

Phase 0 step 4 says to declare the packages "actually used later", which at
Phase 0 is a statement about intent. Four are declared — `vtracer`, `shapely`,
`scikit-image`, `scipy` — at the versions §0.1 measured. `opencv-python` is
**not** declared: nothing in this migration has a use for it, and the brief says
not to declare a dependency that is not called.

**Obligation carried to Phase 5:** grep the tree for an actual import of each of
the four and delete any that never earned its line. The Definition of Done asks
for exactly the packages the code calls, and a declaration made in advance is
only honest once it has been checked against what shipped.

### D3 — calibration must be re-run after every driver edit (§0.8)

Not a choice, recorded so it is not met as a failure: Phase 1 and Phase 3 each
change `render_driver.py`, which changes `driver_fingerprint()`, which makes
`load_curve()` exit. `scripts/calibrate_render.py` is therefore re-run as an
explicit step in both phases, before any `design_qa` figure is taken. This holds
even for a change the brief classes as "not a measuring event", such as a GPU
setting that renders byte-identically — the fingerprint is over the file, not
over the pixels.

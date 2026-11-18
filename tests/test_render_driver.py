"""Tests for engine selection in assets/blender/render_driver.py.

The driver imports bpy at module scope, so it only runs inside Blender's own
interpreter. These tests therefore drive the real executable as a subprocess,
the same way src/blender_renderer.py does, and are skipped when the configured
blender.executable is not installed so the suite still passes without Blender.

Renders are 64x64 at 1 sample: what is under test is which engine Blender ends
up using, not image quality.

Regression under test: the driver used to decide availability by introspecting
bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items. `engine` is a
DYNAMIC enum, so that returns only a static placeholder -- ('BLENDER_EEVEE',)
on 5.1.2 -- and never CYCLES, even where Cycles is enabled and working. Every
render silently fell through to EEVEE with `samples` never applied.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.render_manifest import build_manifest
from src.utils import load_config, resolve_path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PASSPORT = PROJECT_ROOT / "04_passports" / "passports_json" / "1-min.json"

_CFG = load_config()
BLENDER_EXE = Path(_CFG["blender"]["executable"])
DRIVER = resolve_path(_CFG["blender"]["driver_script"])
CONFIGURED_ENGINE = _CFG["blender"]["engine_type"]

_HAVE_BLENDER = BLENDER_EXE.exists()
_SKIP_REASON = f"Blender not installed at {BLENDER_EXE}"


def _manifest(stem: str = "1-min") -> dict:
    path = PROJECT_ROOT / "04_passports" / "passports_json" / f"{stem}.json"
    return build_manifest(json.loads(path.read_text(encoding="utf-8")))


def _run_driver(engine_type: str, workdir: Path, job: dict = None, res: str = "64"):
    """Invoke the driver exactly as blender_renderer.py does, but tiny."""
    job_path = workdir / "job.json"
    out_path = workdir / "out.png"
    job_path.write_text(
        json.dumps(_manifest() if job is None else job),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            str(BLENDER_EXE), "--background", "--factory-startup",
            "--python", str(DRIVER), "--",
            "--job", str(job_path),
            "--out", str(out_path),
            "--engine-type", engine_type,
            "--samples", "1",
            "--res-x", res,
            "--res-y", res,
        ],
        capture_output=True, text=True, timeout=300,
    )
    return proc, out_path


_DUMP_SCENE_CACHE = {}


def _dump_scene(job: dict = None):
    """Run the driver in --dump-scene mode and return the measured geometry.

    Modelled on the subprocess.run block in test_blender_carton.py:115-130.
    Cached per distinct job so repeated calls in one test class (or across
    the four tests in TestPrintedFaceCorners, which all want the same scene)
    do not each pay a fresh Blender launch.
    """
    key = json.dumps(job, sort_keys=True) if job is not None else "__default__"
    if key in _DUMP_SCENE_CACHE:
        return _DUMP_SCENE_CACHE[key]
    with tempfile.TemporaryDirectory() as td:
        job_path = Path(td) / "job.json"
        dump_path = Path(td) / "scene.json"
        job_path.write_text(
            json.dumps(_manifest() if job is None else job),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [str(BLENDER_EXE), "--background", "--factory-startup",
             "--python", str(DRIVER), "--",
             "--job", str(job_path), "--dump-scene", str(dump_path)],
            capture_output=True, text=True, timeout=300,
        )
        if not dump_path.exists():
            raise AssertionError(
                f"driver produced no scene dump (exit {proc.returncode})\n"
                f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
            )
        scene = json.loads(dump_path.read_text(encoding="utf-8"))
    _DUMP_SCENE_CACHE[key] = scene
    return scene


@unittest.skipUnless(_HAVE_BLENDER, _SKIP_REASON)
class TestEngineIsHonoured(unittest.TestCase):
    """The engine that was asked for is the engine that renders."""

    def test_cycles_is_used_when_requested(self):
        with tempfile.TemporaryDirectory() as td:
            proc, out_path = _run_driver("CYCLES", Path(td))
            self.assertEqual(proc.returncode, 0,
                             f"driver failed:\n{proc.stdout}\n{proc.stderr}")
            self.assertTrue(out_path.exists(), "no PNG written")
            self.assertIn("[render_driver] engine CYCLES", proc.stdout,
                          "driver did not report rendering on CYCLES; it "
                          f"substituted another engine.\n{proc.stdout}")

    def test_eevee_is_used_when_requested(self):
        """The substitution guard must not push everything to Cycles either."""
        with tempfile.TemporaryDirectory() as td:
            proc, out_path = _run_driver("BLENDER_EEVEE", Path(td))
            self.assertEqual(proc.returncode, 0,
                             f"driver failed:\n{proc.stdout}\n{proc.stderr}")
            self.assertTrue(out_path.exists(), "no PNG written")
            self.assertIn("[render_driver] engine BLENDER_EEVEE", proc.stdout)

    def test_configured_engine_type_is_available_in_this_blender(self):
        """config.yaml must name an engine this install can actually provide.

        This is the check that was missing: blender.engine_type said CYCLES
        while every render silently came out of EEVEE.
        """
        with tempfile.TemporaryDirectory() as td:
            proc, out_path = _run_driver(CONFIGURED_ENGINE, Path(td))
            self.assertEqual(
                proc.returncode, 0,
                f"config.yaml requests blender.engine_type={CONFIGURED_ENGINE!r}, "
                f"which this Blender rejected:\n{proc.stderr}")
            self.assertIn(f"[render_driver] engine {CONFIGURED_ENGINE}", proc.stdout)


@unittest.skipUnless(_HAVE_BLENDER, _SKIP_REASON)
class TestUnavailableEngineIsFatal(unittest.TestCase):
    """An engine this Blender cannot provide stops the run."""

    def test_unknown_engine_exits_nonzero_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            proc, out_path = _run_driver("NOT_A_REAL_ENGINE", Path(td))
            self.assertNotEqual(proc.returncode, 0,
                                "unavailable engine was silently substituted")
            self.assertFalse(out_path.exists(),
                             "an off-spec PNG was produced anyway")

    def test_failure_names_the_requested_engine_and_refuses_substitution(self):
        with tempfile.TemporaryDirectory() as td:
            proc, _ = _run_driver("NOT_A_REAL_ENGINE", Path(td))
            combined = proc.stdout + proc.stderr
            self.assertIn("NOT_A_REAL_ENGINE", combined,
                          "error does not say which engine was unavailable")
            self.assertNotIn("falling back", combined.lower(),
                             "driver still advertises a fallback")


@unittest.skipUnless(_HAVE_BLENDER, _SKIP_REASON)
class TestLabelContent(unittest.TestCase):
    """The manifest's label_content must reach the rendered face."""

    def test_every_label_row_is_placed(self):
        """Five, not the three this test first expected: the label gained an
        active-ingredient row when the manifest contract went to 1.1, and the
        count is of LINES, so 1-min's wrapping brand contributes two."""
        with tempfile.TemporaryDirectory() as td:
            proc, out_path = _run_driver("CYCLES", Path(td))
            self.assertEqual(proc.returncode, 0,
                             f"driver failed:\n{proc.stdout}\n{proc.stderr}")
            self.assertTrue(out_path.exists())
            self.assertIn("[render_driver] label: 5 text object(s)", proc.stdout,
                          f"brand(2) + ingredient + dosage + count expected"
                          f"\n{proc.stdout}")

    def test_long_brand_wraps_to_a_second_line(self):
        """412-min is the catalogue's worst fit: a 30-character brand on the
        narrowest face. It must wrap rather than overflow or be truncated.

        Compared against a SHORT brand rather than asserted as a bare number:
        with four rows on the face the total is the same whether the name wrapped
        or not, so a lone count would have stopped testing wrapping at all.
        """
        short = _manifest()
        short["label_content"]["brand_name_display"] = "Aleve"
        with tempfile.TemporaryDirectory() as td:
            long_dir, short_dir = Path(td) / "l", Path(td) / "s"
            long_dir.mkdir()
            short_dir.mkdir()
            proc, _ = _run_driver("CYCLES", long_dir, job=_manifest("412-min"))
            proc_short, _ = _run_driver("CYCLES", short_dir, job=short)
            self.assertEqual(proc.returncode, 0,
                             f"driver failed:\n{proc.stdout}\n{proc.stderr}")
            self.assertIn("[render_driver] label: 5 text object(s)", proc.stdout,
                          f"two brand lines + ingredient + dosage + count expected"
                          f"\n{proc.stdout}")
            self.assertIn("[render_driver] label: 4 text object(s)",
                          proc_short.stdout,
                          f"a short brand must NOT wrap\n{proc_short.stdout}")

    def test_label_text_actually_reaches_the_image(self):
        """Same carton, same palette, different brand string -> different pixels.
        Guards against the text being built but never rendered."""
        from PIL import Image, ImageChops

        job_a = _manifest()
        job_b = _manifest()
        job_b["label_content"]["brand_name_display"] = "ZZZZ WWWW"
        with tempfile.TemporaryDirectory() as td:
            a_dir, b_dir = Path(td) / "a", Path(td) / "b"
            a_dir.mkdir(), b_dir.mkdir()
            proc_a, out_a = _run_driver("CYCLES", a_dir, job=job_a, res="200")
            proc_b, out_b = _run_driver("CYCLES", b_dir, job=job_b, res="200")
            self.assertEqual(proc_a.returncode, 0, proc_a.stderr)
            self.assertEqual(proc_b.returncode, 0, proc_b.stderr)

            img_a = Image.open(out_a).convert("RGB")
            img_b = Image.open(out_b).convert("RGB")
            diff = ImageChops.difference(img_a, img_b).convert("L")
            hist = diff.histogram()
            changed = sum(hist[level] for level in range(3, len(hist)))
            self.assertGreater(
                changed, 20,
                "changing the brand string barely moved the image; the label is "
                "probably not being rendered")


@unittest.skipUnless(_HAVE_BLENDER, _SKIP_REASON)
class TestLabelContractIsEnforced(unittest.TestCase):
    """label_content is `required` in the schema; a job without it bypassed the
    contract, and an unlabelled packshot is a silent content failure."""

    def test_missing_label_content_exits_nonzero_and_writes_nothing(self):
        job = _manifest()
        job.pop("label_content")
        with tempfile.TemporaryDirectory() as td:
            proc, out_path = _run_driver("CYCLES", Path(td), job=job)
            self.assertNotEqual(proc.returncode, 0,
                                "an unlabelled carton was rendered anyway")
            self.assertFalse(out_path.exists())
            self.assertIn("label_content", proc.stdout + proc.stderr)


@unittest.skipUnless(_HAVE_BLENDER, _SKIP_REASON)
class TestPrintedFaceCorners(unittest.TestCase):
    """The renderer owns the camera, so it -- not a downstream consumer --
    reports where each printed face landed in the frame.

    Recovering these corners from the image was tried and failed: a colour mask
    keyed on palette.accent cannot separate the accent stripe from the brand
    badge when primary and accent are close, and an SVD principal axis is
    sign-ambiguous (measured tilts came out at 138-178 degrees).
    """

    def test_front_face_corners_are_a_sane_quad_inside_the_frame(self):
        scene = _dump_scene()          # runs --dump-scene, see _dump_scene() above
        corners = scene.get("front_face_px")
        self.assertIsNotNone(corners, "driver did not report front_face_px")
        self.assertEqual(len(corners), 4)
        res_x, res_y = scene["resolution"]
        for x, y in corners:
            self.assertTrue(0 <= x <= res_x, f"corner x={x} outside 0..{res_x}")
            self.assertTrue(0 <= y <= res_y, f"corner y={y} outside 0..{res_y}")

    def _assert_shared_edge_agrees(self, scene):
        """front_face_px and side_panel_px describe adjoining faces of the same
        box, so they must share a vertical edge: front TL == side TR, and
        front BL == side BR (the carton's near-left corner, seen once from
        each face). This is derived from the geometry, not from whatever order
        _order_quad happens to emit, so unlike a same-side inequality it
        cannot be satisfied by an internally-consistent but wrong ordering --
        a self-intersecting (bowtie) quad breaks it even though its own
        left-of/above inequalities all still hold.
        """
        tl, tr, br, bl = scene["front_face_px"]
        side_tl, side_tr, side_br, side_bl = scene["side_panel_px"]
        for a, b, label in ((tl, side_tr, "front TL vs side TR"),
                            (bl, side_br, "front BL vs side BR")):
            self.assertAlmostEqual(a[0], b[0], places=2, msg=f"{label} (x)")
            self.assertAlmostEqual(a[1], b[1], places=2, msg=f"{label} (y)")

        # The shared edge anchors only the side panel's TR and BR. Its other
        # two corners are the far vertical edge, which the front face never
        # touches, so nothing above constrains them and a defect that moved
        # only TL/BL would pass. Perspective supplies the missing anchor: the
        # far edge is further from the camera than the near one, so it must
        # project both further LEFT (the -X face turns leftward under
        # +ROTATION_DEG) and SHORTER (foreshortening). Measured on the T1
        # fixture, 630.4 px against 679.5.
        near_h = abs(side_tr[1] - side_br[1])
        far_h = abs(side_tl[1] - side_bl[1])
        self.assertLess(side_tl[0], side_tr[0],
                        "side TL is not left of side TR; the far edge of the "
                        "-X panel must recede leftward")
        self.assertLess(side_bl[0], side_br[0],
                        "side BL is not left of side BR")
        self.assertLess(far_h, near_h,
                        f"the side panel's far vertical edge ({far_h:.1f} px) "
                        f"is not shorter than its near one ({near_h:.1f} px); "
                        f"under perspective the further edge foreshortens, so "
                        f"TL/BL are mis-ordered or mis-projected")
        # Weak in the same way as the front face's own above/below pair: it
        # follows from _order_quad's local-Z sort, so a sorting bug satisfies
        # it. Kept because it is NOT vacuous against a projection bug -- drop
        # the y-flip in _face_corners_px and TL lands below BL. Measured: the
        # checks above catch a near/far edge swap; this catches an inverted
        # axis; a pure TL-BL transposition is left to the Z sort that produced
        # them.
        self.assertLess(side_tl[1], side_bl[1],
                        "side TL is not above side BL")

    def test_corners_are_ordered_tl_tr_br_bl(self):
        scene = _dump_scene()
        tl, tr, br, bl = scene["front_face_px"]
        # Weak on their own: a same-side ordering holds for ANY consistent
        # sort, including the self-intersecting one this test used to miss
        # (see _assert_shared_edge_agrees). Kept because they are still true
        # of a correct quad, not because they would catch a wrong one.
        self.assertLess(tl[0], tr[0], "top-left is not left of top-right")
        self.assertLess(bl[0], br[0], "bottom-left is not left of bottom-right")
        self.assertLess(tl[1], bl[1], "top-left is not above bottom-left")
        self.assertLess(tr[1], br[1], "top-right is not above bottom-right")
        self._assert_shared_edge_agrees(scene)

    def test_the_quad_is_skewed_because_the_carton_is_rotated(self):
        # If this ever reads as a rectangle, either the rotation was removed or
        # the corners are being faked from nominal dimensions.
        tl, tr, br, bl = _dump_scene()["front_face_px"]
        left_height = bl[1] - tl[1]
        right_height = br[1] - tr[1]
        self.assertGreater(
            abs(left_height - right_height), 1.0,
            "the front face projects as a rectangle; the carton should be "
            "rotated 27.5-35 degrees about Z")

    def test_side_panel_corners_are_reported_too(self):
        self.assertIsNotNone(_dump_scene().get("side_panel_px"))

    def test_a_wide_shallow_carton_is_ordered_correctly(self):
        """Regression for the family the default 1-min carton never exercises.

        On a wide, shallow front face the far vertical edge can project
        ENTIRELY above the near one, so pairing top/bottom by PROJECTED y (the
        original algorithm) puts both smallest-y points on the same edge
        instead of one per edge and emits a self-intersecting (bowtie) quad.
        All 21 T3 SKU at 140x35x25mm (front-face aspect 4.00) hit this; the
        catalogue's next-widest geometry clears the y-split by 248px where
        this one misses it by 37px. Pairing by LOCAL Z instead (world-up,
        since the carton only rotates about Z) has no such blind spot.
        """
        job = _manifest()
        job["template_id"] = "T3"
        job["carton"].update(width_mm=140.0, height_mm=35.0, depth_mm=25.0)
        scene = _dump_scene(job)
        tl, tr, br, bl = scene["front_face_px"]
        self.assertLess(tl[0], tr[0])
        self.assertLess(bl[0], br[0])
        self.assertLess(tl[1], bl[1])
        self.assertLess(tr[1], br[1])
        self._assert_shared_edge_agrees(scene)

    def test_a_vertical_family_carton_is_ordered_correctly(self):
        """T_VERT_VIAL takes the 27.5deg/20deg camera path (VERTICAL_FAMILY in
        render_driver.py), which no other test here projects at all."""
        job = _manifest()
        job["template_id"] = "T_VERT_VIAL"
        job["carton"].update(width_mm=48.0, height_mm=115.0, depth_mm=48.0)
        scene = _dump_scene(job)
        tl, tr, br, bl = scene["front_face_px"]
        self.assertLess(tl[0], tr[0])
        self.assertLess(bl[0], br[0])
        self.assertLess(tl[1], bl[1])
        self.assertLess(tr[1], br[1])
        self._assert_shared_edge_agrees(scene)


class TestComputeDeviceIsStatedAndNotInherited(unittest.TestCase):
    """Which device drew the frame was a thing nobody chose and nobody could see.

    `setup_render()` set the engine, the sample count and `use_denoising`, and
    never assigned `scene.cycles.device`. Under `--factory-startup` that leaves
    CPU, so nothing looked wrong -- but nothing was choosing it, and Blender
    accepts more than one `--python`, so a script running ahead of the driver
    could move the entire render onto the GPU. `scripts/probe_render_device.py`
    does exactly that on purpose; this class is the reason it cannot happen by
    accident.

    IT IS NOT A QUALITY KNOB. Measured 2026-08-24 on an RTX 2060 SUPER at 16
    samples against the CPU render of `1-min`, `64-min` and `357-min`: OptiX
    sampling lands up to 43 levels away on 0.2-0.9% of pixels, CUDA up to 23 on
    0.2-0.7%, and GPU denoising up to 43 on 14-18%. Each would invalidate the
    calibration curve, every `design_qa` row and the OCR fixtures, all of which
    were measured on CPU pixels.
    """

    def test_config_states_a_device_and_a_denoiser(self):
        """Read without a default, so a deleted key fails rather than defaults.

        No Blender needed: this is about the config file, and skipping it on a
        machine without Blender would hide a broken config from CI.
        """
        blender = _CFG["blender"]
        for key in ("device", "device_backend", "denoising_device"):
            self.assertIn(key, blender,
                          f"config.yaml blender.{key} is missing; the device "
                          f"would go back to being whatever the process "
                          f"inherited.")
        self.assertIn(blender["device"], ("CPU", "GPU"))
        self.assertIn(blender["denoising_device"], ("CPU", "GPU"))

    def test_the_drivers_defaults_are_what_config_declares(self):
        """The two sides of a value nothing carries between them.

        The driver cannot read `config.yaml` -- it runs inside Blender's own
        interpreter and may not import project code -- and nothing passes these
        as flags yet, because that means editing `src/blender_renderer.py`.
        So the driver's flag DEFAULTS are what actually renders, and this test
        is the weld: change the config and the suite fails until the driver
        agrees, instead of the config quietly meaning nothing.

        Parsed out of the source rather than imported, because importing the
        driver outside Blender fails at `import bpy` on the first line.
        """
        import re
        src = DRIVER.read_text(encoding="utf-8")
        for flag, key in (("--device", "device"),
                          ("--device-backend", "device_backend"),
                          ("--denoising-device", "denoising_device")):
            m = re.search(rf'_arg\("{re.escape(flag)}",\s*"([^"]*)"\)', src)
            self.assertIsNotNone(
                m, f"render_driver.py has no default for {flag}")
            self.assertEqual(
                m.group(1).upper(), str(_CFG["blender"][key]).upper(),
                f"config.yaml says blender.{key} is "
                f"{_CFG['blender'][key]!r} but the driver's {flag} default is "
                f"{m.group(1)!r}. Nothing passes this flag, so the DRIVER's "
                f"value is the one that renders -- the config would be a "
                f"statement with no effect.")

    @unittest.skipUnless(_HAVE_BLENDER, _SKIP_REASON)
    def test_the_dump_reports_the_device_blender_actually_holds(self):
        """Read back off the scene, so it cannot agree by echoing its input."""
        device = _dump_scene()["device"]
        self.assertEqual(device["engine"], CONFIGURED_ENGINE)
        self.assertEqual(device["cycles_device"], _CFG["blender"]["device"])
        self.assertEqual(device["denoising_use_gpu"],
                         _CFG["blender"]["denoising_device"] == "GPU")

    @unittest.skipUnless(_HAVE_BLENDER, _SKIP_REASON)
    def test_a_cpu_render_never_reports_an_accelerator(self):
        """Blender leaves GPU devices flagged `use` in its own preferences.

        Reporting that list on a CPU render reads as though the card were doing
        the work. `scene.cycles.device` is the only thing that decides, so the
        list is reported only when it decides something.
        """
        device = _dump_scene()["device"]
        if device["cycles_device"] == "CPU":
            self.assertEqual(device["enabled_devices"], [])
            self.assertIsNone(device["backend"])

    @unittest.skipUnless(_HAVE_BLENDER, _SKIP_REASON)
    def test_an_unavailable_backend_is_fatal_rather_than_a_fallback(self):
        """The rule the engine already follows, applied to the device.

        A GPU setting that quietly renders on the CPU is the same defect as an
        engine that quietly renders in EEVEE: the pixels change and the log does
        not say so. Asked for a back-end this Blender does not offer, the driver
        must exit non-zero and write nothing.
        """
        with tempfile.TemporaryDirectory() as td:
            job_path = Path(td) / "job.json"
            out_path = Path(td) / "out.png"
            job_path.write_text(json.dumps(_manifest()), encoding="utf-8")
            proc = subprocess.run(
                [str(BLENDER_EXE), "--background", "--factory-startup",
                 "--python", str(DRIVER), "--",
                 "--job", str(job_path), "--out", str(out_path),
                 "--engine-type", CONFIGURED_ENGINE,
                 "--samples", "1", "--res-x", "64", "--res-y", "64",
                 "--device", "GPU", "--device-backend", "NO_SUCH_BACKEND"],
                capture_output=True, text=True, timeout=300)
        self.assertNotEqual(proc.returncode, 0,
                            "an unavailable back-end rendered anyway")
        self.assertFalse(out_path.exists(), "it wrote a PNG on the wrong device")
        self.assertIn("NO_SUCH_BACKEND", proc.stdout + proc.stderr,
                      "the failure does not name the back-end that was refused")


if __name__ == "__main__":
    unittest.main()

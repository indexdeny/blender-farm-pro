"""Render isolated, detailed white carton shells for matched reference SKUs.

The production manifests are read-only inputs.  Each Blender invocation consumes
a temporary diagnostic copy with a measured carton profile and no printed
content; no production spec, manifest or render is rewritten.
"""
from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.design_group import TEMPLATE_SAMPLE
from src.render_manifest import load_manifest, manifest_path_for
from src.utils import get_path, load_config, resolve_path


PROFILE_SPEC = PROJECT_ROOT / "Reference Templates" / "74_Viagra" / "design_spec.json"
_CFG = load_config()
MANIFESTS_DIR = get_path(_CFG, "passports_manifests")
_BLENDER = _CFG["blender"]
BLENDER_EXE = str(_BLENDER["executable"])
DRIVER_SCRIPT = str(resolve_path(_BLENDER["driver_script"]))
ENGINE = str(_BLENDER.get("engine_type", "CYCLES"))
SAMPLES = int(_BLENDER.get("samples", 16))
RESOLUTION = tuple(int(value) for value in _BLENDER.get("resolution", [2048, 2048]))
TIMEOUT = int(_BLENDER.get("render_timeout", 300))

DIMENSION_KEYS = ("width_mm", "height_mm", "depth_mm")
EMPTY_DUMP_CHANNELS = (
    "design_fields", "label", "side_panel", "reference_aux_text", "relief",
)


def _sort_stem(stem: str) -> tuple[int, str]:
    prefix = stem.split("-", 1)[0]
    return (int(prefix) if prefix.isdigit() else 999999, stem)


def matching_reference_stems(
        dimensions_mm: tuple[float, float, float] = (110.0, 50.0, 18.0),
) -> list[str]:
    """Return only reference-template SKU with matching passport dimensions."""
    target = tuple(float(value) for value in dimensions_mm)
    matches = []
    for stem in set(TEMPLATE_SAMPLE.values()):
        manifest = load_manifest(manifest_path_for(stem, MANIFESTS_DIR))
        passport_dims = manifest["carton"]["passport_dimensions"]
        measured = tuple(float(passport_dims[key]) for key in DIMENSION_KEYS)
        if measured == target:
            matches.append(stem)
    return sorted(matches, key=_sort_stem)


def _measured_profile() -> dict:
    spec = json.loads(PROFILE_SPEC.read_text(encoding="utf-8"))
    return copy.deepcopy(spec["carton_profile"])


def blank_job(manifest: dict, dimensions_mm: tuple[float, float, float]) -> dict:
    """Build a disposable physical shell without mutating the canonical job."""
    job = copy.deepcopy(manifest)
    dimensions = tuple(float(value) for value in dimensions_mm)
    for key, value in zip(DIMENSION_KEYS, dimensions):
        job["carton"][key] = value
    job["carton"]["features"] = []
    job["label_content"] = {}
    job.pop("side_panel", None)
    job["palette"] = {
        **(job.get("palette") or {}),
        "primary": "#FFFFFF",
        "accent": "#FFFFFF",
        "background": "#FFFFFF",
    }
    job["design"] = {
        "spec_version": "0.1",
        "face_aspect": dimensions[1] / dimensions[0],
        "substrate": "#FFFFFF",
        "fields": [],
        "marks": [],
        "type_rows": {},
        "reference_aux_text": [],
        "carton_profile": _measured_profile(),
    }
    return job


def validate_blank_dump(scene: dict) -> None:
    """Fail closed if diagnostic output contains content or lost carton detail."""
    for key in EMPTY_DUMP_CHANNELS:
        if scene.get(key) != []:
            raise ValueError(f"blank scene contains non-empty {key}")
    carton = scene.get("carton") or {}
    color = carton.get("base_color") or []
    if len(color) < 3 or any(abs(float(channel) - 1.0) > 1e-6 for channel in color[:3]):
        raise ValueError(f"blank carton is not white: {color}")
    if not scene.get("carton_profile"):
        raise ValueError("blank scene lost carton_profile")
    if not scene.get("visible_carton_geometry"):
        raise ValueError("blank scene lost measured flap/seam geometry")
    finish = carton.get("material_finish") or {}
    if not finish.get("noise_scale") or not finish.get("bump_strength"):
        raise ValueError("blank scene lost measured paper micro-bump")


def _run_blender(job_path: Path, *, out_path: Path | None = None,
                 dump_path: Path | None = None) -> None:
    cmd = [
        BLENDER_EXE, "--background", "--factory-startup",
        "--python", DRIVER_SCRIPT, "--",
        "--job", str(job_path), "--blank-carton",
        "--engine-type", ENGINE, "--samples", str(SAMPLES),
        "--res-x", str(RESOLUTION[0]), "--res-y", str(RESOLUTION[1]),
    ]
    if out_path is not None:
        cmd.extend(("--out", str(out_path)))
    if dump_path is not None:
        cmd.extend(("--dump-scene", str(dump_path)))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    expected = dump_path if dump_path is not None else out_path
    if result.returncode != 0 or expected is None or not expected.exists():
        tail = (result.stderr or result.stdout or "")[-3000:]
        raise RuntimeError(f"Blender failed for {job_path.name}: {tail}")


def render_blank(stem: str, dimensions_mm: tuple[float, float, float],
                 output_dir: Path) -> tuple[Path, Path]:
    output_dir = output_dir.resolve()
    manifest = load_manifest(manifest_path_for(stem, MANIFESTS_DIR))
    job = blank_job(manifest, dimensions_mm)
    output_dir.mkdir(parents=True, exist_ok=True)
    job_path = output_dir / f".{stem}-blank.job.json"
    png_path = output_dir / f"{stem}-blank.png"
    dump_path = output_dir / f"{stem}-blank.scene.json"
    job_path.write_text(json.dumps(job, indent=2), encoding="utf-8")
    try:
        _run_blender(job_path, dump_path=dump_path)
        validate_blank_dump(json.loads(dump_path.read_text(encoding="utf-8")))
        _run_blender(job_path, out_path=png_path)
    finally:
        if job_path.exists():
            job_path.unlink()
    return png_path, dump_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dimensions", type=float, nargs=3,
                        default=(110.0, 50.0, 18.0),
                        metavar=("WIDTH", "HEIGHT", "DEPTH"))
    parser.add_argument("--exclude", action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    dimensions = tuple(args.dimensions)
    stems = [stem for stem in matching_reference_stems(dimensions)
             if stem not in set(args.exclude)]
    for stem in stems:
        png, dump = render_blank(stem, dimensions, args.out)
        print(f"{stem}: {png} | {dump}")
    print(f"rendered {len(stems)} isolated blank carton(s)")


if __name__ == "__main__":
    main()

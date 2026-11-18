"""Build the authorized physical baseline through the canonical manifest."""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))


def main():
    from src.carton_spec import load_spec, workspace_root
    from src.carton_artwork import generate_artwork
    from src.render_manifest import build_baseline_manifest, write_manifest

    parser = argparse.ArgumentParser()
    parser.add_argument("--views", default="front,hero,top,end")
    parser.add_argument("--dump-only", action="store_true")
    parser.add_argument("--reuse-artwork", action="store_true")
    parser.add_argument("--output-stem")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args()
    if args.output_root is not None:
        os.environ["BFP_PHYSICAL_OUTPUT_ROOT"] = str(args.output_root.resolve())
    root = workspace_root()
    spec = load_spec(args.spec)
    sku = spec["sku"]
    args.output_stem = args.output_stem or f"{sku}-physical"
    if Path(args.output_stem).name != args.output_stem:
        raise ValueError("Output stem must be a filename")
    renders = root / "renders"
    reports = root / "reports"
    root.mkdir(parents=True, exist_ok=True)
    renders.mkdir(exist_ok=True)
    reports.mkdir(exist_ok=True)
    passport = json.loads(
        (CODE_ROOT / "04_passports/passports_json" / f"{sku}.json").read_text("utf-8")
    )
    if args.reuse_artwork:
        art = json.loads(
            (root / "assets/generated" / sku / "artwork-manifest.json").read_text(
                "utf-8"
            )
        )
    else:
        art = generate_artwork(spec)
    manifest = build_baseline_manifest(passport, spec, art)
    job = root / "assets/generated" / sku / "render-manifest.json"
    write_manifest(manifest, job)
    import yaml

    config = yaml.safe_load((CODE_ROOT / "config.yaml").read_text("utf-8"))
    command = [
        config["blender"]["executable"],
        "--background",
        "--factory-startup",
        "--python",
        str(CODE_ROOT / "05_assets/blender/render_driver.py"),
        "--",
        "--job",
        str(job),
        "--out",
        str(renders / (args.output_stem + ".png")),
        "--physical-views",
        args.views,
    ]
    if args.dump_only:
        command += [
            "--dump-scene",
            str(
                reports
                / (
                    "physical-scene-build.json"
                    if sku == "74-min"
                    else f"{sku}-scene-build.json"
                )
            ),
        ]
    command += ["--save-blend", str(renders / f"{sku}-baseline-rebuild.blend")]
    start = time.perf_counter()
    with (reports / (args.output_stem + ".log")).open("w", encoding="utf-8") as log:
        result = subprocess.run(
            command,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=1800,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
    summary = dict(
        exit_code=result.returncode,
        seconds=time.perf_counter() - start,
        command=command,
        artwork_seconds=art["generation_seconds"],
    )
    (reports / (args.output_stem + "-run.json")).write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()

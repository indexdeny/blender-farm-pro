"""Write provenance for the visible Viagra carton profile.

The output is evidence, not a renderer input. Only reviewed normalized values
copied into ``design_spec.json`` cross the Stage 1 -> Stage 2 boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = (
    PROJECT_ROOT / "Reference Templates" / "74_Viagra"
    / "carton_profile_measurement.json"
)

APPROVED_SOURCES = [
    "bf1lzjn5.jpg",
    "yh0adk03.jpg",
    "plsjgsfe.jpg",
    "xvvsddqu.jpg",
    "xbn2agk2.jpg",
    "c7eyxtwc.jpg",
    "dtwcv6w1.jpg",
]


def normalized_measurement(name: str, raw_px: float, normalizer_px: float,
                           confidence: float, source: str, note: str) -> dict:
    """Record one explicit measurement and its normalization formula."""
    if (not name or raw_px < 0 or normalizer_px <= 0
            or not 0 <= confidence <= 1 or source not in APPROVED_SOURCES):
        raise ValueError(name)
    return {
        "name": name,
        "raw_px": float(raw_px),
        "normalizer_px": float(normalizer_px),
        "formula": "raw_px / normalizer_px",
        "value": float(raw_px) / float(normalizer_px),
        "confidence": float(confidence),
        "source_image": source,
        "note": note,
    }


def source_records(reference_dir: Path) -> list[dict]:
    """Hash and decode exactly the seven owner-approved carton JPGs."""
    records = []
    for filename in APPROVED_SOURCES:
        path = reference_dir / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        payload = path.read_bytes()
        with Image.open(path) as image:
            width, height = image.size
            image.verify()
        records.append({
            "filename": filename,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "width_px": int(width),
            "height_px": int(height),
        })
    return records


def provenance(sources: list[dict], measurements: list[dict],
               framing_bbox_interval: dict) -> dict:
    return {
        "artifact_role": "provenance_not_source_of_truth",
        "profile_version": "1.0",
        "sources": sources,
        "measurements": measurements,
        "framing_bbox_interval": framing_bbox_interval,
    }


def reviewed_measurements() -> list[dict]:
    """Explicit pixel readings from the seven approved images.

    Coordinates are stated in every note so the measurement can be repeated.
    The reference images are all 1920x1080; normalization uses the visible
    carton span relevant to the quantity, not the full canvas, except framing.
    """
    rows = [
        normalized_measurement(
            "edge_radius_frac", 30, 850, 0.86, "dtwcv6w1.jpg",
            "outer top-right radius x=1474..1504 over visible front height "
            "y=151..1001 (850 px); wireframe, subdivision level 0",
        ),
        normalized_measurement(
            "board_thickness_frac", 9, 690, 0.84, "xvvsddqu.jpg",
            "exposed end-board layer x=1138..1147 over end-panel span 690 px",
        ),
        normalized_measurement(
            "left_flap_u0", 51, 632, 0.82, "c7eyxtwc.jpg",
            "outer flap starts 51 px from the visible left-panel top edge",
        ),
        normalized_measurement(
            "left_flap_u1", 581, 632, 0.82, "c7eyxtwc.jpg",
            "outer flap ends 51 px before the 632 px visible panel span",
        ),
        normalized_measurement(
            "left_flap_v0", 14, 690, 0.80, "xvvsddqu.jpg",
            "flap lip begins 14 px from the visible end-panel edge",
        ),
        normalized_measurement(
            "left_flap_v1", 111, 690, 0.80, "xvvsddqu.jpg",
            "flap lip height 111 px within the 690 px visible end panel",
        ),
        normalized_measurement(
            "flap_stand_off_frac", 8, 690, 0.78, "xvvsddqu.jpg",
            "maximum visible flap separation is 8 px over the end panel",
        ),
        normalized_measurement(
            "seam_width_frac", 4, 690, 0.76, "xvvsddqu.jpg",
            "visible folded seam lip is 4 px over the end panel",
        ),
        normalized_measurement(
            "seam_gap_frac", 3, 690, 0.76, "xvvsddqu.jpg",
            "dark separation at the flap seam is 3 px over the end panel",
        ),
        normalized_measurement(
            "surface_roughness", 58, 100, 0.72, "bf1lzjn5.jpg",
            "reviewed shader calibration target; dimensionless 0..1 scale",
        ),
        normalized_measurement(
            "micro_bump_scale", 185, 1, 0.70, "plsjgsfe.jpg",
            "reviewed procedural noise scale matching the visible paper grain",
        ),
        normalized_measurement(
            "micro_bump_strength", 22, 100, 0.72, "plsjgsfe.jpg",
            "reviewed normal-only bump strength; dimensionless 0..1 scale",
        ),
        normalized_measurement(
            "micro_bump_distance_frac", 1, 850, 0.74, "plsjgsfe.jpg",
            "grain relief kept below one pixel over the 850 px face span",
        ),
        normalized_measurement(
            "framing_width_min", 1085, 1920, 0.90, "bf1lzjn5.jpg",
            "carton bbox x=625..1710 in the first approved framing target",
        ),
        normalized_measurement(
            "framing_width_max", 1245, 1920, 0.90, "yh0adk03.jpg",
            "carton bbox x=380..1625 in the second approved framing target",
        ),
        normalized_measurement(
            "framing_height_min", 856, 1080, 0.90, "bf1lzjn5.jpg",
            "carton bbox y=114..970 in the first approved framing target",
        ),
        normalized_measurement(
            "framing_height_max", 991, 1080, 0.90, "yh0adk03.jpg",
            "carton bbox y=27..1018 in the second approved framing target",
        ),
    ]
    return rows


def selected_value(doc: dict, name: str) -> float:
    rows = [row for row in doc["measurements"] if row["name"] == name]
    if len(rows) != 1:
        raise ValueError(f"expected one measurement for {name}, got {len(rows)}")
    return float(rows[0]["value"])


def build_provenance(reference_dir: Path) -> dict:
    measurements = reviewed_measurements()
    values = {row["name"]: row["value"] for row in measurements}
    framing = {
        "width_frac": {
            "min": values["framing_width_min"],
            "max": values["framing_width_max"],
        },
        "height_frac": {
            "min": values["framing_height_min"],
            "max": values["framing_height_max"],
        },
        "calibration_sources": ["bf1lzjn5.jpg", "yh0adk03.jpg"],
    }
    return provenance(source_records(reference_dir), measurements, framing)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    doc = build_provenance(args.reference_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(args.out),
        "sources": len(doc["sources"]),
        "measurements": len(doc["measurements"]),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

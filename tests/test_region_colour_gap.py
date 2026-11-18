"""The region map must not move when paint does, and the old one does.

Contract 1.9 -- a part carries its own fill -- was built, measured and rolled
back, and one of the two reasons was that `design_qa`'s figures are computed
against a palette which is itself made of the paints being changed. Before and
after were two instruments rather than two renders
(00_PROJECT_STATE/PART_FILL.md).

`region_colour_gap` was added to answer the same question without a vocabulary:
its regions come from `spec_index`, which reads OUTLINES. This pins that
property, and pins it the only way that means anything -- by showing that the
classified path moves under the same perturbation. A test that only asserted the
new figure is stable would pass just as well if nothing were sensitive to
anything.
"""
from __future__ import annotations

import unittest

import numpy as np

from scripts.design_coverage import SUBSTRATE, spec_index
from scripts.design_qa import _classify, _hex_rgb
from scripts.fit_design_spec import rasterise

W = H = 120


def _spec(fill_a: str, fill_b: str) -> dict:
    """Two fields, two rectangles, nothing else. Outlines identical throughout.

    Contract 1.9: a part carries its own fill and `rasterise` paints it, with no
    fallback to the field's. Here the two are equal, because what this fixture
    perturbs is the paint and not the part-versus-field question.
    """
    return {
        "substrate": "#FFFFFF",
        "face_aspect": 1.0,
        "fields": [
            {"role": "brand", "z": 0, "fill": fill_a, "coverage_pct": 10.0,
             "parts": [{"kind": "field", "area_pct": 10.0, "smoothness": 0.0,
                        "holes": [], "fill": fill_a,
                        "outline": [[0.10, 0.10], [0.45, 0.10],
                                    [0.45, 0.45], [0.10, 0.45]]}]},
            {"role": "highlight", "z": 1, "fill": fill_b, "coverage_pct": 10.0,
             "parts": [{"kind": "field", "area_pct": 10.0, "smoothness": 0.0,
                        "holes": [], "fill": fill_b,
                        "outline": [[0.55, 0.55], [0.90, 0.55],
                                    [0.90, 0.90], [0.55, 0.90]]}]},
        ],
    }


def _palette(spec: dict) -> np.ndarray:
    """The palette `design_qa` builds today: substrate plus one per field."""
    return np.stack([_hex_rgb(spec["substrate"])]
                    + [_hex_rgb(f["fill"]) for f in spec["fields"]])


#: Far apart, then moved to within a thousandth. `SEPARABLE_MIN` is 0.08, and
#: `221_Inderal` really carries two paints 0.002 apart -- splitting them took
#: that carton's worst field to 0.0% and `357_Adderall`'s render~ref to 37.8%
#: on renders that had not changed. This reproduces that in miniature.
FAR_A, FAR_B = "#E05506", "#2D3336"
NEAR_B = "#E05507"


class TestTheGeometricRegionMapIsInvariantToPaint(unittest.TestCase):

    def test_spec_index_does_not_move_when_a_fill_moves(self):
        before = spec_index(_spec(FAR_A, FAR_B), W, H)
        after = spec_index(_spec(FAR_A, NEAR_B), W, H)
        self.assertTrue(
            np.array_equal(before, after),
            "spec_index changed when only a fill changed; it must read outlines "
            "and nothing else, which is the whole basis of region_colour_gap")

    def test_it_really_is_two_regions_and_a_substrate(self):
        """Guards the test itself: an all-substrate map would pass trivially."""
        idx = spec_index(_spec(FAR_A, FAR_B), W, H)
        self.assertEqual(sorted(set(int(v) for v in np.unique(idx))),
                         [0, 1, SUBSTRATE])
        for k in (0, 1):
            self.assertGreater(int((idx == k).sum()), 500, f"region {k} is empty")

    def _noisy(self, spec):
        """The rasterisation as a picture rather than as an answer key.

        Classifying the CLEAN raster proves nothing -- every pixel is exactly one
        palette entry, so nearest-colour recovers the geometry however close two
        paints are. What `design_qa` actually classifies is a RENDER and a
        PHOTOGRAPH, and both carry noise. The collapse recorded on `221_Inderal`
        and `357_Adderall` is that noise crossing a gap of 0.002.

        Deterministic rather than seeded: a committed measurement may not move
        between runs, and a test that demonstrates a mechanism should not either.
        """
        from PIL import Image
        arr = np.asarray(rasterise(spec, W, H)).astype(float) / 255.0
        yy, xx = np.mgrid[0:H, 0:W]
        wobble = (0.010 * np.sin(yy / 3.0) * np.cos(xx / 5.0))[..., None]
        arr = np.clip(arr + wobble, 0.0, 1.0)
        return Image.fromarray((arr * 255).round().astype("uint8"), "RGB")

    def test_the_classified_map_DOES_move_under_the_same_change(self):
        """Without this the invariance above proves nothing.

        Far apart, nearest-colour recovers the geometry through the noise. A
        thousandth apart, it cannot: the noise is ten times the gap, and the two
        regions scramble between the two entries. `spec_index` is untouched by
        exactly the same edit.
        """
        far, near = _spec(FAR_A, FAR_B), _spec(FAR_A, NEAR_B)
        geo = spec_index(far, W, H)
        idx_far, _ = _classify(self._noisy(far), _palette(far))
        idx_near, _ = _classify(self._noisy(near), _palette(near))

        # Palette index k+1 is field k; SUBSTRATE is palette 0.
        want = np.where(geo == SUBSTRATE, 0, geo + 1)
        agree_far = float((idx_far == want).mean())
        agree_near = float((idx_near == want).mean())
        self.assertGreater(
            agree_far, 0.99,
            f"the classifier failed to recover the geometry even with the paints "
            f"far apart ({agree_far:.3f}); the demonstration is broken, not the point")
        self.assertLess(
            agree_near, 0.95,
            f"the classifier still recovered the geometry with two paints 0.001 "
            f"apart ({agree_near:.3f}); if that is really so, region_colour_gap "
            f"solves nothing and this whole line of work should be re-read")

    def test_geometry_survives_the_change_that_breaks_the_classifier(self):
        """The two halves of the point, on one perturbation, side by side."""
        far, near = _spec(FAR_A, FAR_B), _spec(FAR_A, NEAR_B)
        self.assertTrue(np.array_equal(spec_index(far, W, H),
                                       spec_index(near, W, H)),
                        "the geometric map moved")
        idx_far, _ = _classify(self._noisy(far), _palette(far))
        idx_near, _ = _classify(self._noisy(near), _palette(near))
        self.assertFalse(np.array_equal(idx_far, idx_near),
                         "the classified map did not move")


if __name__ == "__main__":
    unittest.main()

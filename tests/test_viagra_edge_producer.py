"""Regression from the measured source, after every producer postprocess."""
import copy
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from scripts import fit_design_spec as fitter
from scripts.shadow_alignment_qa import band_metrics

ROOT = Path(__file__).resolve().parents[1]


def span(outline, v):
    hits = []
    for a, b in zip(outline, outline[1:] + outline[:1]):
        if min(a[1], b[1]) <= v <= max(a[1], b[1]) and a[1] != b[1]:
            hits.append(a[0] + (b[0]-a[0]) * (v-a[1]) / (b[1]-a[1]))
    return min(hits), max(hits)


class TestProducerEdgeRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = ROOT / 'Reference Templates/74_Viagra'
        if not any(p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'}
                   for p in folder.iterdir()):
            raise unittest.SkipTest(
                'NOT VERIFIED: optional producer reference photography is not installed')
        with patch.object(fitter, 'write_complete_spec'):
            try:
                cls.spec = fitter.fit(folder)
            except SystemExit as error:
                raise AssertionError(
                    'Supplied reference dataset was rejected by the producer') from error

    def test_final_navy_and_blue_share_one_exact_edge(self):
        navy = next(f for f in self.spec['fields'] if f['role'] == 'brand')['parts'][0]
        band = next(f for f in self.spec['fields'] if f['role'] == 'recovered_01')['parts'][0]
        gaps = [abs(span(band['outline'], v)[0] - span(navy['outline'], v)[1])
                for v in np.linspace(.001, .998, 101)]
        self.assertLessEqual(max(gaps), 1e-6)

    def test_final_band_preserves_straight_edges(self):
        band = next(f for f in self.spec['fields'] if f['role'] == 'recovered_01')['parts'][0]
        metrics = band_metrics(band['outline'])
        self.assertLessEqual(metrics['left_max_residual'], 1e-6)
        self.assertLessEqual(metrics['right_max_residual'], 1e-6)

    def test_final_navy_left_is_continuous_with_reviewed_side_ink(self):
        navy = next(f for f in self.spec['fields'] if f['role'] == 'brand')['parts'][0]
        self.assertLessEqual(max(abs(span(navy['outline'],v)[0]) for v in
                                 np.linspace(.04,.998,300)), 1e-6)

    def test_pfizer_preserves_disconnected_letters_and_their_counters(self):
        mark = self.spec['marks'][0]
        self.assertEqual(mark['key'], 'brand#0/hole#0')
        self.assertEqual(len(mark.get('parts', [])), 4)
        self.assertEqual(sorted(len(p['holes']) for p in mark['parts']), [0,0,1,1])


class TestFoldPreservesVectorGeometry(unittest.TestCase):
    def test_already_closed_slanted_band_is_not_rasterized_again(self):
        part = {'fill':'#AAC1DB', 'outline':[[.23,0],[.2691,0],[.2373,1],[.1982,1]],'holes':[]}
        before=copy.deepcopy(part)
        spec={'fields':[{'parts':[part]}, {'surface':'top','parts':[{
            'fill':'#AAC1DB','outline':[[.2291,0],[.2682,0],[.2682,1],[.2291,1]]}]}]}
        fitter.close_matching_front_top_fold(spec,1100,838)
        self.assertEqual(part,before)

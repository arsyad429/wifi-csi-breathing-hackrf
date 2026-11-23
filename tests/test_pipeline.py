"""Uji DSP dan batas validasi. Tidak membutuhkan HackRF atau koneksi jaringan."""
import copy
import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from caseb.analysis import load_trial, peak, predict, select_carriers, spectra
from caseb.radio import AMP, K, extract
from caseb.synthetic import make_dataset, make_iq

BASE = Path(__file__).resolve().parents[1]
CFG = json.loads((BASE/"config/default.json").read_text())


class PipelineTests(unittest.TestCase):
    def test_iq_coarse_cfo_and_chunk_boundary(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            cfg = {**CFG, "chunk_samples": 4000}
            # Burst starts just before the chunk boundary; CFO exceeds fine range.
            truth = make_iq(d/"test.cs8", duration=.012, starts=[3980, 80000, 160000], cfo_hz=220000)
            qc = extract(d/"test.cs8", d/"out", cfg, {}, logging.getLogger("test"))
            df = pd.read_csv(d/"out/csi.csv")
            self.assertEqual(qc["valid_packets"], 3)
            self.assertLess(abs(df.cfo_hz.median()-220000), 3000)
            self.assertLess(np.median(abs(df[AMP].to_numpy()-truth["amplitude"])/truth["amplitude"]), .05)
            np.testing.assert_allclose(df.t_s, np.array(truth["packet_start_s"])+192/20e6, atol=2/20e6)

    def test_noise_does_not_make_csi(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            make_iq(d/"test.cs8", duration=.01, starts=[])
            qc = extract(d/"test.cs8", d/"out", CFG, {}, logging.getLogger("test"))
            self.assertEqual(qc["valid_packets"], 0)
            self.assertFalse(qc["pilot_pass"])

    def test_negative_adc_saturation_is_counted_without_int8_overflow(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            path = d/"clipped.cs8"
            np.full(8000, -128, dtype=np.int8).tofile(path)
            qc = extract(path, d/"out", CFG, {}, logging.getLogger("test"))
            self.assertEqual(qc["clipped_component_fraction"], 1)
            self.assertEqual(qc["clipping_status"], "fail")
            histogram = pd.read_csv(d/"out/adc_histogram.csv")
            self.assertEqual(histogram.component_count.sum(), 8000)

    def test_truncated_iq_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"odd.cs8"
            p.write_bytes(b"123")
            with self.assertRaises(ValueError):
                extract(p, Path(d)/"out", CFG, {}, logging.getLogger("test"))

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.dataset = make_dataset(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def trial(self, name="B_S1_P1_10"):
        folder = self.root/name
        meta = json.loads((folder/"metadata.json").read_text())
        return load_trial(folder/"csi.csv", meta, CFG)

    def test_three_windows_and_known_rate(self):
        t = self.trial()
        ws = spectra(t, CFG)
        self.assertEqual([w["start_s"] for w in ws], [0, 15, 30])
        chosen, _ = select_carriers([t], CFG)
        rows = [r for r in predict(t, chosen, CFG) if r["method"] == "csi_selected"]
        self.assertTrue(all(r["reliable"] for r in rows))
        self.assertTrue(all(abs(r["pred_bpm"]-10) <= 2 for r in rows))

    def test_long_gap_invalidates_all_crossing_windows(self):
        t = self.trial()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"gapped.csv"
            df = t["df"]
            df[~df.t_s.between(20, 22)].to_csv(path, index=False)
            trial = load_trial(path, t["meta"], CFG)
            ws = spectra(trial, CFG)
            self.assertFalse(ws[0]["quality_ok"])
            self.assertFalse(ws[1]["quality_ok"])
            self.assertTrue(ws[2]["quality_ok"])
            self.assertTrue(np.isnan(trial["filtered"][(trial["t"] > 20.1) & (trial["t"] < 21.9)]).all())

    def test_unverified_transmitter_never_reliable(self):
        t = self.trial()
        t["meta"]["tx_verified"] = False
        t = load_trial(t["path"], t["meta"], CFG)
        self.assertFalse(any(r["reliable"] for r in predict(t, [0], CFG)))

    def test_short_control_has_energy_but_no_30s_prediction(self):
        trial = self.trial("B_S1_P1_breath_hold")
        self.assertEqual(spectra(trial, CFG), [])
        self.assertTrue(np.isfinite(trial["filtered"]).all())

    def test_missing_actual_count_is_not_target_ground_truth(self):
        trial = self.trial()
        trial["meta"]["actual_breath_count"] = None
        self.assertTrue(all(r["ground_truth_bpm"] is None for r in predict(trial, [0], CFG)))

    def test_training_selection_does_not_use_labels_or_held_out_signals(self):
        train = [self.trial("B_S1_P1_10"), self.trial("B_S2_P1_20")]
        selected, scores = select_carriers(train, CFG)
        mutated = copy.deepcopy(train)
        for t in mutated:
            t["meta"]["actual_breath_count"] = 999
            t["meta"]["target_bpm"] = 999
        selected2, scores2 = select_carriers(mutated, CFG)
        np.testing.assert_array_equal(selected, selected2)
        np.testing.assert_allclose(scores, scores2)
        # Held-out trial never enters the selection function's input.
        held = self.trial("B_S3_P1_15")
        held["filtered"] *= 0
        np.testing.assert_array_equal(select_carriers(train, CFG)[0], selected)

    def test_failed_invocation_is_archived(self):
        with tempfile.TemporaryDirectory() as d:
            result = subprocess.run([sys.executable, str(BASE/"case_b.py"), "--output-root", d,
                                     "extract", "missing.cs8", "--metadata", "missing.json"],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            manifests = list(Path(d).glob("*/manifest.json"))
            self.assertEqual(len(manifests), 1)
            self.assertEqual(json.loads(manifests[0].read_text())["status"], "failed")
            self.assertTrue((manifests[0].parent/"error.txt").exists())

    def test_wrong_session_metadata_is_rejected(self):
        t = self.trial()
        t["meta"]["session_id"] = "S99"
        with self.assertRaises(ValueError):
            load_trial(t["path"], t["meta"], CFG)

    def test_windows_powershell_command_preserves_spaces_and_quotes(self):
        from caseb.runlog import command_text
        cmd = command_text([r"C:\Data Project\python.exe", "case_b.py", r"D:\O'Brien\m.json"], windows=True)
        self.assertEqual(cmd, "& 'C:\\Data Project\\python.exe' 'case_b.py' 'D:\\O''Brien\\m.json'")

    def test_powershell_utf8_bom_metadata_is_accepted(self):
        from case_b import load_meta
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"metadata.json"
            p.write_text(json.dumps({"session_id": "S1", "subject_id": "P1", "scenario": "breathing",
                                     "duration_s": 60, "note": "UTF-8 BOM dari PowerShell"}), encoding="utf-8-sig")
            from unittest.mock import Mock
            self.assertEqual(load_meta(p, Mock())["session_id"], "S1")

    def test_leave_one_person_out_keeps_people_separate(self):
        from caseb.analysis import evaluate
        trials = [self.trial("B_S1_P1_10"), self.trial("B_S2_P2_20"), self.trial("B_S3_P3_15")]
        with tempfile.TemporaryDirectory() as d, patch("caseb.analysis.trial_plots"):
            evaluate(trials, d, CFG, group="subject_id")
            folds = json.loads((Path(d)/"folds.json").read_text(encoding="utf-8"))
            self.assertEqual(len(folds), 3)
            subjects = {t["meta"]["trial_id"]: t["meta"]["subject_id"] for t in trials}
            for fold in folds:
                self.assertTrue(all(subjects[x] != fold["held_out"] for x in fold["training_trials"]))
                self.assertTrue(all(subjects[x] == fold["held_out"] for x in fold["test_trials"]))

    def test_evaluation_without_gt_still_writes_null_metrics_and_disjoint_folds(self):
        from caseb.analysis import evaluate
        trials = [self.trial("B_S1_P1_10"), self.trial("B_S2_P1_20")]
        for t in trials:
            t["meta"]["actual_breath_count"] = None
        with tempfile.TemporaryDirectory() as d, patch("caseb.analysis.trial_plots"):
            evaluate(trials, d, CFG)
            summary = json.loads((Path(d)/"summary.json").read_text())
            self.assertFalse(summary["all_labeled"])
            self.assertIsNone(summary["metrics"][0]["mae_csi"])
            folds = json.loads((Path(d)/"folds.json").read_text())
            for fold in folds:
                self.assertFalse(set(fold["training_trials"]) & set(fold["test_trials"]))


if __name__ == "__main__":
    unittest.main()

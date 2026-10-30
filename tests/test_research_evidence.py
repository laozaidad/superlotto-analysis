"""存档证据重算不允许事后换范围、扩大池或忽略训练泄漏。"""

import copy
import csv
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("evidence_builder", ROOT / "scripts/build_research_evidence.py")
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.study = json.loads((ROOT / "site/data/research-study.json").read_text())

    def test_recounts_saved_predictions(self):
        result = builder.build_evidence(self.study)
        self.assertEqual(
            [(r["left_hits"], r["right_hits"]) for r in result["comparisons"]], [(85, 40), (81, 45), (91, 36)]
        )
        self.assertTrue(all(r["full_coverage_count"] == 0 for r in result["all_tests"]))
        self.assertTrue(all(r["p_left_adjusted"] == r["p_right_adjusted"] == 1 for r in result["all_tests"]))
        self.assertEqual(result["prediction_gate"], "CLOSED")

    def test_future_duplicate_missing_or_enlarged_pool_rejected(self):
        for mutation in ("future", "duplicate", "missing", "pool", "blind", "source_path", "actual"):
            item = copy.deepcopy(self.study)
            if mutation == "future":
                item["rows"][0]["gate_training_last_id"] = item["rows"][0]["target"]
            if mutation == "duplicate":
                item["rows"].append(item["rows"][0])
            if mutation == "missing":
                item["rows"].pop()
            if mutation == "pool":
                item["rows"][0]["pools"][0]["left"].append(35)
            if mutation == "blind":
                item["historical_data_previously_seen"] = False
            if mutation == "source_path":
                item["source_hashes"]["private_path"] = "/private/not-for-public"
            if mutation == "actual":
                item["rows"][0]["actual_left"] = [1, 2, 3, 4, 5]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                builder.build_evidence(item)

    def test_hypergeometric_distribution_known_cases(self):
        self.assertEqual(builder.total_hit_pmf(2, 1, 1, 2), [0.25, 0.5, 0.25])
        mass = builder.total_hit_pmf(35, 5, 5, 123)
        self.assertAlmostEqual(sum(mass), 1, places=12)
        self.assertAlmostEqual(sum(i * p for i, p in enumerate(mass)), 123 * 25 / 35, places=10)

    def test_actual_draws_match_independent_public_history(self):
        with (ROOT / "site/runtime/history.csv").open(encoding="utf-8-sig", newline="") as handle:
            actual = {
                row["No."]: ([int(row[f"L{i}"]) for i in range(1, 6)], [int(row[f"R{i}"]) for i in range(1, 3)])
                for row in csv.DictReader(handle)
            }
        for row in self.study["rows"]:
            self.assertEqual((row["actual_left"], row["actual_right"]), actual[row["target"]])

    def test_public_evidence_has_no_paths_or_candidates(self):
        raw = (ROOT / "site/data/research-study.json").read_text()
        self.assertNotIn("/Users/", raw)
        self.assertNotIn("26124", raw)

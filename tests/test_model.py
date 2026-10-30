"""模型的标准库单元测试：不改原始数据，临时输入均在系统临时目录。"""
import contextlib
import csv
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import tempfile
import unittest

MODULE_FILE = Path(os.environ.get("MODEL_MODULE_FILE", Path(__file__).resolve().parents[1] / "skills/superlotto/scripts/model.py"))
SPEC = importlib.util.spec_from_file_location("model_under_test", MODULE_FILE)
assert SPEC is not None and SPEC.loader is not None
model = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model)


def records():
    return [
        {"id": "26001", "left": (1, 2, 3, 20, 35), "right": (1, 12), "date": "2026-01-01"},
        {"id": "26002", "left": (4, 5, 7, 22, 30), "right": (2, 11), "date": "2026-01-03"},
        {"id": "26003", "left": (6, 8, 13, 17, 31), "right": (4, 9), "date": "2026-01-05"},
    ]


def write_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["No.", "L1", "L2", "L3", "L4", "L5", "R1", "R2", "Date"])
        for row in rows:
            writer.writerow([row["id"], *row["left"], *row["right"], row["date"]])


class FeatureTests(unittest.TestCase):
    def test_manual_features(self):
        actual = model.features((1, 2, 3, 20, 35), 35, (1, 4, 5, 20, 32))
        self.assertEqual(actual, {"odd": 3, "even": 2, "small": 3, "large": 2,
                                  "sum": 61, "span": 34, "adjacent_pairs": 2,
                                  "max_run": 3, "repeat_previous": 2})

    def test_size_boundary(self):
        self.assertEqual(model.features((17, 18), 35)["small"], 1)
        self.assertEqual(model.features((6, 7), 12)["small"], 1)
        self.assertEqual(model.features((6, 7), 12)["adjacent_pairs"], 1)
        self.assertEqual(model.features((2, 9), 12)["max_run"], 1)

    def test_invalid_features(self):
        for nums in ((1, 1), (0, 12), (1, 13), (True, 2), ()):
            with self.assertRaises(ValueError):
                model.features(nums, 12)

    def test_gap_uses_last_occurrence_and_all_history(self):
        h = model.heat_summary([(1, 2), (3, 4), (1, 5)], 12, 2, window=1)
        self.assertEqual(h[1]["gap"], 0)
        self.assertEqual(h[2]["gap"], 2)
        self.assertEqual(h[2]["count"], 0)
        self.assertFalse(h[2]["gap_censored"])
        self.assertEqual(h[6]["gap"], 3)
        self.assertTrue(h[6]["gap_censored"])

    def test_heat_threshold_and_small_sample_denominator(self):
        h = model.heat_summary([(1, 2)] * 12, 12, 2, window=100)
        self.assertEqual(h[1]["window"], 12)
        self.assertEqual(h[1]["count"], 12)
        self.assertEqual(h[1]["rate"], 1)
        self.assertEqual(h[1]["expected"], 2)
        self.assertAlmostEqual(h[1]["sd"], math.sqrt(12 / 6 * 5 / 6))
        self.assertEqual(h[1]["label"], "hot")
        self.assertEqual(h[3]["label"], "cold")
        with self.assertRaises(ValueError):
            model.heat_summary([], 12, 2)
        with self.assertRaises(ValueError):
            model.heat_summary([(1, 2)], 12, 2, window=0)


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "data.csv"

    def test_preserves_leading_zero_and_iso(self):
        data = records()
        data[0]["id"] = "07001"
        data[0]["date"] = "2007-05-30T00:00:00.000Z"
        write_csv(self.path, data)
        actual, audit = model.load_data(self.path)
        self.assertEqual(actual[0]["id"], "07001")
        self.assertEqual(audit["iso_timestamp_rows"], 1)
        self.assertEqual(len(audit["source_sha256"]), 64)

    def test_duplicate_full_sets_are_not_deleted(self):
        data = records()
        data[2]["left"], data[2]["right"] = data[0]["left"], data[0]["right"]
        write_csv(self.path, data)
        actual, audit = model.load_data(self.path)
        self.assertEqual(len(actual), 3)
        self.assertEqual(audit["duplicate_full_sets"][0]["ids"], ["26001", "26003"])

    def test_duplicate_id_fails(self):
        data = records()
        data[1]["id"] = data[0]["id"]
        write_csv(self.path, data)
        with self.assertRaisesRegex(ValueError, "期号重复"):
            model.load_data(self.path)

    def test_invalid_period_and_year_mismatch_fail(self):
        for identity, value in (("26000", "2026-01-01"), ("26001", "2000-01-01"),
                                ("２６００１", "2026-01-01")):
            with self.subTest(identity=identity, date=value):
                data = records()
                data[0]["id"], data[0]["date"] = identity, value
                write_csv(self.path, data)
                with self.assertRaises(ValueError):
                    model.load_data(self.path)

    def test_invalid_rows_fail(self):
        cases = [("left", (1, 2, 3, 4, 36)), ("right", (1, 1)),
                 ("date", "not-a-date"), ("date", "2025-01-01"),
                 ("left", (2, 1, 3, 4, 5))]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                data = records()
                data[1][key] = value
                write_csv(self.path, data)
                with self.assertRaises(ValueError):
                    model.load_data(self.path)

    def test_empty_data_never_uses_default_sample(self):
        write_csv(self.path, [])
        with self.assertRaisesRegex(ValueError, "没有历史"):
            model.load_data(self.path)

    def test_cutoff_and_cli_no_future_leak(self):
        before, audit = model.select_history(records(), "26003")
        self.assertEqual(len(before), 2)
        self.assertEqual(audit["excluded_future"], 1)
        data = records()
        write_csv(self.path, data)
        buf = io.StringIO()
        args = ["--data", str(self.path), "--target", "26003", "--mode", "coverage"]
        with contextlib.redirect_stdout(buf):
            self.assertEqual(model.main(args), 0)
        first = json.loads(buf.getvalue())
        data[-1]["left"], data[-1]["right"] = (20, 21, 22, 23, 24), (5, 8)
        write_csv(self.path, data)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            model.main(args)
        changed = json.loads(buf.getvalue())
        self.assertEqual(first["groups"], changed["groups"])
        self.assertEqual(first["heat"], changed["heat"])
        self.assertNotEqual(first["audit"]["source_sha256"], changed["audit"]["source_sha256"])
        self.assertEqual(first["cutoff"]["training_last_id"], "26002")


class PortfolioTests(unittest.TestCase):
    def test_uniform_deterministic_and_legal(self):
        a = model.generate_portfolio(records(), seed=9, groups=5)
        self.assertEqual(a, model.generate_portfolio(records(), seed=9, groups=5))
        complete = set()
        for row in a["groups"]:
            self.assertEqual(len(set(row["left"])), 5)
            self.assertEqual(len(set(row["right"])), 2)
            self.assertTrue(1 <= min(row["left"]) <= max(row["left"]) <= 35)
            self.assertTrue(1 <= min(row["right"]) <= max(row["right"]) <= 12)
            complete.add(tuple(row["left"] + row["right"]))
        self.assertEqual(len(complete), 5)
        self.assertEqual(a["joint_probability"], 5 / 21425712)
        self.assertEqual(a["prediction_gate"], "CLOSED")
        self.assertFalse(a["predictive_advantage_claim"])
        self.assertEqual(a["probability_assumption"], "uniform independent draws")

    def test_coverage_disjoint_and_deterministic(self):
        a = model.generate_portfolio(records(), seed=10, groups=5, mode="coverage")
        self.assertEqual(a, model.generate_portfolio(records(), seed=10, groups=5, mode="coverage"))
        self.assertEqual(a["coverage"]["left_count"], 25)
        self.assertEqual(a["coverage"]["right_count"], 10)
        self.assertEqual(a["overlap"]["max_left"], 0)
        self.assertEqual(a["overlap"]["max_right"], 0)
        self.assertEqual(a["candidate_partitions"], 256)
        self.assertEqual(a["diversity_definition"]["heat_weight"], 0)
        self.assertEqual(a["diversity_definition"]["hard_shape_filters"], [])
        self.assertIn("不构成购彩建议", a["warning"])

    def test_limits_and_single_group(self):
        for groups in (0, -1, True, 7):
            with self.assertRaises(ValueError):
                model.generate_portfolio(records(), groups=groups, mode="coverage")
        one = model.generate_portfolio(records(), groups=1, mode="coverage")
        self.assertEqual(one["overlap"]["max_left"], 0)
        self.assertEqual(one["joint_probability"], 1 / 21425712)
        six = model.generate_portfolio(records(), groups=6, mode="coverage")
        self.assertEqual(six["coverage"]["right_count"], 12)

    def test_excludes_existing_full_set_only(self):
        a = model.generate_portfolio(records(), seed=5, groups=1)
        existing = {"id": "26004", "left": tuple(a["groups"][0]["left"]),
                    "right": tuple(a["groups"][0]["right"]), "date": "2026-01-07"}
        b = model.generate_portfolio(records() + [existing], seed=5, groups=1)
        self.assertNotEqual(a["groups"][0]["left"] + a["groups"][0]["right"],
                            b["groups"][0]["left"] + b["groups"][0]["right"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

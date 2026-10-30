"""集成验证仅使用合成数据和mock网络，不把真实个人文件打包。"""
import contextlib
import csv
from datetime import date, timedelta
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/superlotto/scripts"))
import run_skill
import run_research


def synthetic_csv(path):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["No.", "L1", "L2", "L3", "L4", "L5", "R1", "R2", "Date"])
        writer.writerow(["26001", 1, 4, 10, 22, 30, 2, 9, "2026-01-01"])
        writer.writerow(["26002", 3, 8, 11, 23, 31, 4, 10, "2026-01-03"])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_local_cli_and_atomic_output(self):
        source, output = self.root / "input.csv", self.root / "result.json"
        synthetic_csv(source)
        before = source.read_bytes()
        capture = io.StringIO()
        with contextlib.redirect_stdout(capture):
            code = run_skill.main(["--data", str(source), "--target", "26003", "--output", str(output)])
        self.assertEqual(code, 0)
        result = json.loads(output.read_text())
        self.assertEqual(result, json.loads(capture.getvalue()))
        self.assertEqual(result["cutoff"]["training_last_id"], "26002")
        self.assertTrue(result["data_quality"]["target_predecessor_present"])
        self.assertTrue(result["data_quality"]["warnings"])
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(result["display_name"], "大乐透选号分析")

    def test_missing_data_acquisition_then_model(self):
        source = self.root / "missing.csv"
        def acquire(path, target=None):
            self.assertEqual(target, "26003")
            synthetic_csv(path)
            return {"source": "test double"}
        with patch.object(run_skill, "ensure_data", side_effect=acquire):
            result = run_skill.execute(source, "26003", 0, 5, "coverage")
        self.assertEqual(result["coverage"]["left_count"], 25)

    def test_invalid_local_file_not_replaced(self):
        source = self.root / "invalid.csv"
        source.write_text("bad schema\n")
        with self.assertRaises(ValueError):
            run_skill.execute(source, "26003", 1, 5, "coverage")
        self.assertEqual(source.read_text(), "bad schema\n")

    def test_stale_and_gap_warning(self):
        records = [{"id": "26001"}, {"id": "26004"}]
        quality = run_skill.data_quality(records, "26006")
        self.assertFalse(quality["target_predecessor_present"])
        self.assertEqual(quality["within_year_gaps"], [{"after": "26001", "before": "26004"}])
        self.assertFalse(quality["complete_history_verified"])

    def test_existing_output_and_bad_target_stop_before_fetch(self):
        output = self.root / "output.json"
        output.write_text("preserve")
        for args in (["--target", "26003", "--output", str(output)], ["--target", "26000"], ["--target", "23001"], ["--target", "22099"],
                     ["--target", "26003", "--groups", "7"]):
            with self.subTest(args=args), patch.object(run_skill, "ensure_data") as fetch:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    run_skill.main(args)
                fetch.assert_not_called()
        self.assertEqual(output.read_text(), "preserve")

    def test_writer_does_not_overwrite(self):
        output = self.root / "existing.json"
        output.write_text("original")
        with self.assertRaises(FileExistsError):
            run_skill.write_new_json(output, "replacement")
        self.assertEqual(output.read_text(), "original")
        self.assertEqual(len(list(self.root.iterdir())), 1)


class ResearchRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input.csv"

    def write_history(self, count=200):
        with self.source.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(["No.", "L1", "L2", "L3", "L4", "L5", "R1", "R2", "Date"])
            # 旧年记录仍参与源审计，但不能填补研究的200期门槛。
            writer.writerow(["22001", 1, 2, 3, 4, 5, 1, 2, "2022-01-01"])
            for index in range(count):
                year, period = 2023 + index // 150, index % 150 + 1
                left = sorted({(index + n * 6) % 35 + 1 for n in range(5)})
                right = sorted({index % 12 + 1, (index + 5) % 12 + 1})
                day = date(year, 1, 1) + timedelta(days=period - 1)
                writer.writerow([f"{year % 100:02}{period:03}", *left, *right, day.isoformat()])
            writer.writerow(["25001", 2, 3, 4, 5, 6, 2, 3, "2025-01-01"])

    def test_real_research_cli_is_reproducible_and_does_not_modify_input(self):
        self.write_history()
        original = self.source.read_bytes()
        output = self.root / "research.json"
        with patch.object(run_research, "ensure_data", wraps=run_research.ensure_data) as acquire:
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = run_research.main(["--data", str(self.source), "--target", "25001",
                                          "--pool-size", "5+5", "--output", str(output)])
        self.assertEqual(code, 0)
        result = json.loads(output.read_text())
        self.assertEqual(result, json.loads(stdout.getvalue()))
        self.assertFalse(result["data_acquisition"]["downloaded"])
        self.assertEqual(acquire.call_count, 1)
        self.assertEqual(result["history"]["rows"], 200)
        self.assertEqual(result["history"]["first_id"], "23001")
        self.assertEqual(result["history"]["last_id"], "24050")
        self.assertEqual(result["learning"]["rows"], 100)
        self.assertEqual(result["pool"]["basic_combinations"], 10)
        self.assertEqual(result["pool"]["basic_cost_yuan"], 20)
        self.assertEqual(result["prediction_gate"], "CLOSED")
        self.assertEqual(set(result["code_sha256"]), {"model.py", "research.py", "conditional_core.py"})
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(run_research.execute(self.source, "25001", "5+5"), result)

    def test_bad_requests_stop_before_acquisition(self):
        existing = self.root / "existing.json"
        existing.write_text("preserve")
        for args in (["--target", "23001"], ["--target", "22099"], ["--target", "25000"],
                     ["--target", "2500"], ["--target", "２５００１"],
                     ["--target", "25001", "--pool-size", "35+12"],
                     ["--target", "25001", "--output", str(existing)],
                     ["--target", "25001", "--data", str(self.source), "--output", str(self.source)]):
            with self.subTest(args=args), patch.object(run_research, "ensure_data") as acquire:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    run_research.main(args)
                self.assertEqual(caught.exception.code, 2)
                acquire.assert_not_called()
        self.assertEqual(existing.read_text(), "preserve")
        self.assertFalse(self.source.exists())
        for target, size in (("23001", "5+2"), ("25001", "bad")):
            with patch.object(run_research, "ensure_data") as acquire, self.assertRaises(ValueError):
                run_research.execute(self.source, target, size)
            acquire.assert_not_called()

    def test_missing_input_acquired_then_research_and_invalid_not_repaired(self):
        def acquire(path, target=None):
            self.assertEqual(path, self.source)
            self.assertEqual(target, "25001")
            self.write_history()
            return {"source": "test double", "downloaded": True}
        with patch.object(run_research, "ensure_data", side_effect=acquire):
            result = run_research.execute(self.source, "25001", "7+3")
        self.assertTrue(result["data_acquisition"]["downloaded"])
        self.assertEqual(result["pool"]["basic_combinations"], 63)
        self.source.write_text("bad schema\n")
        with self.assertRaises(ValueError):
            run_research.execute(self.source, "25001")
        self.assertEqual(self.source.read_text(), "bad schema\n")

    def test_insufficient_history_writes_no_candidate_and_no_fallback(self):
        self.write_history(count=199)
        output = self.root / "no-result.json"
        original = self.source.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            run_research.main(["--data", str(self.source), "--target", "25001", "--output", str(output)])
        self.assertEqual(caught.exception.code, 2)
        self.assertFalse(output.exists())
        self.assertEqual(self.source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()

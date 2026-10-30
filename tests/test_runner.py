"""集成验证仅使用合成数据和mock网络，不把真实个人文件打包。"""
import contextlib
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/superlotto/scripts"))
import run_skill


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
            result = run_skill.execute(source, "26003", 26124, 5, "coverage")
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
        for args in (["--target", "26003", "--output", str(output)], ["--target", "26000"],
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


if __name__ == "__main__":
    unittest.main()

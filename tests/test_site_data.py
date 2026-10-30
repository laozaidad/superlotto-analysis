"""静态网页快照只复用既有算法，并隔离本地路径和旧年数据。"""
import contextlib
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_site_data", ROOT / "scripts/build_site_data.py")
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class SiteDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "public.csv"
        self.rows = [
            ["12001", 1, 2, 3, 4, 5, 1, 2, "2012-01-01"],
            ["13001", 6, 7, 8, 9, 10, 3, 4, "2013-01-02"],
            ["13002", 6, 12, 17, 29, 30, 7, 11, "2013-01-05"],
            ["13003", 6, 12, 17, 29, 30, 7, 11, "2013-01-07"],
        ]
        self.write_csv()

    def write_csv(self):
        with self.data.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["No.", "L1", "L2", "L3", "L4", "L5", "R1", "R2", "Date"])
            writer.writerows(self.rows)

    def metadata(self, **overrides):
        metadata = {
            "source": "500.com", "sha256": hashlib.sha256(self.data.read_bytes()).hexdigest(),
            "source_path": "/private/never-publish", "warnings": ["do-not-copy-private-text"],
            "source_urls": ["https://example.invalid/?token=do-not-copy"],
            "retrieved_at_utc": "2026-10-30T00:00:00+00:00",
        }
        metadata.update(overrides)
        self.data.with_suffix(".csv.metadata.json").write_text(json.dumps(metadata))

    def test_schema_scope_and_real_model_reuse(self):
        result = builder.build_snapshot(self.data, generated_at="2026-10-30T00:00:00+00:00")
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["history"]["rows"], 3)
        self.assertEqual(result["history"]["excluded_before_start"], 1)
        self.assertEqual(result["history"]["first_id"], "13001")
        records, _ = builder.model.load_data(self.data)
        history = [r for r in records if builder.model.within_history_scope(r)]
        for mode in ("coverage", "uniform"):
            self.assertEqual(result["portfolios"][mode], builder.model.generate_portfolio(
                history, seed=0, groups=5, mode=mode))
        self.assertEqual([r["id"] for r in result["recent_draws"]], ["13003", "13002", "13001"])
        self.assertNotIn("target", result)

    def test_distribution_denominators_and_adjacency(self):
        result = builder.build_snapshot(self.data)
        for zone in ("left", "right"):
            distribution = result["distributions"][zone]
            for metric in builder.METRICS:
                expected = 2 if metric == "repeat_previous" else 3
                self.assertEqual(sum(item["count"] for item in distribution[metric]), expected)
                self.assertEqual(distribution["sample_sizes"][metric], expected)
        self.assertEqual(result["distributions"]["left"]["repeat_previous"],
                         [{"value": 1, "count": 1}, {"value": 5, "count": 1}])
        self.assertEqual(result["distributions"]["left"]["adjacent_pairs"],
                         [{"value": 1, "count": 2}, {"value": 4, "count": 1}])

    def test_public_source_allowlist_and_no_local_paths(self):
        self.metadata()
        result = builder.build_snapshot(self.data)
        raw = json.dumps(result, ensure_ascii=False)
        for secret in (str(self.data), self.temp.name, "/private/", "do-not-copy", "source_path"):
            self.assertNotIn(secret, raw)
        self.assertEqual(result["source"]["url"], builder.PUBLIC_SOURCE_URL)
        self.assertFalse(result["source"]["complete"])
        self.assertTrue(result["source"]["provenance_hash_matches"])
        self.assertTrue(any("重复" in item for item in result["source"]["warnings"]))

    def test_no_sidecar_does_not_assert_source(self):
        result = builder.build_snapshot(self.data)
        self.assertIsNone(result["source"]["url"])
        self.assertFalse(result["source"]["provenance_hash_matches"])
        self.assertTrue(any("来源侧车" in item for item in result["source"]["warnings"]))

    def test_mismatching_sidecar_rejected(self):
        self.metadata(sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "SHA-256不匹配"):
            builder.build_snapshot(self.data)

    def test_old_history_does_not_influence_statistics_or_portfolios(self):
        before = builder.build_snapshot(self.data)
        self.rows = self.rows[1:]
        self.write_csv()
        after = builder.build_snapshot(self.data)
        for field in ("portfolios", "distributions", "recent_draws"):
            self.assertEqual(before[field], after[field])
        self.rows = [["12001", 1, 2, 3, 4, 5, 1, 2, "2012-01-01"]]
        self.write_csv()
        with self.assertRaisesRegex(ValueError, "没有有效历史"):
            builder.build_snapshot(self.data)

    def test_same_input_and_metadata_are_not_overwritten(self):
        self.metadata()
        original = self.data.read_bytes()
        for output in (self.data, self.data.with_suffix(".csv.metadata.json")):
            with self.assertRaisesRegex(ValueError, "不能覆盖"):
                builder.write_snapshot(self.data, output)
        self.assertEqual(self.data.read_bytes(), original)

    def test_cli_and_atomic_json(self):
        output = Path(self.temp.name) / "site/data/snapshot.json"
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            status = builder.main(["--data", str(self.data), "--output", str(output)])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout.getvalue())["rows"], 3)
        result = json.loads(output.read_text())
        self.assertEqual(result["schema_version"], 1)
        original = output.read_bytes()
        with mock.patch.object(builder.os, "replace", side_effect=OSError("write failed")):
            with self.assertRaisesRegex(OSError, "write failed"):
                builder.write_snapshot(self.data, output)
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(list(output.parent.glob(".snapshot-*")), [])

    def test_recent_draws_are_limited_and_latest_first(self):
        self.rows = [[f"130{i:02d}", 1, 2, 3, 4, 5, 1, 2, f"2013-01-{i:02d}"] for i in range(1, 13)]
        self.write_csv()
        result = builder.build_snapshot(self.data)
        self.assertEqual(len(result["recent_draws"]), 8)
        self.assertEqual(result["recent_draws"][0]["id"], "13012")
        self.assertEqual(result["recent_draws"][-1]["id"], "13005")

    def test_runtime_bytes_hashes_floor_and_source_unchanged(self):
        self.metadata()
        original = self.data.read_bytes()
        source_metadata = self.data.with_suffix(".csv.metadata.json").read_bytes()
        output = Path(self.temp.name) / "site/snapshot.json"
        runtime = Path(self.temp.name) / "site/runtime"
        snapshot = builder.write_snapshot(self.data, output, runtime)
        manifest = json.loads((runtime / "manifest.json").read_text())
        self.assertEqual((runtime / "model.py").read_bytes(), builder.MODEL_FILE.read_bytes())
        self.assertEqual(manifest["model_sha256"], hashlib.sha256(builder.MODEL_FILE.read_bytes()).hexdigest())
        self.assertEqual(manifest["data_sha256"], hashlib.sha256((runtime / "history.csv").read_bytes()).hexdigest())
        records, audit = builder.model.load_data(runtime / "history.csv")
        self.assertEqual(audit["rows"], 3)
        self.assertEqual([row["id"] for row in records], ["13001", "13002", "13003"])
        self.assertEqual(manifest["history"]["first_id"], "13001")
        self.assertEqual(manifest["source"], snapshot["source"])
        for item in runtime.iterdir():
            self.assertNotIn(self.temp.name, item.read_text())
            self.assertNotIn("/private/", item.read_text())
        self.assertEqual(self.data.read_bytes(), original)
        self.assertEqual(self.data.with_suffix(".csv.metadata.json").read_bytes(), source_metadata)

    def test_runtime_conflicts_do_not_change_source_or_model(self):
        model_before = builder.MODEL_FILE.read_bytes()
        output = Path(self.temp.name) / "snapshot.json"
        with self.assertRaisesRegex(ValueError, "不能覆盖"):
            builder.write_snapshot(self.data, output, builder.MODEL_FILE.parent)
        self.assertEqual(builder.MODEL_FILE.read_bytes(), model_before)
        runtime = Path(self.temp.name) / "runtime"
        with self.assertRaisesRegex(ValueError, "不能覆盖"):
            builder.write_snapshot(self.data, runtime / "manifest.json", runtime)
        self.assertFalse(output.exists())
        original = self.data.read_bytes()
        data_at_runtime_path = Path(self.temp.name) / "history.csv"
        data_at_runtime_path.write_bytes(original)
        with self.assertRaisesRegex(ValueError, "不能覆盖"):
            builder.write_snapshot(data_at_runtime_path, output, Path(self.temp.name))
        self.assertEqual(data_at_runtime_path.read_bytes(), original)

    def test_runtime_cli_repeat_builds_keep_hashes(self):
        output = Path(self.temp.name) / "site/snapshot.json"
        runtime = Path(self.temp.name) / "site/runtime"
        arguments = ["--data", str(self.data), "--output", str(output), "--runtime-dir", str(runtime)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(builder.main(arguments), 0)
        first = {name: (runtime / name).read_bytes() for name in ("model.py", "history.csv", "manifest.json")}
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(builder.main(arguments), 0)
        self.assertEqual(first, {name: (runtime / name).read_bytes() for name in first})

    def test_runtime_guard_detects_data_change_during_build(self):
        snapshot = builder.build_snapshot(self.data)
        self.rows.pop()
        self.write_csv()
        with self.assertRaisesRegex(ValueError, "构建过程中源CSV发生变化"):
            builder.runtime_payloads(self.data, snapshot)


if __name__ == "__main__":
    unittest.main()

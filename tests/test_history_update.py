"""定时公共历史更新只允许追加，候选失败时不破坏已发布数据。"""
import contextlib
from datetime import date
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("update_history", ROOT / "scripts/update_history.py")
assert SPEC is not None and SPEC.loader is not None
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


class HistoryUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.site = self.root / "site"
        self.base = self.root / "baseline.csv"
        self.source = self.root / "candidate.csv"
        self.today = date(2026, 10, 30)
        self.rows: list[dict[str, Any]] = [
            {"id": "23001", "left": [1, 2, 3, 4, 5], "right": [1, 2], "date": "2023-01-02"},
            {"id": "23002", "left": [6, 7, 8, 9, 10], "right": [3, 4], "date": "2023-01-05"},
            {"id": "23003", "left": [11, 12, 13, 14, 15], "right": [5, 6], "date": "2023-01-07"},
        ]
        self.extra = {"id": "23004", "left": [16, 17, 18, 19, 20], "right": [7, 8], "date": "2023-01-09"}
        self.write_source(self.base, self.rows)
        updater.builder.write_snapshot(self.base, self.site / "data/snapshot.json", self.site / "runtime")
        (self.site / "index.html").write_text("do not edit layout")
        (self.site / "data/research-study.json").write_text('{"frozen":true}')
        (self.site / "data/research-evidence.json").write_text('{"frozen":true}')
        self.private = self.root / "numbers.csv"
        self.private.write_bytes(b"private source must not be touched")
        self.write_source(self.source, self.rows + [self.extra])

    def write_source(self, path, rows, **metadata):
        path.write_bytes(updater.fetcher._csv_bytes(rows))
        self.write_metadata(path, **metadata)

    def write_metadata(self, path=None, **overrides):
        path = path or self.source
        value = {
            "source": "500.com", "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "retrieved_at_utc": "2026-10-30T00:00:00+00:00",
            "source_path": "/private/not-for-publication", "warnings": ["not-for-publication"],
        }
        value.update(overrides)
        path.with_suffix(path.suffix + ".metadata.json").write_text(json.dumps(value))

    def site_state(self):
        return {str(p.relative_to(self.site)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.site.rglob("*") if p.is_file()}

    def update(self):
        return updater.update_site(self.site, self.source, today=self.today)

    def reject_unchanged(self, pattern):
        before = self.site_state()
        with self.assertRaisesRegex((ValueError, OSError, RuntimeError), pattern):
            self.update()
        self.assertEqual(self.site_state(), before)
        self.assertEqual(list(self.root.glob(".history-update-*")), [])

    def test_valid_append_and_runtime_hashes(self):
        source_before = self.source.read_bytes()
        metadata_before = self.source.with_suffix(".csv.metadata.json").read_bytes()
        private_before = self.private.read_bytes()
        old = self.site_state()
        result = self.update()
        self.assertEqual(result["status"], "updated")
        self.assertEqual(result["history"], {"rows": 4, "first_id": "23001", "last_id": "23004"})
        self.assertEqual(result["added_rows"], 1)
        manifest = json.loads((self.site / "runtime/manifest.json").read_text())
        self.assertEqual(result["data_sha256"], manifest["data_sha256"])
        records, _ = updater._inspect_site(self.site, self.today)
        self.assertEqual(len(records), 4)
        self.assertEqual(manifest["source"]["url"], updater.builder.PUBLIC_SOURCE_URL)
        for key in ["index.html", "data/research-study.json", "data/research-evidence.json"]:
            self.assertEqual(self.site_state()[key], old[key])
        for name in updater.PUBLIC_FILES:
            self.assertNotIn("not-for-publication", (self.site / name).read_text())
            self.assertNotIn(str(self.root), (self.site / name).read_text())
        self.assertEqual(self.source.read_bytes(), source_before)
        self.assertEqual(self.source.with_suffix(".csv.metadata.json").read_bytes(), metadata_before)
        self.assertEqual(self.private.read_bytes(), private_before)
        self.assertEqual(list(self.root.glob(".history-update-*")), [])

    def test_no_new_rows_keeps_all_bytes_and_mtimes(self):
        self.write_source(self.source, self.rows)
        before = self.site_state()
        with mock.patch.object(updater.builder, "write_snapshot") as build:
            result = self.update()
        build.assert_not_called()
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(result["added_rows"], 0)
        self.assertEqual(self.site_state(), before)

    def test_equivalent_csv_format_and_iso_midnight_do_not_trigger_update(self):
        rows = [{**row, "date": row["date"] + "T00:00:00.000Z"} for row in self.rows]
        self.write_source(self.source, rows)
        raw = self.source.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        self.source.write_text(raw)
        self.write_metadata()
        before = self.site_state()
        self.assertEqual(self.update()["status"], "unchanged")
        self.assertEqual(self.site_state(), before)

    def test_deleted_existing_draw_is_rejected(self):
        self.write_source(self.source, self.rows[:2])
        self.reject_unchanged("删除")

    def test_changed_existing_numbers_are_rejected(self):
        changed = [{**self.rows[0], "right": [1, 3]}, *self.rows[1:], self.extra]
        self.write_source(self.source, changed)
        self.reject_unchanged("修改或删除")

    def test_changed_existing_date_is_rejected(self):
        changed = [{**self.rows[0], "date": "2023-01-03"}, *self.rows[1:], self.extra]
        self.write_source(self.source, changed)
        self.reject_unchanged("修改或删除")

    def test_missing_same_year_draw_is_rejected(self):
        self.write_source(self.source, self.rows + [{**self.extra, "id": "23005"}])
        self.reject_unchanged("缺口")

    def test_missing_start_and_old_scope_are_rejected(self):
        self.write_source(self.source, self.rows[1:])
        self.reject_unchanged("23001")
        self.write_source(self.source, [{**self.rows[0], "id": "22001", "date": "2022-01-02"}, *self.rows])
        self.reject_unchanged("23001")

    def test_new_year_requires_001_and_no_whole_year_gap(self):
        for identity, drawn in (("24002", "2024-01-02"), ("25001", "2025-01-02")):
            with self.subTest(identity=identity):
                self.write_source(self.source, self.rows + [{**self.extra, "id": identity, "date": drawn}])
                self.reject_unchanged("跨年缺口")
        self.write_source(self.source, self.rows + [{**self.extra, "id": "24001", "date": "2024-01-02"}])
        self.assertEqual(self.update()["status"], "updated")

    def test_future_date_is_rejected(self):
        self.today = date(2023, 1, 8)
        self.reject_unchanged("未来日期")

    def test_invalid_or_duplicate_draw_rejected(self):
        self.write_source(self.source, self.rows + [{**self.extra, "left": [1, 2, 3, 4, 36]}])
        self.reject_unchanged("35")
        self.write_source(self.source, self.rows + [self.rows[-1]])
        self.reject_unchanged("期号重复")

    def test_bad_missing_and_wrong_source_metadata_rejected(self):
        for overrides, pattern in [({"source": "offline_html"}, "500.com"),
                                   ({"sha256": "0" * 64}, "SHA-256")]:
            with self.subTest(overrides=overrides):
                self.write_metadata(**overrides)
                self.reject_unchanged(pattern)
        metadata = self.source.with_suffix(".csv.metadata.json")
        metadata.write_text("not json")
        self.reject_unchanged("Expecting")
        metadata.write_bytes(b"x" * (1024 * 1024 + 1))
        self.reject_unchanged("大小上限")
        metadata.unlink()
        self.reject_unchanged("普通文件")

    def test_corrupt_published_manifest_stops_before_fetch(self):
        path = self.site / "runtime/manifest.json"
        manifest = json.loads(path.read_text())
        manifest["data_sha256"] = "0" * 64
        path.write_text(json.dumps(manifest))
        before = self.site_state()
        with mock.patch.object(updater.fetcher, "fetch_data") as fetch:
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                updater.update_site(self.site)
        fetch.assert_not_called()
        self.assertEqual(self.site_state(), before)

    def test_corrupt_published_snapshot_and_model_are_rejected(self):
        path = self.site / "data/snapshot.json"
        original = path.read_bytes()
        snapshot = json.loads(original)
        snapshot["history"]["last_id"] = "23099"
        path.write_text(json.dumps(snapshot))
        self.reject_unchanged("快照与运行清单")
        path.write_bytes(original)
        (self.site / "runtime/model.py").write_text("# changed")
        self.reject_unchanged("SHA-256")

    def test_default_fetch_uses_23001_and_temporary_output(self):
        observed = []

        def fetch(output, *, start):
            observed.append((output, start))
            self.write_source(output, self.rows + [self.extra])

        with mock.patch.object(updater.fetcher, "fetch_data", side_effect=fetch):
            result = updater.update_site(self.site, today=self.today)
        self.assertEqual(result["status"], "updated")
        self.assertEqual(observed[0][1], "23001")
        self.assertNotIn(self.site, observed[0][0].parents)
        self.assertFalse(observed[0][0].exists())

    def test_network_failure_preserves_every_file(self):
        before = self.site_state()
        with mock.patch.object(updater.fetcher, "fetch_data", side_effect=updater.fetcher.FetchError("network failed")):
            with self.assertRaisesRegex(updater.fetcher.FetchError, "network failed"):
                updater.update_site(self.site)
        self.assertEqual(self.site_state(), before)
        self.assertEqual(list(self.root.glob(".history-update-*")), [])

    def test_build_failure_preserves_every_file(self):
        with mock.patch.object(updater.builder, "write_snapshot", side_effect=OSError("stage failed")):
            self.reject_unchanged("stage failed")

    def test_partial_publish_failure_restores_bytes_and_mtimes(self):
        original_replace = updater._replace
        attempts = []

        def fail_second(source, destination):
            attempts.append(destination)
            if len(attempts) == 2:
                raise OSError("publish failed")
            original_replace(source, destination)

        with mock.patch.object(updater, "_replace", side_effect=fail_second):
            self.reject_unchanged("publish failed")
        self.assertEqual(len(attempts), 2)

    def test_failed_rollback_keeps_recovery_backup_and_reports_failure(self):
        original_replace = updater._replace
        attempts = []
        before = self.site_state()

        def fail_second(source, destination):
            attempts.append(destination)
            if len(attempts) == 2:
                raise OSError("publish failed")
            original_replace(source, destination)

        with mock.patch.object(updater, "_replace", side_effect=fail_second), \
                mock.patch.object(updater, "_restore", side_effect=OSError("recovery filesystem unavailable")):
            with self.assertRaisesRegex(updater.RecoveryRequired, "保留备份") as raised:
                self.update()
        workspaces = list(self.root.glob(".history-update-*"))
        self.assertEqual(len(workspaces), 1)
        recovery = workspaces[0] / "backup"
        self.assertIn(str(recovery), str(raised.exception))
        for path in recovery.rglob("*"):
            if path.is_file():
                self.assertEqual(path.read_bytes(), before[str(path.relative_to(recovery))][0])
        self.assertIsInstance(raised.exception.__cause__, OSError)

    def test_cli_emits_single_json_and_failures_nonzero(self):
        self.write_source(self.source, self.rows)
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(updater.main(["--site-dir", str(self.site), "--source-csv", str(self.source)]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["status"], "unchanged")
        self.write_metadata(source="unknown")
        before = self.site_state()
        with contextlib.redirect_stdout(io.StringIO()) as stdout, contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as raised:
                updater.main(["--site-dir", str(self.site), "--source-csv", str(self.source)])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("500.com", stderr.getvalue())
        self.assertEqual(self.site_state(), before)

    def test_reject_source_inside_site_and_samefile_alias(self):
        original = self.site_state()
        with self.assertRaisesRegex(ValueError, "发布site"):
            updater.update_site(self.site, self.site / "runtime/history.csv")
        self.assertEqual(self.site_state(), original)
        alias = self.root / "hardlink.csv"
        os.link(self.site / "runtime/history.csv", alias)
        self.write_metadata(alias)
        with self.assertRaisesRegex(ValueError, "同一文件"):
            updater.update_site(self.site, alias)
        self.assertEqual(self.site_state(), original)

    def test_reject_symlink_site_source_and_output(self):
        alias = self.root / "site-link"
        alias.symlink_to(self.site, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            updater.update_site(alias, self.source)
        source_link = self.root / "source-link.csv"
        source_link.symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, "符号链接"):
            updater.update_site(self.site, source_link)
        path = self.site / "runtime/history.csv"
        external = self.root / "external.csv"
        path.rename(external)
        path.symlink_to(external)
        before = external.read_bytes()
        with self.assertRaisesRegex(ValueError, "符号链接"):
            self.update()
        self.assertEqual(external.read_bytes(), before)

    def test_source_modified_during_staging_is_not_published(self):
        original_build = updater.builder.write_snapshot

        def tamper(*args, **kwargs):
            result = original_build(*args, **kwargs)
            self.source.write_bytes(b"externally modified")
            return result

        with mock.patch.object(updater.builder, "write_snapshot", side_effect=tamper):
            self.reject_unchanged("候选源或侧车发生变化")

    def test_concurrent_site_edit_not_overwritten(self):
        original_build = updater.builder.write_snapshot
        manifest = self.site / "runtime/manifest.json"

        def tamper(*args, **kwargs):
            result = original_build(*args, **kwargs)
            manifest.write_bytes(b"external change")
            return result

        before = self.site_state()
        with mock.patch.object(updater.builder, "write_snapshot", side_effect=tamper):
            with self.assertRaisesRegex(ValueError, "并发修改"):
                self.update()
        self.assertEqual(manifest.read_bytes(), b"external change")
        after = self.site_state()
        for name in before.keys() - {"runtime/manifest.json"}:
            self.assertEqual(before[name], after[name])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""只追加经校验的500网公开历史；无新增或失败时保留已发布快照。"""
from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import importlib.util
import json
import os
import shutil
from pathlib import Path
import stat
import tempfile
from types import ModuleType
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (
    "runtime/model.py", "runtime/research.py", "runtime/conditional_core.py",
    "runtime/history.csv", "data/snapshot.json", "runtime/manifest.json",
)
MAX_BYTES = 20 * 1024 * 1024


class RecoveryRequired(RuntimeError):
    """操作系统阻止回滚时保留备份目录，不伪装成安全完成。"""


@contextmanager
def _workspace(parent: Path) -> Iterator[Path]:
    work = Path(tempfile.mkdtemp(prefix=".history-update-", dir=parent))
    keep = False
    try:
        yield work
    except RecoveryRequired:
        keep = True
        raise
    finally:
        if not keep:
            shutil.rmtree(work)


def _module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = _module("history_site_builder", ROOT / "scripts/build_site_data.py")
fetcher = _module("history_fetcher", ROOT / "skills/superlotto/scripts/fetch_data.py")


def _safe_path(path: Path) -> Path:
    """在resolve前检查，拒绝输入、输出或中间目录中的符号链接。"""
    path = path.expanduser().absolute()
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError(f"不接受符号链接路径：{path}")
    return path.resolve()


def _read(path: Path, limit: int = MAX_BYTES) -> bytes:
    path = _safe_path(path)
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"需要已有普通文件：{path}")
    if path.stat().st_size > limit:
        raise ValueError(f"文件超过大小上限：{path}")
    return path.read_bytes()


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _history(records: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """以源日期的日历日比较，允许日期/零点ISO表示差异，不允许改开奖。"""
    if not records or records[0]["id"] != "23001":
        raise ValueError("公共历史必须从23001开始")
    normalized = []
    for row in records:
        drawn = datetime.fromisoformat(row["date"].replace("Z", "+00:00")).date()
        if not builder.model.within_history_scope(row):
            raise ValueError("不接受2023年以前的公共历史")
        if drawn > today:
            raise ValueError(f"拒绝未来日期的开奖：{row['id']}")
        normalized.append({"id": row["id"], "left": tuple(row["left"]),
                           "right": tuple(row["right"]), "date": drawn.isoformat()})
    for previous, current in zip(normalized, normalized[1:]):
        before, after = previous["id"], current["id"]
        if current["date"] <= previous["date"]:
            raise ValueError("开奖日历日期必须严格递增")
        if before[:2] == after[:2]:
            if int(after) != int(before) + 1:
                raise ValueError(f"历史期号有缺口：{before}→{after}")
        elif int(after[:2]) != int(before[:2]) + 1 or after[2:] != "001":
            raise ValueError(f"历史跨年缺口或新年未从001开始：{before}→{after}")
    return normalized


def _inspect_site(site: Path, today: date) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    files = {name: _read(site / name) for name in PUBLIC_FILES}
    manifest = json.loads(files["runtime/manifest.json"])
    snapshot = json.loads(files["data/snapshot.json"])
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("已发布运行清单版本不符")
    for name, key in (("history.csv", "data_sha256"), ("model.py", "model_sha256"),
                      ("research.py", "research_sha256"), ("conditional_core.py", "conditional_core_sha256")):
        if manifest.get(key) != _digest(files[f"runtime/{name}"]):
            raise ValueError(f"已发布{name}与清单SHA-256不匹配")
    records, audit = builder.model.load_data(site / "runtime/history.csv")
    if audit["source_sha256"] != _digest(files["runtime/history.csv"]):
        raise ValueError("读取期间已发布历史发生变化")
    rows = _history(records, today)
    expected = {"rows": len(rows), "first_id": rows[0]["id"], "last_id": rows[-1]["id"],
                "first_date": records[0]["date"], "last_date": records[-1]["date"],
                "history_start_date": "2023-01-01", "history_start_issue": "23001"}
    if manifest.get("history") != expected:
        raise ValueError("已发布清单历史范围与CSV不一致")
    if (not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1
            or not isinstance(snapshot.get("history"), dict)
            or any(snapshot["history"].get(key) != value for key, value in expected.items())
            or snapshot.get("source") != manifest.get("source")):
        raise ValueError("已发布快照与运行清单不一致")
    return rows, files


def _source_copy(source: Path, site: Path, work: Path) -> tuple[Path, dict[Path, bytes]]:
    source = _safe_path(source)
    metadata = _safe_path(source.with_suffix(source.suffix + ".metadata.json"))
    for path in (source, metadata):
        if path == site or site in path.parents:
            raise ValueError("候选源及来源侧车不能位于发布site内或覆盖输出")
        for name in PUBLIC_FILES:
            if path.exists() and os.path.samefile(path, site / name):
                raise ValueError("候选源及来源侧车不能与发布输出为同一文件")
    original = {source: _read(source), metadata: _read(metadata, 1024 * 1024)}
    provenance = json.loads(original[metadata])
    if not isinstance(provenance, dict) or provenance.get("source") != "500.com":
        raise ValueError("候选必须带500.com公开抓取来源侧车，不接受未知或离线HTML来源冒充")
    if provenance.get("sha256") != _digest(original[source]):
        raise ValueError("候选CSV与来源侧车SHA-256不匹配")
    frozen = work / "candidate.csv"
    frozen.write_bytes(original[source])
    frozen.with_suffix(".csv.metadata.json").write_bytes(original[metadata])
    return frozen, original


def _replace(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _restore(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _publish(site: Path, stage: Path, original: dict[str, bytes], work: Path) -> None:
    """先备份全部目标再替换；异常回滚已替换文件并原样抛出，回滚失败显式报告。"""
    changed = [name for name in PUBLIC_FILES if (stage / name).read_bytes() != original[name]]
    backup = work / "backup"
    for name in PUBLIC_FILES:
        path = _safe_path(site / name)
        if _read(path) != original[name]:
            raise ValueError("发布前检测到site被并发修改，未覆盖")
    for name in changed:
        path = site / name
        info = path.stat()
        saved = backup / name
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(original[name])
        os.chmod(saved, stat.S_IMODE(info.st_mode))
        os.utime(saved, ns=(info.st_atime_ns, info.st_mtime_ns))
        os.chmod(stage / name, stat.S_IMODE(info.st_mode))
    replaced: list[str] = []
    try:
        for name in changed:
            _safe_path(site / name)
            _replace(stage / name, site / name)
            replaced.append(name)
    except BaseException as exc:
        errors = []
        for name in reversed(replaced):
            try:
                _restore(backup / name, site / name)
            except OSError as restore_error:
                errors.append(f"{name}: {restore_error}")
        if errors:
            raise RecoveryRequired(f"发布失败且回滚不完整，保留备份于{backup}，请人工恢复：{'; '.join(errors)}") from exc
        raise


def update_site(site_dir: Path, source_csv: Path | None = None, *, today: date | None = None) -> dict[str, Any]:
    site = _safe_path(site_dir)
    if not site.is_dir():
        raise ValueError("site-dir必须为已有独立网站目录")
    day = today or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    existing, original_site = _inspect_site(site, day)
    with _workspace(site.parent) as work:
        if source_csv is None:
            source_csv = work / "download.csv"
            fetcher.fetch_data(source_csv, start="23001")
        frozen, original_source = _source_copy(source_csv, site, work)
        candidate, _ = builder.model.load_data(frozen)
        incoming = _history(candidate, day)
        if len(incoming) < len(existing):
            raise ValueError("候选删除了已发布开奖，保留旧版")
        if incoming[:len(existing)] != existing:
            raise ValueError("候选修改或删除了已发布开奖，需人工核对，保留旧版")
        changed = len(incoming) > len(existing)
        if changed:
            stage = work / "site"
            builder.write_snapshot(frozen, stage / "data/snapshot.json", stage / "runtime")
            staged, _ = _inspect_site(stage, day)
            if staged != incoming:
                raise ValueError("暂存发布数据与候选不一致")
        for path, raw in original_source.items():
            if _read(path) != raw:
                raise ValueError("读取期间候选源或侧车发生变化，未发布")
        if changed:
            _publish(site, stage, original_site, work)
        elif any(_read(site / name) != raw for name, raw in original_site.items()):
            raise ValueError("检查期间已发布site发生变化")
    return {
        "status": "updated" if changed else "unchanged",
        "history": {"rows": len(incoming), "first_id": incoming[0]["id"], "last_id": incoming[-1]["id"]},
        "added_rows": len(incoming) - len(existing),
        "data_sha256": _digest(_read(site / "runtime/history.csv")),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "warnings": ["500网为第三方公开来源；哈希、连续性及追加校验不证明官方准确性或全历史完整。"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", type=Path, default=ROOT / "site", help="已有公共网站目录")
    parser.add_argument("--source-csv", type=Path, help="可选：显式指定公开候选CSV，须有匹配500.com来源侧车")
    args = parser.parse_args(argv)
    try:
        result = update_site(args.site_dir, args.source_csv)
    except (ValueError, OSError, RuntimeError, UnicodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

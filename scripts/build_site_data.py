#!/usr/bin/env python3
"""从明确可公开的CSV构建网页快照及可选运行时；不联网，不导出本地路径。"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODEL_FILE = ROOT / "skills/superlotto/scripts/model.py"
SPEC = importlib.util.spec_from_file_location("site_source_model", MODEL_FILE)
assert SPEC is not None and SPEC.loader is not None
model = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(model)

PUBLIC_SOURCE_URL = "https://datachart.500.com/dlt/history/history.shtml"
METRICS = ("odd", "small", "sum", "span", "adjacent_pairs", "repeat_previous")


def public_source(data: Path, audit: dict[str, Any]) -> dict[str, Any]:
    """只输出白名单字段；侧车匹配不等于对第三方来源做了官方认证。"""
    source: dict[str, Any] = {
        "url": None,
        "sha256": audit["source_sha256"],
        "complete": False,
        "provenance_hash_matches": False,
        "warnings": [
            "静态快照，不是实时开奖数据；第三方数据未与官方开奖源交叉核验。",
            "仅验证输入结构与范围，不保证每年末期或全历史无缺漏。",
        ] + audit["warnings"],
    }
    metadata_path = data.with_suffix(data.suffix + ".metadata.json")
    if not metadata_path.is_file():
        source["warnings"].append("输入缺少抓取来源侧车，网页不标注已核验的数据来源。")
        return source
    if metadata_path.stat().st_size > 1024 * 1024:
        raise ValueError("来源侧车超过1MB上限")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or metadata.get("sha256") != audit["source_sha256"]:
        raise ValueError("来源侧车与CSV的SHA-256不匹配，拒绝发布来源错误的快照")
    source["provenance_hash_matches"] = True
    if metadata.get("source") == "500.com":
        # 不复制可含任意文本、身份信息、路径或查询参数的原始侧车字段。
        source["url"] = PUBLIC_SOURCE_URL
        source["warnings"].append("来源侧车与CSV哈希匹配，但不构成来源真实性的独立认证。")
    else:
        source["warnings"].append("不是在线500网抓取来源，网页仅展示输入数据，不声称为实时公开源。")
    retrieved = metadata.get("retrieved_at_utc")
    if isinstance(retrieved, str):
        parsed = datetime.fromisoformat(retrieved.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            source["retrieved_at"] = parsed.astimezone(timezone.utc).isoformat()
    return source


def distributions(history: list[dict[str, Any]], zone: str, maximum: int) -> dict[str, Any]:
    """沿用model.features口径，首期没有上期，故不计入重号分布。"""
    counts: dict[str, Counter[int]] = {metric: Counter() for metric in METRICS}
    for index, row in enumerate(history):
        previous = history[index - 1][zone] if index else ()
        profile = model.features(row[zone], maximum, previous)
        for metric in METRICS:
            if metric == "repeat_previous" and index == 0:
                continue
            counts[metric][profile[metric]] += 1
    result: dict[str, Any] = {
        metric: [{"value": value, "count": count} for value, count in sorted(counts[metric].items())]
        for metric in METRICS
    }
    result["sample_sizes"] = {
        metric: len(history) - (metric == "repeat_previous") for metric in METRICS
    }
    return result


def build_snapshot(data: Path, *, generated_at: str | None = None) -> dict[str, Any]:
    """按现有模型的2013年下限过滤，导出截至末期的描述性快照而非目标期预测。"""
    records, audit = model.load_data(data)
    history = [row for row in records if model.within_history_scope(row)]
    if not history:
        raise ValueError("2013-01-01起没有有效历史，不能构建网页快照")
    source = public_source(data, audit)
    if len(history) < 100:
        source["warnings"].append("有效历史不足100期，冷热窗口使用实际样本数。")
    if history[0]["id"] != model.HISTORY_START_ISSUE:
        source["warnings"].append("输入未从13001开始，不是2013年以来的完整范围。")
    if any(
        (a["id"][:2] == b["id"][:2] and int(b["id"]) != int(a["id"]) + 1)
        or int(b["id"][:2]) > int(a["id"][:2]) + 1
        for a, b in zip(history, history[1:])
    ):
        source["warnings"].append("历史期号存在同年或整年缺口；重号与遗漏按实际可用记录计算。")
    return {
        "schema_version": 1,
        "title": "大乐透选号分析",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "description": "截至历史末期的统计与组合设计展示，不指定目标期，不代表预测结果或购彩建议。",
        "history": {
            "rows": len(history),
            "first_id": history[0]["id"], "last_id": history[-1]["id"],
            "first_date": history[0]["date"], "last_date": history[-1]["date"],
            "history_start_date": model.HISTORY_START_DATE,
            "history_start_issue": model.HISTORY_START_ISSUE,
            "excluded_before_start": len(records) - len(history),
        },
        "source": source,
        "portfolios": {
            mode: model.generate_portfolio(history, seed=0, groups=5, mode=mode)
            for mode in ("coverage", "uniform")
        },
        "distributions": {
            "left": distributions(history, "left", 35),
            "right": distributions(history, "right", 12),
        },
        "recent_draws": [
            {"id": row["id"], "date": row["date"], "left": list(row["left"]), "right": list(row["right"])}
            for row in reversed(history[-8:])
        ],
    }


def runtime_payloads(data: Path, snapshot: dict[str, Any]) -> dict[str, bytes]:
    """生成浏览器可计算的公开历史及原样模型，manifest为实际字节的哈希。"""
    records, audit = model.load_data(data)
    if audit["source_sha256"] != snapshot["source"]["sha256"]:
        raise ValueError("构建过程中源CSV发生变化，拒绝混用不同版本数据")
    history = [row for row in records if model.within_history_scope(row)]
    handle = io.StringIO(newline="")
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerow(["No.", "L1", "L2", "L3", "L4", "L5", "R1", "R2", "Date"])
    for row in history:
        writer.writerow([row["id"], *row["left"], *row["right"], row["date"]])
    csv_bytes = handle.getvalue().encode("utf-8")
    model_bytes = MODEL_FILE.read_bytes()
    manifest = {
        "schema_version": 1,
        "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
        "data_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "history": {key: snapshot["history"][key] for key in (
            "rows", "first_id", "last_id", "first_date", "last_date",
            "history_start_date", "history_start_issue",
        )},
        "source": snapshot["source"],
    }
    return {
        "model.py": model_bytes,
        "history.csv": csv_bytes,
        "manifest.json": (json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"),
    }


def write_snapshot(data: Path, output: Path, runtime_dir: Path | None = None) -> dict[str, Any]:
    """显式构建会更新输出，单文件原子替换；运行时先写资源、最后提交清单。"""
    data, output = data.expanduser().resolve(), output.expanduser().resolve()
    protected = {data, data.with_suffix(data.suffix + ".metadata.json"), MODEL_FILE.resolve()}
    if output in protected or output.suffix != ".json":
        raise ValueError("输出必须为独立的.json文件，不能覆盖输入CSV、来源侧车或原模型")
    destinations = [output]
    runtime_paths: dict[str, Path] = {}
    if runtime_dir is not None:
        runtime_dir = runtime_dir.expanduser().resolve()
        runtime_paths = {name: (runtime_dir / name).resolve() for name in ("model.py", "history.csv", "manifest.json")}
        destinations.extend(runtime_paths.values())
    if len(set(destinations)) != len(destinations) or any(path in protected for path in destinations):
        raise ValueError("运行时输出路径冲突，不能覆盖输入CSV、来源侧车、快照或原模型")
    if any(path.is_dir() or any(parent in destinations for parent in path.parents) for path in destinations):
        raise ValueError("输出路径必须是相互独立的文件，不能覆盖目录")
    snapshot = build_snapshot(data)
    payloads: dict[Path, bytes] = {}
    if runtime_dir is not None:
        runtime = runtime_payloads(data, snapshot)
        payloads.update({runtime_paths[name]: raw for name, raw in runtime.items()})
    payloads[output] = (json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    temporary_files: dict[Path, str] = {}
    try:
        # 所有内容和路径校验完成且临时文件均写入成功后，才更新发布文件。
        for path, raw in payloads.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".snapshot-", suffix=".tmp", dir=path.parent)
            temporary_files[path] = temporary
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
        for path, temporary in temporary_files.items():
            os.replace(temporary, path)
    finally:
        for temporary in temporary_files.values():
            if os.path.exists(temporary):
                os.unlink(temporary)
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path, help="用户已确认可公开的CSV；不会自动联网获取")
    parser.add_argument("--output", required=True, type=Path, help="静态网站JSON，显式构建会原子更新该文件")
    parser.add_argument("--runtime-dir", type=Path, help="可选浏览器运行时目录，公开2013年起历史CSV、原模型及哈希清单")
    args = parser.parse_args(argv)
    try:
        result = write_snapshot(args.data, args.output, args.runtime_dir)
    except (ValueError, OSError, UnicodeError, RuntimeError) as exc:
        parser.error(str(exc))
    print(json.dumps({"rows": result["history"]["rows"], "last_id": result["history"]["last_id"],
                      "schema_version": result["schema_version"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

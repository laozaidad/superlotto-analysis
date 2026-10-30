#!/usr/bin/env python3
"""大乐透选号分析：使用本地数据，缺失时获取500网历史记录。"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from fetch_data import ensure_data
import model


def data_quality(history: list[dict[str, Any]], target: str) -> dict[str, Any]:
    """区分数据结构合法与期数完整，不以成功下载代替时效验收。"""
    warnings = []
    if len(history) < 100:
        warnings.append(f"只有{len(history)}期历史，少于默认100期窗口；按实际期数计算，不补造数据。")
    missing = []
    for previous, current in zip(history, history[1:]):
        a, b = previous["id"], current["id"]
        if a[:2] == b[:2] and int(b[2:]) != int(a[2:]) + 1:
            missing.append({"after": a, "before": b})
    if missing:
        warnings.append("存在同年期号缺口；频率窗口和遗漏按已有记录计数，不代表连续实际期数。")
    last_id = history[-1]["id"]
    predecessor_present = int(target[2:]) > 1 and int(last_id) == int(target) - 1
    if int(target[2:]) > 1 and not predecessor_present:
        warnings.append(f"数据截止{last_id}，未包含目标{target}的上一期；可能陈旧或目标尚远，不宣称最新完整。")
    if int(target[2:]) == 1:
        warnings.append("目标为当年首期；仅凭五位期号不能确认上年最后一期完整性。")
    return {"training_count": len(history), "training_last_id": last_id,
            "target_predecessor_present": predecessor_present,
            "within_year_gaps": missing, "warnings": warnings,
            "complete_history_verified": False,
            "completeness_note": "连续性和上一期检查不是第三方数据准确性或跨年全量完整性的证明。"}


def execute(data: Path, target: str, seed: int, groups: int, mode: str) -> dict[str, Any]:
    acquisition = ensure_data(data, target=target)
    records, audit = model.load_data(data)
    history, cutoff = model.select_history(records, target)
    result = model.generate_portfolio(history, seed=seed, groups=groups, mode=mode)
    result["audit"] = audit
    result["cutoff"] = cutoff
    result["data_acquisition"] = acquisition
    result["data_quality"] = data_quality(history, target)
    result["display_name"] = "大乐透选号分析"
    return result


def write_new_json(path: Path, payload: str) -> None:
    """先写临时文件再原子创建，绝不覆盖已有结果。"""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".superlotto-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/numbers.csv"))
    parser.add_argument("--target", required=True, help="五位目标期号；只使用2013年起且严格早于该期的数据")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--groups", type=int, default=5)
    parser.add_argument("--mode", choices=("uniform", "coverage"), default=model.DEFAULT_MODE)
    parser.add_argument("--output", type=Path, help="可选JSON输出路径；不会覆盖已有文件")
    args = parser.parse_args(argv)
    # Reject invalid requests before any network or output side effect.
    if len(args.target) != 5 or not args.target.isascii() or not args.target.isdigit() or int(args.target[2:]) < 1:
        parser.error("target必须为有效五位期号且年内序号大于0")
    if args.groups < 1 or (args.mode == "coverage" and args.groups > 6):
        parser.error("groups必须为正数；coverage最多6组")
    if args.output and args.output.exists():
        parser.error("输出文件已存在，请选择新路径，避免覆盖历史结果")
    if args.output and args.output.resolve() == args.data.resolve():
        parser.error("输出不能与输入数据使用相同路径")
    try:
        result = execute(args.data, args.target, args.seed, args.groups, args.mode)
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if args.output:
            write_new_json(args.output, payload)
        print(payload, end="")
    except (ValueError, RuntimeError, OSError, UnicodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

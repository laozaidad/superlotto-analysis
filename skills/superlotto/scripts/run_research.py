#!/usr/bin/env python3
"""运行2023年起的条件融合实验；仅生成可审计候选，不宣称预测优势。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from fetch_data import ensure_data, validate_issue
import model
import research
from run_skill import data_quality, write_new_json

POOL_SIZES = ("5+2", "5+5", "7+3", "8+3")


def validate_request(target: str, pool_size: str) -> None:
    """在下载或文件写入前校验固定参数白名单。"""
    validate_issue(target, "目标期号")
    if int(target) <= int(model.HISTORY_START_ISSUE):
        raise ValueError("2023-01-01起且目标期之前没有历史数据；目标必须晚于23001")
    if pool_size not in POOL_SIZES:
        raise ValueError("pool-size仅支持5+2、5+5、7+3、8+3")


def execute(data: Path, target: str, pool_size: str = "5+2") -> dict[str, Any]:
    validate_request(target, pool_size)
    acquisition = ensure_data(data, target=target)
    records, audit = model.load_data(data)
    history, _ = model.select_history(records, target)
    result = research.generate_research(records, target, pool_size=pool_size)
    result["audit"] = audit
    result["data_acquisition"] = acquisition
    result["data_quality"] = data_quality(history, target)
    result["display_name"] = "大乐透选号分析"
    scripts = Path(__file__).resolve().parent
    result["code_sha256"] = {
        name: hashlib.sha256((scripts / name).read_bytes()).hexdigest()
        for name in ("model.py", "research.py", "conditional_core.py")
    }
    result["warnings"] = list(dict.fromkeys([
        *result["warnings"], *audit["warnings"], *acquisition.get("warnings", []),
        *result["data_quality"]["warnings"],
        "第三方数据未逐条官方核验；来源哈希不证明真实性或完整性。",
        "结果文件用于复现，不提供可信的开奖前时间戳或不可篡改证明。",
    ]))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/numbers.csv"))
    parser.add_argument("--target", required=True, help="五位目标期号；只用2023年起且严格早于目标的记录")
    parser.add_argument("--pool-size", choices=POOL_SIZES, default="5+2", help="预先固定的号码池规格，不是组数")
    parser.add_argument("--output", type=Path, help="新JSON输出路径；不覆盖已存在文件")
    args = parser.parse_args(argv)
    try:
        validate_request(args.target, args.pool_size)
        if args.output and args.output.exists():
            raise ValueError("输出文件已存在，请选择新路径，避免覆盖历史结果")
        if args.output and args.output.resolve() == args.data.resolve():
            raise ValueError("输出不能与输入数据使用相同路径")
        result = execute(args.data, args.target, args.pool_size)
        payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        if args.output:
            write_new_json(args.output, payload)
        print(payload, end="")
    except (ValueError, RuntimeError, OSError, UnicodeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""复核已存档逐期预测，导出公开研究证据；不重新选模，不声称前瞻验证。"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from typing import Any

VARIANTS = {
    "equal_rank_fusion": "等权融合",
    "conditional_no_dedup": "条件权重",
    "conditional_dedup": "条件权重＋软去冗余",
}
SIZES = ("5+2", "7+3", "8+3")
FAMILY_SIZE = 66


def total_hit_pmf(maximum: int, pool: int, drawn: int, periods: int) -> list[float]:
    """均匀独立零假设下，逐期超几何命中数之和的精确离散分布（浮点）。"""

    def choose(n: int, k: int) -> int:
        return math.comb(n, k) if 0 <= k <= n else 0

    single = [
        choose(pool, hit) * choose(maximum - pool, drawn - hit) / math.comb(maximum, drawn) for hit in range(drawn + 1)
    ]
    total = [1.0]
    for _ in range(periods):
        updated = [0.0] * (len(total) + drawn)
        for i, probability in enumerate(total):
            for hit, mass in enumerate(single):
                updated[i + hit] += probability * mass
        total = updated
    return total


def numbers(values: Any, size: int, maximum: int) -> set[int]:
    if not isinstance(values, list) or len(values) != size or any(type(n) is not int for n in values):
        raise ValueError("号码数量或类型错误")
    if values != sorted(set(values)) or any(not 1 <= n <= maximum for n in values):
        raise ValueError("号码越界、重复或未排序")
    return set(values)


def build_evidence(study: dict[str, Any]) -> dict[str, Any]:
    if study.get("schema_version") != 1 or study.get("history_start_issue") != "23001":
        raise ValueError("研究范围或schema不正确")
    if study.get("historical_data_previously_seen") is not True:
        raise ValueError("存档研究必须标注历史已使用，不能包装成盲测")
    if study.get("test") != {"first_id": "26001", "last_id": "26123", "periods": 123}:
        raise ValueError("该导出器仅复核已存档的123期研究，不用于扩展测试窗口")
    hashes = study.get("source_hashes")
    hash_keys = {"original_results", "original_walk_forward", "original_protocol", "data"}
    if (
        not isinstance(hashes, dict)
        or set(hashes) != hash_keys
        or any(
            not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)
            for value in hashes.values()
        )
    ):
        raise ValueError("公开来源只接受固定字段的SHA-256，不复制路径或任意来源文本")
    actual_by_target: dict[str, tuple[tuple[int, ...], tuple[int, ...]]] = {}
    rows = study["rows"]
    expected = {(f"26{i:03d}", variant) for i in range(1, 124) for variant in VARIANTS}
    observed = [(r["target"], r["variant"]) for r in rows]
    if len(observed) != len(expected) or set(observed) != expected:
        raise ValueError("研究逐期记录缺失、重复或包含未知策略")
    totals: dict[tuple[str, str], Counter[str]] = {}
    for row in rows:
        target = row["target"]
        for key in ("history_last_id", "gate_training_last_id"):
            if not isinstance(row[key], str) or not row[key].isdigit() or not 23001 <= int(row[key]) < int(target):
                raise ValueError("训练截止越界或包含当期未来数据")
        actual_l, actual_r = numbers(row["actual_left"], 5, 35), numbers(row["actual_right"], 2, 12)
        actual = (tuple(sorted(actual_l)), tuple(sorted(actual_r)))
        if target in actual_by_target and actual_by_target[target] != actual:
            raise ValueError("不同策略的同期实际开奖号码不一致")
        actual_by_target[target] = actual
        pools = row["pools"]
        if len(pools) != 3 or {p["size"] for p in pools} != set(SIZES):
            raise ValueError("复式规格不符，不能事后扩大号码池")
        for pool in pools:
            left, right = map(int, pool["size"].split("+"))
            hits_l = len(actual_l & numbers(pool["left"], left, 35))
            hits_r = len(actual_r & numbers(pool["right"], right, 12))
            total = totals.setdefault((row["variant"], pool["size"]), Counter())
            total.update(left_hits=hits_l, right_hits=hits_r, full_coverage_count=int(hits_l == 5 and hits_r == 2), n=1)
    comparisons: list[dict[str, Any]] = []
    all_tests: list[dict[str, Any]] = []
    distributions = {
        (m, k, d): total_hit_pmf(m, k, d, 123)
        for m, k, d in ((35, 5, 5), (35, 7, 5), (35, 8, 5), (12, 2, 2), (12, 3, 2))
    }
    for variant, label in VARIANTS.items():
        for size in SIZES:
            a, b = map(int, size.split("+"))
            total = totals[variant, size]
            p_l = min(1.0, math.fsum(distributions[35, a, 5][total["left_hits"] :]))
            p_r = min(1.0, math.fsum(distributions[12, b, 2][total["right_hits"] :]))
            record = dict(
                variant=variant,
                label=label,
                size=size,
                **total,
                p_left=p_l,
                p_right=p_r,
                p_left_adjusted=min(1.0, p_l * FAMILY_SIZE),
                p_right_adjusted=min(1.0, p_r * FAMILY_SIZE),
            )
            all_tests.append(record)
            if size == "5+2":
                comparisons.append(record)
    if any(row[key] < 0.05 for row in all_tests for key in ("p_left_adjusted", "p_right_adjusted")):
        raise ValueError("重算结果与原存档无显著优势结论矛盾，需要人工调查")
    return {
        "schema_version": 1,
        "scope": {"start_issue": "23001", "start_date": "2023-01-01"},
        "test": study["test"],
        "status": "exploratory_no_advantage",
        "prediction_gate": "CLOSED",
        "historical_data_previously_seen": True,
        "verification": "recomputed_from_saved_walk_forward",
        "source_hashes": study["source_hashes"],
        "random_expected": {"left": 123 * 25 / 35, "right": 123 * 4 / 12},
        "comparisons": comparisons,
        "all_tests": all_tests,
        "multiple_testing": {"method": "Bonferroni", "family_size": 66},
        "limitations": [
            "这是既有2026年123期探索性研究，历史已多次使用，不是新盲测，也不是本次部署后的验证。",
            "本次从存档逐期号码重算命中、同期全覆盖和超几何零假设上尾p；不是重新训练原研究流程。",
            "比较族沿用原研究累计66项；校正不能消除未记录的跨轮选参和研究者自由度。",
            "前区累计91、后区36不表示全中或收益；完整方案没有检出优于同规模随机的证据。",
            "表中单式随机期望只适用于5+2；5+5未在这份旧研究中测试，不能外推。",
            "第三方历史数据并非全量官方认证；本工具不计算奖级、奖金或收益率。",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("不能覆盖输入")
    try:
        raw = args.input.read_bytes()
        study = json.loads(raw)
        evidence = build_evidence(study)
        evidence["source_hashes"] = {**evidence["source_hashes"], "public_study": hashlib.sha256(raw).hexdigest()}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        print(json.dumps({"comparisons": len(evidence["all_tests"]), "periods": 123, "prediction_gate": "CLOSED"}))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""可审计选号模型：历史描述与组合覆盖，不把形态评分当成预测概率。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import re

DEFAULT_MODE = "coverage"
SPACE_SIZE = math.comb(35, 5) * math.comb(12, 2)
WARNING = (
    "仅为可复现的数据描述与组合设计，不构成购彩建议。"
    "均匀独立假设下每个完整组合等概率，冷热、遗漏、形态多样性不提高单组全中概率。"
)


def _check_numbers(nums, maximum, expected_size=None):
    """拒绝越界、重复、布尔值等非法号码，不悄悄修复输入。"""
    values = tuple(nums)
    if not values or any(type(n) is not int for n in values):
        raise ValueError("号码必须是非空整数序列")
    if len(set(values)) != len(values) or min(values) < 1 or max(values) > maximum:
        raise ValueError(f"号码必须在 1–{maximum} 内且区内无重复")
    if expected_size is not None and len(values) != expected_size:
        raise ValueError(f"本区必须有 {expected_size} 个号码")
    return tuple(sorted(values))


def _parse_date(value):
    """接受纯 ISO 日期或 ISO 时间戳，统一为 UTC 以检查时序。"""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"非法 ISO 日期：{value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_data(path):
    """只读加载 CSV；完整跨期重复保留并告警，期号重复或非法行直接报错。"""
    path = Path(path).resolve()
    raw = path.read_bytes()
    reader = csv.DictReader(raw.decode("utf-8-sig").splitlines())
    expected_columns = ["No.", "L1", "L2", "L3", "L4", "L5", "R1", "R2", "Date"]
    if reader.fieldnames != expected_columns:
        raise ValueError(f"CSV 表头必须为 {expected_columns}")
    records = []
    seen_ids = set()
    combined = defaultdict(list)
    previous_id = None
    previous_date = None
    timestamps = 0
    for line, row in enumerate(reader, start=2):
        if set(row) != set(expected_columns):
            raise ValueError(f"第 {line} 行列数与表头不一致")
        identity = row["No."]
        if identity is None or re.fullmatch(r"[0-9]{5}", identity) is None:
            raise ValueError(f"第 {line} 行期号必须为五位数字字符串")
        if int(identity[2:]) < 1:
            raise ValueError(f"第 {line} 行期号的年内序号必须大于0")
        if identity in seen_ids:
            raise ValueError(f"期号重复：{identity}")
        if previous_id is not None and int(identity) <= previous_id:
            raise ValueError(f"期号未严格递增：{identity}")
        try:
            left = tuple(int(row[f"L{i}"]) for i in range(1, 6))
            right = tuple(int(row[f"R{i}"]) for i in range(1, 3))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"第 {line} 行号码不可解析为整数") from exc
        if _check_numbers(left, 35, 5) != left or _check_numbers(right, 12, 2) != right:
            raise ValueError(f"第 {line} 行区内号码未升序排列")
        if not isinstance(row["Date"], str):
            raise ValueError(f"第 {line} 行日期缺失")
        date = _parse_date(row["Date"])
        if datetime.fromisoformat(row["Date"].replace("Z", "+00:00")).year % 100 != int(identity[:2]):
            raise ValueError(f"第 {line} 行期号年份与日期不一致")
        if previous_date is not None and date <= previous_date:
            raise ValueError(f"日期未严格递增：{identity}")
        record = {"id": identity, "left": left, "right": right, "date": row["Date"]}
        records.append(record)
        seen_ids.add(identity)
        combined[left + right].append(identity)
        previous_id, previous_date = int(identity), date
        timestamps += ("T" in row["Date"])
    if not records:
        raise ValueError("CSV 没有历史数据，禁止回退到内置样本")
    duplicates = [{"ids": ids, "left": list(key[:5]), "right": list(key[5:])}
                  for key, ids in combined.items() if len(ids) > 1]
    return records, {
        "source_path": str(path), "source_sha256": hashlib.sha256(raw).hexdigest(),
        "rows": len(records), "first_id": records[0]["id"], "last_id": records[-1]["id"],
        "duplicate_full_sets": duplicates, "iso_timestamp_rows": timestamps,
        "warnings": (["完整号码跨期重复；保留原始记录，不等同于重复期号。"] if duplicates else [])
                    + (["日期包含 ISO 时间戳，而非仅 YYYY-MM-DD。"] if timestamps else []),
    }


def select_history(records, target):
    """仅选择目标期之前的数据；同一期及未来期不参与任何特征与选号。"""
    target = str(target)
    if re.fullmatch(r"[0-9]{5}", target) is None or int(target[2:]) < 1:
        raise ValueError("目标期号必须为五位数字")
    history = [record for record in records if int(record["id"]) < int(target)]
    if not history:
        raise ValueError("目标期之前没有历史数据")
    return history, {
        "target": target, "training_rows": len(history),
        "training_last_id": history[-1]["id"],
        "excluded_future": len(records) - len(history),
        "exclusion_definition": "期号大于或等于目标期；这些行只参与源文件完整性审计，不参与模型。",
    }


def features(nums, maximum, previous=(), heat=None):
    """统一形态口径：三连算两个相邻对；重号只与上期同区比较。"""
    if maximum not in (35, 12):
        raise ValueError("maximum 必须为 35 或 12")
    values = _check_numbers(nums, maximum)
    odd = sum(n % 2 for n in values)
    small = sum(n <= maximum // 2 for n in values)
    adjacent = 0
    run = maximum_run = 1
    for a, b in zip(values, values[1:]):
        if b == a + 1:
            adjacent += 1
            run += 1
            maximum_run = max(maximum_run, run)
        else:
            run = 1
    result = {
        "odd": odd, "even": len(values) - odd,
        "small": small, "large": len(values) - small,
        "sum": sum(values), "span": values[-1] - values[0],
        "adjacent_pairs": adjacent, "max_run": maximum_run,
        "repeat_previous": len(set(values).intersection(previous)),
    }
    if heat is not None:
        labels = Counter(heat[n]["label"] for n in values)
        result.update({label: labels[label] for label in ("hot", "warm", "cold")})
    return result


def heat_summary(history, maximum, k, window=100):
    """冷热仅为历史频数相对均匀基准的一倍标准差描述，不是显著性或预测。"""
    if type(maximum) is not int or type(k) is not int or not 0 < k < maximum:
        raise ValueError("必须满足整数 0 < k < maximum")
    if type(window) is not int or window <= 0:
        raise ValueError("window 必须为正整数")
    if not history:
        raise ValueError("冷热统计需要非空历史")
    history = [_check_numbers(row, maximum, k) for row in history]
    chosen = history[-window:]
    n = len(chosen)
    counts = Counter(number for row in chosen for number in row)
    p = k / maximum
    expected = n * p
    sd = math.sqrt(n * p * (1 - p))
    last_seen: dict[int, int] = {}
    for gap, row in enumerate(reversed(history)):
        for number in row:
            last_seen.setdefault(number, gap)
    result = {}
    for number in range(1, maximum + 1):
        z = (counts[number] - expected) / sd
        result[number] = {
            "number": number, "window": n, "count": counts[number],
            "rate": counts[number] / n, "expected": expected, "sd": sd, "z": z,
            "label": "hot" if z >= 1 else "cold" if z <= -1 else "warm",
            "gap": last_seen.get(number, len(history)),
            "gap_censored": number not in last_seen,
        }
    return result


def _diversity_score(pairs, previous_left, previous_right):
    """最大化形态档位覆盖数，不声称该分数是概率；不使用冷热权重。"""
    total = 0
    for zone, maximum, previous, sum_width, span_width in (
        (0, 35, previous_left, 15, 7), (1, 12, previous_right, 5, 3)
    ):
        profiles = []
        for pair in pairs:
            f = features(pair[zone], maximum, previous)
            profiles.append((f["odd"], f["small"], f["sum"] // sum_width,
                             f["span"] // span_width, f["adjacent_pairs"], f["repeat_previous"]))
        total += sum(len({profile[index] for profile in profiles}) for index in range(6))
    return total


def generate_portfolio(records, seed=26124, groups=5, mode="uniform"):
    """生成示例组合；uniform 为均匀基线，coverage 只优化覆盖和形态差异。"""
    if not records:
        raise ValueError("必须提供目标期之前的历史")
    if type(groups) is not int or groups < 1:
        raise ValueError("groups 必须为正整数")
    if mode not in ("uniform", "coverage"):
        raise ValueError("mode 必须为 uniform 或 coverage")
    if mode == "coverage" and groups > 6:
        raise ValueError("coverage 模式最多 6 组，受 Right 12 个号码无重叠限制")
    seen = {tuple(row["left"]) + tuple(row["right"]) for row in records}
    if groups > SPACE_SIZE - len(seen):
        raise ValueError("剩余不重复组合不足")
    rng = random.Random(seed)
    previous_left, previous_right = records[-1]["left"], records[-1]["right"]
    attempts = 0
    if mode == "uniform":
        pairs: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
        selected = set()
        while len(pairs) < groups:
            attempts += 1
            if attempts > max(10000, 100 * groups):
                raise RuntimeError("uniform 采样超出尝试上限，未输出部分组合")
            left = tuple(sorted(rng.sample(range(1, 36), 5)))
            right = tuple(sorted(rng.sample(range(1, 13), 2)))
            key = left + right
            if key in seen or key in selected:
                continue
            selected.add(key)
            pairs.append((left, right))
        diversity = _diversity_score(pairs, previous_left, previous_right)
        candidate_partitions = 1
    else:
        best = None
        best_score = -1
        accepted = 0
        while accepted < 256:
            attempts += 1
            if attempts > 2560:
                raise RuntimeError("coverage 采样超出尝试上限，未输出未经验证的组合")
            left_pool, right_pool = list(range(1, 36)), list(range(1, 13))
            rng.shuffle(left_pool)
            rng.shuffle(right_pool)
            candidate = [(tuple(sorted(left_pool[5*i:5*i+5])),
                          tuple(sorted(right_pool[2*i:2*i+2]))) for i in range(groups)]
            if any(left + right in seen for left, right in candidate):
                continue
            accepted += 1
            score = _diversity_score(candidate, previous_left, previous_right)
            if score > best_score:
                best, best_score = candidate, score
        if best is None:
            raise RuntimeError("没有生成有效覆盖分区")
        pairs, diversity, candidate_partitions = best, best_score, accepted
    heat_left = heat_summary([r["left"] for r in records], 35, 5)
    heat_right = heat_summary([r["right"] for r in records], 12, 2)
    items = [{"index": index + 1, "left": list(left), "right": list(right),
              "left_features": features(left, 35, previous_left, heat_left),
              "right_features": features(right, 12, previous_right, heat_right)}
             for index, (left, right) in enumerate(pairs)]
    left_union = sorted({n for left, _ in pairs for n in left})
    right_union = sorted({n for _, right in pairs for n in right})
    overlaps = [{"a": i + 1, "b": j + 1,
                 "left": len(set(pairs[i][0]).intersection(pairs[j][0])),
                 "right": len(set(pairs[i][1]).intersection(pairs[j][1]))}
                for i in range(groups) for j in range(i + 1, groups)]
    return {
        "model_version": "1.0", "mode": mode, "seed": seed,
        "group_count": groups, "groups": items,
        "coverage": {"left_union": left_union, "right_union": right_union,
                     "left_count": len(left_union), "right_count": len(right_union),
                     "left_max_possible": min(5 * groups, 35),
                     "right_max_possible": min(2 * groups, 12)},
        "overlap": {"pairs": overlaps, "max_left": max((p["left"] for p in overlaps), default=0),
                    "max_right": max((p["right"] for p in overlaps), default=0)},
        "diversity_score": diversity, "candidate_partitions": candidate_partitions,
        "sampling_attempts": attempts, "space_size": SPACE_SIZE,
        "single_ticket_probability": 1 / SPACE_SIZE,
        "distinct_ticket_count": len({left + right for left, right in pairs}),
        "joint_probability": groups / SPACE_SIZE,
        "probability_assumption": "uniform independent draws",
        "prediction_gate": "CLOSED",
        "predictive_advantage_claim": False,
        "probability_event": "均匀独立假设下，同一期至少一个完整组合七个号码全中；不是任意奖率。",
        "historical_exclusion": "按本地README约束排除已见完整组合，不是假设开奖不会重复。",
        "diversity_definition": {
            "objective": "对两区分别统计 odd/small/sum_bucket/span_bucket/adjacent_pairs/repeat_previous 的不同取值数，再求和；不是概率分数。",
            "left_sum_bucket": "sum // 15", "left_span_bucket": "span // 7",
            "right_sum_bucket": "sum // 5", "right_span_bucket": "span // 3",
            "heat_weight": 0, "hard_shape_filters": [],
        },
        "heat": {"window_requested": 100, "left": heat_left, "right": heat_right,
                 "definition": "z=(次数-n*k/M)/sqrt(n*k/M*(1-k/M)); z>=1热，z<=-1冷，其余温。遗漏依据全部可用历史的最近出现。仅为描述。"},
        "warning": WARNING,
    }


def main(argv=None):
    """CLI 只向 stdout 输出一份稳定 JSON，不写入或修改任何文件。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--target", required=True)
    parser.add_argument("--seed", type=int, default=26124)
    parser.add_argument("--groups", type=int, default=5)
    parser.add_argument("--mode", choices=("uniform", "coverage"), default=DEFAULT_MODE)
    args = parser.parse_args(argv)
    try:
        records, audit = load_data(args.data)
        history, cutoff = select_history(records, args.target)
        output = generate_portfolio(history, seed=args.seed, groups=args.groups, mode=args.mode)
        output["audit"] = audit
        output["cutoff"] = cutoff
    except (ValueError, RuntimeError, OSError, UnicodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

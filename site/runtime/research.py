"""条件融合研究入口：严格历史截断、确定性计算；没有已证实的预测优势。

只依赖同目录标准库模块，不读取历史报告或保存过的预测结果。固定参数来自
既有探索，不把对历史目标的重算冒充事先冻结的独立验证。
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import math
from typing import Any

import conditional_core as core
import model

Record = dict[str, Any]
NAMES = ("legacy_blend", "shrink20", "shrink100", "shrink_all", "gap_rank")
RIDGE = 10.0
TEMPERATURE = 0.5
PRIOR = 100
MIN_FEATURE_HISTORY = 100
MIN_LEARNING_ROWS = 100
MODEL_VERSION = "conditional-fusion-v1"
POOL_SIZES = {"5+2": (5, 2), "5+5": (5, 5), "7+3": (7, 3), "8+3": (8, 3)}
FEATURE_NAMES = tuple(f"{zone}_{name}" for zone in ("left", "right") for name in (
    "freq20_vs100_rms", "concentration20", "mean_gap_div100", "max_gap_div100", "repeat20_share"))


def _validate_history(history: list[Record]) -> None:
    """直接 Python 调用也拒绝乱序、重复期、非法号码；不检查被排除期的开奖结果。"""
    previous_id = 0
    previous_date = None
    for row in history:
        identity = row["id"]
        if not isinstance(identity, str) or len(identity) != 5 or not identity.isascii() or not identity.isdigit():
            raise ValueError("研究历史期号必须为五位数字字符串")
        if int(identity[2:]) < 1 or int(identity) <= previous_id:
            raise ValueError("研究历史期号必须严格递增且不可重复")
        date = model._parse_date(row["date"])
        source_year = datetime.fromisoformat(row["date"].replace("Z", "+00:00")).year
        if source_year % 100 != int(identity[:2]) or (previous_date is not None and date <= previous_date):
            raise ValueError("研究历史日期必须严格递增且与期号年份一致")
        for zone, maximum, count in (("left", 35, 5), ("right", 12, 2)):
            if tuple(row[zone]) != model._check_numbers(row[zone], maximum, count):
                raise ValueError("研究历史区内号码必须升序排列")
        previous_id, previous_date = int(identity), date


def _expert_ranking(history: list[Record], zone: str, name: str) -> list[int]:
    """沿用已审计专家定义及浮点同分顺序；这些排序不是概率。"""
    if name not in NAMES or zone not in ("left", "right") or not history:
        raise ValueError("专家名称、分区或历史无效")
    maximum, drawn = (35, 5) if zone == "left" else (12, 2)
    sequences = [row[zone] for row in history]
    scores: dict[int, float]
    if name == "gap_rank":
        last_seen = {number: index for index, row in enumerate(sequences) for number in row}
        scores = {number: len(history) - 1 - last_seen.get(number, -1) for number in range(1, maximum + 1)}
    else:
        windows = (30, 100, len(history)) if name == "legacy_blend" else (
            20 if name == "shrink20" else 100 if name == "shrink100" else len(history),
        )
        scores = {number: 0.0 for number in range(1, maximum + 1)}
        for width in windows:
            rows = sequences[-width:]
            counts = Counter(number for row in rows for number in row)
            for number in scores:
                scores[number] += (counts[number] / len(rows) if name == "legacy_blend" else
                                   (counts[number] + PRIOR * drawn / maximum) / (len(rows) + PRIOR)) / len(windows)
    return sorted(scores, key=lambda number: (-scores[number], number))


def _history_features(history: list[Record]) -> list[float]:
    if len(history) < MIN_FEATURE_HISTORY:
        raise ValueError("每个研究特征至少需要 100 期此前历史")
    values = []
    for zone, maximum, drawn in (("left", 35, 5), ("right", 12, 2)):
        short = Counter(number for row in history[-20:] for number in row[zone])
        long = Counter(number for row in history[-100:] for number in row[zone])
        rms = math.sqrt(math.fsum((short[n] / 20 - long[n] / 100) ** 2 for n in range(1, maximum + 1)) / maximum)
        concentration = math.fsum((short[n] / (20 * drawn)) ** 2 for n in range(1, maximum + 1))
        last_seen = {number: i for i, row in enumerate(history) for number in row[zone]}
        gaps = [len(history) - 1 - last_seen.get(n, -1) for n in range(1, maximum + 1)]
        recent = history[-21:]
        repeats = math.fsum(len(set(a[zone]) & set(b[zone])) for a, b in zip(recent, recent[1:])) / (20 * drawn)
        values.extend([rms, concentration, math.fsum(gaps) / (100 * maximum), max(gaps) / 100, repeats])
    return values


def _make_input(history: list[Record]) -> Record:
    rankings = {zone: [_expert_ranking(history, zone, name) for name in NAMES] for zone in ("left", "right")}
    vectors = []
    for i in range(len(NAMES)):
        vector: list[float] = []
        for zone, maximum in (("left", 35), ("right", 12)):
            ranks = {number: rank for rank, number in enumerate(rankings[zone][i], start=1)}
            vector.extend((maximum - ranks[n]) / (maximum - 1) for n in range(1, maximum + 1))
        vectors.append(vector)
    return {"x": _history_features(history), "rankings": rankings, "rank_vectors": vectors,
            "training_last_id": history[-1]["id"]}


def _build_learning_rows(history: list[Record]) -> list[Record]:
    """先用严格前缀造特征和排序，再读取该行结果；调用方已截断并验证历史。"""
    samples = []
    for index in range(MIN_FEATURE_HISTORY, len(history)):
        actual = history[index]
        current = _make_input(history[:index])
        hits = [(len(set(current["rankings"]["left"][i][:5]) & set(actual["left"])),
                 len(set(current["rankings"]["right"][i][:2]) & set(actual["right"]))) for i in range(len(NAMES))]
        samples.append({**current, "target": actual["id"],
                        "y": [(7 * left + 15 * right) / 10 for left, right in hits]})
    return samples


def generate_research(records: list[Record], target: str, pool_size: str = "5+2") -> Record:
    """生成一个研究候选池，不运行选参或回测，不接受外部预拟合状态。

    CSV 用户应先调用 model.load_data；本入口再次验证入模历史。只使用统一
    2023 下限与目标之前的数据，至少 100 期特征预热加 100 行有结果学习样本。
    """
    if not isinstance(pool_size, str) or pool_size not in POOL_SIZES:
        raise ValueError("研究候选池仅支持 5+2、5+5、7+3、8+3")
    if not isinstance(target, str):
        raise ValueError("目标期号必须为五位数字字符串")
    history, cutoff = model.select_history(records, target)
    _validate_history(history)
    minimum = MIN_FEATURE_HISTORY + MIN_LEARNING_ROWS
    if len(history) < minimum:
        raise ValueError(f"研究模式至少需要 {minimum} 期 2023 年起且目标之前的历史"
                         f"（100 期特征预热 + 100 行学习样本），实际 {len(history)} 期；不回退到其他模式")
    samples = _build_learning_rows(history)
    if any(int(sample["training_last_id"]) >= int(sample["target"]) or
           int(sample["target"]) >= int(target) for sample in samples):
        raise ValueError("研究训练样本违反严格时序截止")
    current = _make_input(history)
    state = core.fit_conditional_scores([sample["x"] for sample in samples],
                                        [sample["y"] for sample in samples], RIDGE)
    rewards = core.predict_conditional_scores(state, current["x"])
    similarity = core.average_rank_similarity([sample["rank_vectors"] for sample in samples])
    weights = core.conditional_expert_weights(rewards, similarity, TEMPERATURE, True)
    raw_weights = core.conditional_expert_weights(rewards, similarity, TEMPERATURE, False)
    fused = {zone: core.fuse_expert_rankings(current["rankings"][zone], weights, maximum)
             for zone, maximum in (("left", 35), ("right", 12))}
    left_size, right_size = POOL_SIZES[pool_size]
    combinations = math.comb(left_size, 5) * math.comb(right_size, 2)
    return {
        "schema_version": 1, "kind": "research", "model_version": MODEL_VERSION, "target": target,
        "prediction_gate": "CLOSED", "predictive_advantage_claim": False, "score_not_probability": True,
        "history": {"start_issue": model.HISTORY_START_ISSUE, "start_date": model.HISTORY_START_DATE,
                    "first_id": history[0]["id"], "last_id": history[-1]["id"], "rows": len(history)},
        "cutoff": cutoff,
        "learning": {"rows": len(samples), "first_id": samples[0]["target"], "last_id": samples[-1]["target"]},
        "parameters": {"ridge": RIDGE, "temperature": TEMPERATURE, "variant": "conditional_dedup"},
        "experts": [{"name": name, "weight": weights[i], "raw_weight": raw_weights[i],
                     "predicted_reward": rewards[i], "similarity_density": math.fsum(similarity[i])}
                    for i, name in enumerate(NAMES)],
        "features": [{"name": name, "value": value} for name, value in zip(FEATURE_NAMES, current["x"])],
        "similarity": similarity, "fused_rankings": fused,
        "pool": {"size": pool_size, "left": sorted(fused["left"][:left_size]),
                 "right": sorted(fused["right"][:right_size]), "basic_combinations": combinations,
                 "basic_cost_yuan": 2 * combinations,
                 "joint_probability": {"numerator": combinations, "denominator": model.SPACE_SIZE}},
        "warnings": [
            "研究模式仅为可复现的实验候选，不构成购彩建议；既有探索未显示统计显著优势，预测门槛仍关闭。",
            "ridge=10 来自 2026 年既有探索性研究的开发段选参，不是对任意历史目标期事先预注册的参数；重算不是独立验证。",
            "条件成绩、专家权重与融合名次都不是开奖概率；软去冗余不证明专家独立，也不保证复制专家后总权重不变。",
            "单式成绩用于学习，两区共享权重；未证明该目标适合更大复式池。扩大池只增加基本组合数及成本。",
            "joint_probability 仅指均匀独立假设下完整 5+2 全中概率，不代表任一奖级概率；历史完整组合允许再次出现。",
        ],
    }

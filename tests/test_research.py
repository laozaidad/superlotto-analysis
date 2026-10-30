"""条件成绩、软去冗余、排名融合的独立小样本数学测试。"""
from __future__ import annotations

import copy
import json
import math
import unittest

from datetime import date, timedelta
from pathlib import Path
import random
import sys
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/superlotto/scripts"))
import conditional_core as core
import research


class ConditionalFitTests(unittest.TestCase):
    def test_closed_form_single_feature_five_outputs(self) -> None:
        x = [[0.0], [1.0], [2.0]]
        y = [[10.0 + j + (j + 1) * row[0] for j in range(5)] for row in x]
        state = core.fit_conditional_scores(x, y, 3.0)
        predicted = core.predict_conditional_scores(state, [3.0])
        # 三个样本的标准化平方和为3，lambda=3使斜率减半，截距由目标均值恢复。
        expected = [10.0 + j + 2 * (j + 1) for j in range(5)]
        for observed, truth in zip(predicted, expected):
            self.assertAlmostEqual(observed, truth, places=12)
        self.assertEqual(state["feature_count"], 1)
        self.assertEqual(state["output_count"], 5)

    def test_intercept_constant_feature_and_one_sample(self) -> None:
        constant = core.fit_conditional_scores([[7.0, 1.0]] * 3, [[8.0, 2.0]] * 3, 100.0)
        self.assertEqual(constant["x_scale"], [1.0, 1.0])
        self.assertEqual(constant["coefficients"], [[0.0, 0.0], [0.0, 0.0]])
        self.assertEqual(core.predict_conditional_scores(constant, [500.0, -99.0]), [8.0, 2.0])
        one = core.fit_conditional_scores([[4.0, 6.0]], [[8.0, 9.0]], 10.0)
        self.assertEqual(core.predict_conditional_scores(one, [0.0, 0.0]), [8.0, 9.0])

    def test_dependent_features_still_solve_with_ridge(self) -> None:
        x = [[float(i), float(i * 2)] for i in range(8)]
        y = [[float(3 * i + 5)] for i in range(8)]
        state = core.fit_conditional_scores(x, y, 1e-6)
        self.assertAlmostEqual(core.predict_conditional_scores(state, [8.0, 16.0])[0], 29.0, places=5)

    def test_training_only_standardization_and_json_state(self) -> None:
        x = [[0.0, 2.0], [2.0, 4.0], [4.0, 6.0]]
        y = [[2.0], [4.0], [5.0]]
        state = core.fit_conditional_scores(x, y, 10.0)
        self.assertEqual(state["x_mean"], [2.0, 4.0])
        initial = copy.deepcopy(state)
        a = core.predict_conditional_scores(state, [1000.0, 2000.0])
        b = core.predict_conditional_scores(json.loads(json.dumps(state)), [1000.0, 2000.0])
        self.assertEqual(a, b)
        self.assertEqual(initial, state)

    def test_input_not_mutated_and_fit_reproducible(self) -> None:
        x = [[0.0, 3.0], [2.0, 4.0], [4.0, 6.0]]
        y = [[2.0, 7.0], [4.0, 3.0], [5.0, 2.0]]
        originals = copy.deepcopy((x, y))
        state = core.fit_conditional_scores(x, y, 10.0)
        self.assertEqual(state, core.fit_conditional_scores(x, y, 10.0))
        self.assertEqual((x, y), originals)

    def test_invalid_training_and_prediction_inputs(self) -> None:
        for x, y, ridge in [([], [[1.0]], 10.0), ([[1.0]], [], 10.0),
                            ([[1.0], [2.0]], [[1.0]], 10.0),
                            ([[1.0], [2.0, 3.0]], [[1.0], [2.0]], 10.0),
                            ([[math.nan]], [[1.0]], 10.0), ([[math.inf]], [[1.0]], 10.0),
                            ([[1.0]], [[math.inf]], 10.0), ([[1.0]], [[1.0]], 0.0),
                            ([[1.0]], [[1.0]], -1.0), ([[1.0]], [[1.0]], math.inf)]:
            with self.subTest(x=x, y=y, ridge=ridge), self.assertRaises(ValueError):
                core.fit_conditional_scores(x, y, ridge)
        state = core.fit_conditional_scores([[0.0], [1.0]], [[1.0], [2.0]], 10.0)
        for vector in ([], [0.0, 1.0], [math.nan]):
            with self.assertRaises(ValueError):
                core.predict_conditional_scores(state, vector)
        broken = {**state, "x_scale": [0.0]}
        with self.assertRaises(ValueError):
            core.predict_conditional_scores(broken, [2.0])
        with self.assertRaises(ValueError):
            core.predict_conditional_scores({}, [2.0])


class SimilarityWeightTests(unittest.TestCase):
    def test_centered_cosine_positive_part_after_temporal_average(self) -> None:
        positive = [[1.0, 0.0], [1.0, 0.0]]
        negative = [[1.0, 0.0], [0.0, 1.0]]
        self.assertEqual(core.average_rank_similarity([positive]), [[1.0, 1.0], [1.0, 1.0]])
        self.assertEqual(core.average_rank_similarity([negative]), [[1.0, 0.0], [0.0, 1.0]])
        # 若逐期先截负再平均会错误地产生0.5；正确结果是0。
        self.assertEqual(core.average_rank_similarity([positive, negative]), [[1.0, 0.0], [0.0, 1.0]])

    def test_orthogonal_centered_vectors_and_47_dimension_input(self) -> None:
        orthogonal = [[1.0, 1.0, 0.0, 0.0], [1.0, 0.0, 1.0, 0.0]]
        self.assertEqual(core.average_rank_similarity([orthogonal]), [[1.0, 0.0], [0.0, 1.0]])
        a = [i / 34 for i in range(35)] + [i / 11 for i in range(12)]
        b = [1 - v for v in a]
        observed = core.average_rank_similarity([[a, b, a]])
        self.assertEqual(observed, [[1.0, 0.0, 1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 1.0]])

    def test_similarity_validation_and_input_not_mutated(self) -> None:
        history = [[[0.0, 1.0], [1.0, 0.0]], [[0.2, 0.8], [0.9, 0.1]]]
        original = copy.deepcopy(history)
        core.average_rank_similarity(history)
        self.assertEqual(history, original)
        bad_cases: list[list[list[list[float]]]] = [[], [[]], [[[0.5, 0.5]]], [[[0.0, 1.1]]],
                    [[[0.0, 1.0]], [[0.0, 1.0, 0.5]]], [[[0.0, math.nan]]]]
        for bad in bad_cases:
            with self.assertRaises(ValueError):
                core.average_rank_similarity(bad)

    def test_weights_stable_softmax_and_no_deduplication(self) -> None:
        identity = [[1.0, 0.0], [0.0, 1.0]]
        weights = core.conditional_expert_weights([10000.0, 10000.5], identity, 0.5)
        expected = 1 / (1 + math.e)
        self.assertAlmostEqual(weights[0], expected, places=14)
        self.assertAlmostEqual(math.fsum(weights), 1.0, places=15)
        self.assertEqual(core.conditional_expert_weights([1e308, -1e308], identity), [1.0, 0.0])
        duplicate = [[1.0, 1.0, 0.0], [1.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        self.assertEqual(core.conditional_expert_weights([0.0] * 3, duplicate, deduplicate=False), [1 / 3] * 3)

    def test_exact_duplicate_orthogonal_family_does_not_multiply_mass(self) -> None:
        pair = [[1.0, 0.0], [0.0, 1.0]]
        triple = [[1.0, 1.0, 0.0], [1.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        original = core.conditional_expert_weights([0.0, 0.0], pair)
        repeated = core.conditional_expert_weights([0.0, 0.0, 0.0], triple)
        self.assertEqual(repeated, [0.25, 0.25, 0.5])
        self.assertEqual(math.fsum(repeated[:2]), original[0])
        self.assertEqual(repeated[2], original[1])

    def test_soft_discount_is_not_universal_clone_invariance(self) -> None:
        before = core.conditional_expert_weights([0.0, 0.0], [[1.0, 0.5], [0.5, 1.0]])
        matrix = [[1.0, 1.0, 0.5], [1.0, 1.0, 0.5], [0.5, 0.5, 1.0]]
        after = core.conditional_expert_weights([0.0] * 3, matrix)
        self.assertNotAlmostEqual(sum(after[:2]), before[0])
        self.assertEqual(core.conditional_expert_weights([0.0] * 4, [[1.0] * 4 for _ in range(4)]), [0.25] * 4)

    def test_weight_validation_and_input_not_mutated(self) -> None:
        scores, matrix = [0.0, 1.0], [[1.0, 0.5], [0.5, 1.0]]
        original = copy.deepcopy((scores, matrix))
        core.conditional_expert_weights(scores, matrix)
        self.assertEqual((scores, matrix), original)
        for scores_bad, matrix_bad, temperature in [([], matrix, 0.5), ([math.nan, 0.0], matrix, 0.5),
                (scores, [[1.0]], 0.5), (scores, [[1.0, 0.3], [0.4, 1.0]], 0.5),
                (scores, [[1.0, -0.1], [-0.1, 1.0]], 0.5), (scores, [[0.9, 0.1], [0.1, 1.0]], 0.5),
                (scores, matrix, 0.0), (scores, matrix, -1.0), (scores, matrix, math.inf)]:
            with self.assertRaises(ValueError):
                core.conditional_expert_weights(scores_bad, matrix_bad, temperature)


class FusionTests(unittest.TestCase):
    def test_equal_five_experts_integer_borda_ties(self) -> None:
        # 五个循环排列让各号码得到不同分数组合，但总和均为10。
        values = [4, 2, 5, 3, 1]
        rankings = [values[offset:] + values[:offset] for offset in range(5)]
        self.assertEqual(core.fuse_expert_rankings(rankings, [0.2] * 5, 5), [1, 2, 3, 4, 5])

    def test_one_hot_and_equal_opposites_tie_break(self) -> None:
        rankings = [[3, 2, 1, 4], [4, 1, 2, 3]]
        self.assertEqual(core.fuse_expert_rankings(rankings, [1.0, 0.0], 4), rankings[0])
        self.assertEqual(core.fuse_expert_rankings(rankings, [0.0, 1.0], 4), rankings[1])
        self.assertEqual(core.fuse_expert_rankings(rankings, [0.5, 0.5], 4), [1, 2, 3, 4])

    def test_matches_direct_normalized_borda_and_reproducible(self) -> None:
        rankings = [[4, 3, 2, 1], [1, 2, 3, 4], [2, 4, 1, 3]]
        weights = [0.2, 0.5, 0.3]
        originals = copy.deepcopy((rankings, weights))
        expected = sorted(range(1, 5), key=lambda number: (
            -math.fsum(w * (3 - rank.index(number)) / 3 for rank, w in zip(rankings, weights)), number))
        actual = core.fuse_expert_rankings(rankings, weights, 4)
        self.assertEqual(actual, expected)
        self.assertEqual(actual, core.fuse_expert_rankings(rankings, weights, 4))
        self.assertEqual((rankings, weights), originals)

    def test_invalid_ranking_and_weights(self) -> None:
        for rankings, weights, maximum in [([], [], 4), ([[1, 2]], [1.0], 1),
                ([[1, 2]], [1.0], 3), ([[1, 1]], [1.0], 2), ([[0, 1]], [1.0], 2),
                ([[1, 2]], [0.9], 2), ([[1, 2]], [math.nan], 2),
                ([[1, 2], [2, 1]], [-1.0, 2.0], 2), ([[1, 2]], [0.5, 0.5], 2)]:
            with self.assertRaises(ValueError):
                core.fuse_expert_rankings(rankings, weights, maximum)


def synthetic_records(count=230):
    """每年 150 个有效日期；合成号码不借用真实开奖结果。"""
    rng = random.Random(731)
    rows = []
    for index in range(count):
        year, offset = 2023 + index // 150, index % 150
        rows.append({"id": f"{year % 100:02d}{offset + 1:03d}",
                     "date": (date(year, 1, 1) + timedelta(days=2 * offset)).isoformat(),
                     "left": tuple(sorted(rng.sample(range(1, 36), 5))),
                     "right": tuple(sorted(rng.sample(range(1, 13), 2)))})
    return rows


class ResearchTests(unittest.TestCase):
    records: list[research.Record]
    target: str
    result: research.Record

    @classmethod
    def setUpClass(cls):
        cls.records = synthetic_records()
        cls.target = "24071"
        cls.result = research.generate_research(cls.records, cls.target)

    def test_schema_scope_cutoff_and_disclaimers(self):
        result = self.result
        self.assertEqual(result["kind"], "research")
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["history"], {"start_issue": "23001", "start_date": "2023-01-01",
                                           "first_id": "23001", "last_id": "24070", "rows": 220})
        self.assertEqual(result["learning"], {"rows": 120, "first_id": "23101", "last_id": "24070"})
        self.assertEqual(result["cutoff"]["training_last_id"], "24070")
        self.assertEqual(result["cutoff"]["excluded_future"], 10)
        self.assertEqual(result["parameters"], {"ridge": 10.0, "temperature": 0.5, "variant": "conditional_dedup"})
        self.assertEqual(result["prediction_gate"], "CLOSED")
        self.assertFalse(result["predictive_advantage_claim"])
        self.assertTrue(result["score_not_probability"])
        self.assertIn("不是对任意历史目标期事先预注册", " ".join(result["warnings"]))
        self.assertIn("未显示统计显著优势", " ".join(result["warnings"]))

    def test_deterministic_no_input_mutation_and_json_roundtrip(self):
        original = copy.deepcopy(self.records)
        result = research.generate_research(self.records, self.target)
        self.assertEqual(result, self.result)
        self.assertEqual(original, self.records)
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)

    def test_current_and_future_outcomes_cannot_affect_any_result(self):
        changed = copy.deepcopy(self.records)
        for row in changed:
            if row["id"] >= self.target:
                row["left"], row["right"] = (1, 2, 3, 4, 5), (1, 2)
        self.assertEqual(research.generate_research(changed, self.target), self.result)
        # Even unvalidated outcome payloads in excluded rows cannot enter the model.
        for row in changed:
            if row["id"] >= self.target:
                row["left"], row["right"] = (), ()
        self.assertEqual(research.generate_research(changed, self.target), self.result)

    def test_added_future_and_old_draws_only_change_cutoff_audit(self):
        old = {"id": "13001", "date": "2013-01-01", "left": (1, 2, 3, 4, 5), "right": (1, 2)}
        boundary = {**old, "id": "22150", "date": "2022-12-31"}
        changed = research.generate_research([old, boundary, *synthetic_records(250)], self.target)
        self.assertEqual(changed["cutoff"]["excluded_before_start"], 2)
        self.assertEqual(changed["cutoff"]["excluded_future"], 30)
        self.assertEqual({k: v for k, v in changed.items() if k != "cutoff"},
                         {k: v for k, v in self.result.items() if k != "cutoff"})

    def test_minimum_200_history_requires_100_learning_rows(self):
        for count in (99, 100, 199):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, "至少需要 200 期"):
                research.generate_research(synthetic_records(count), self.target)
        result = research.generate_research(synthetic_records(200), self.target)
        self.assertEqual(result["learning"]["rows"], 100)
        self.assertEqual(result["history"]["rows"], 200)
        with self.assertRaisesRegex(ValueError, "2023-01-01"):
            research.generate_research(self.records, "23001")

    def test_learning_features_and_ranks_precede_own_label(self):
        history = self.records[:202]
        samples = research._build_learning_rows(history)
        self.assertEqual(len(samples), 102)
        for sample in samples:
            self.assertLess(sample["training_last_id"], sample["target"])
            self.assertLess(sample["target"], self.target)
        changed = copy.deepcopy(history)
        changed[100]["left"], changed[100]["right"] = (31, 32, 33, 34, 35), (11, 12)
        rebuilt = research._build_learning_rows(changed)
        for key in ("x", "rankings", "rank_vectors", "training_last_id"):
            self.assertEqual(rebuilt[0][key], samples[0][key])
        self.assertNotEqual(rebuilt[0]["y"], samples[0]["y"])

    def test_standardization_fit_and_similarity_only_receive_prior_rows(self):
        with patch.object(core, "fit_conditional_scores", wraps=core.fit_conditional_scores) as fit, \
             patch.object(core, "average_rank_similarity", wraps=core.average_rank_similarity) as similarity:
            research.generate_research(self.records, self.target)
        self.assertEqual(len(fit.call_args.args[0]), 120)
        self.assertEqual(len(fit.call_args.args[1]), 120)
        self.assertEqual(fit.call_args.args[2], 10.0)
        self.assertEqual(len(similarity.call_args.args[0]), 120)

    def test_weights_finite_normalized_and_complete_rankings(self):
        result = self.result
        self.assertEqual([row["name"] for row in result["experts"]], list(research.NAMES))
        for field in ("weight", "raw_weight"):
            weights = [row[field] for row in result["experts"]]
            self.assertTrue(all(math.isfinite(value) and value >= 0 for value in weights))
            self.assertAlmostEqual(math.fsum(weights), 1.0, places=14)
        self.assertTrue(all(math.isfinite(row["predicted_reward"]) for row in result["experts"]))
        self.assertEqual([row["name"] for row in result["features"]], list(research.FEATURE_NAMES))
        self.assertTrue(all(math.isfinite(row["value"]) for row in result["features"]))
        for zone, maximum in (("left", 35), ("right", 12)):
            self.assertEqual(sorted(result["fused_rankings"][zone]), list(range(1, maximum + 1)))
        for i, row in enumerate(result["similarity"]):
            self.assertEqual(row[i], 1)
            self.assertEqual(result["experts"][i]["similarity_density"], math.fsum(row))
            for j, value in enumerate(row):
                self.assertTrue(0 <= value <= 1)
                self.assertEqual(value, result["similarity"][j][i])

    def test_pool_sizes_exact_count_cost_and_probability(self):
        for size, counts, units in (("5+2", (5, 2), 1), ("5+5", (5, 5), 10),
                                    ("7+3", (7, 3), 63), ("8+3", (8, 3), 168)):
            with self.subTest(size=size):
                result = research.generate_research(self.records, self.target, size)
                pool = result["pool"]
                self.assertEqual((len(pool["left"]), len(pool["right"])), counts)
                self.assertEqual(pool["size"], size)
                self.assertEqual(pool["basic_combinations"], units)
                self.assertEqual(pool["basic_cost_yuan"], 2 * units)
                self.assertEqual(pool["joint_probability"], {"numerator": units, "denominator": 21425712})
                self.assertEqual(result["fused_rankings"], self.result["fused_rankings"])
                self.assertEqual(result["experts"], self.result["experts"])
                self.assertEqual(pool["left"], sorted(pool["left"]))
                self.assertEqual(pool["right"], sorted(pool["right"]))

    def test_full_historical_combination_is_not_excluded(self):
        history = synthetic_records(200)
        for row in history:
            row["left"], row["right"] = (1, 2, 3, 4, 5), (1, 2)
        result = research.generate_research(history, self.target)
        self.assertEqual(result["pool"]["left"], [1, 2, 3, 4, 5])
        self.assertEqual(result["pool"]["right"], [1, 2])

    def test_reject_invalid_target_pool_and_corrupt_history(self):
        bad_targets: list[Any] = ["24000", "２４０７１", "2407", "240710", True]
        for target in bad_targets:
            with self.subTest(target=target), self.assertRaises(ValueError):
                research.generate_research(self.records, target)
        bad_sizes: list[Any] = ["5+3", "35+12", "7+03", None, True]
        for size in bad_sizes:
            with self.subTest(size=size), self.assertRaises(ValueError):
                research.generate_research(self.records, self.target, size)
        for field, value in (("id", "23001"), ("date", "2023-01-01"),
                             ("left", (1, 1, 3, 4, 5)), ("right", (12, 1))):
            changed = copy.deepcopy(self.records)
            changed[1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                research.generate_research(changed, self.target)
        with self.assertRaisesRegex(ValueError, "严格递增"):
            research.generate_research(list(reversed(self.records)), self.target)

    def test_constant_history_feature_definition(self):
        history = synthetic_records(100)
        for row in history:
            row["left"], row["right"] = (1, 2, 3, 4, 5), (1, 2)
        values = research._history_features(history)
        for actual, expected in zip(values, [0, 1 / 5, 30 / 35, 1, 1, 0, 1 / 2, 10 / 12, 1, 1]):
            self.assertAlmostEqual(actual, expected, places=14)


if __name__ == "__main__":
    unittest.main(verbosity=2)

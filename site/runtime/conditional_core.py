"""历史条件成绩学习、正向秩相关软去冗余与排名融合；权重不是中奖概率。"""
from __future__ import annotations

import math


def _cf_vector(value: object, label: str, length: int | None = None) -> list[float]:
    """复制并校验数值向量，不接受布尔、非有限值或隐式字符串转换。"""
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"{label}必须为非空数值向量")
    result = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError(f"{label}包含非数值")
        number = float(item)
        if not math.isfinite(number):
            raise ValueError(f"{label}包含非有限值")
        result.append(number)
    if length is not None and len(result) != length:
        raise ValueError(f"{label}维度不一致")
    return result


def _cf_matrix(value: object, label: str) -> list[list[float]]:
    """复制并校验非空矩形矩阵。"""
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError(f"{label}必须为非空矩阵")
    first = _cf_vector(value[0], label)
    return [first, *[_cf_vector(row, label, len(first)) for row in value[1:]]]


def _cf_mean(values: list[float]) -> float:
    """先除样本数再求和，避免有限大数求均值时无谓溢出。"""
    result = math.fsum(value / len(values) for value in values)
    if not math.isfinite(result):
        raise ValueError("均值计算超出有限数值范围")
    return result


def _cf_solve_spd(matrix: list[list[float]], rhs: list[list[float]]) -> list[list[float]]:
    """Cholesky同时求解多个目标；失败明确报错，不伪造有效系数。"""
    size, outputs = len(matrix), len(rhs[0])
    lower = [[0.0] * size for _ in range(size)]
    for i in range(size):
        for j in range(i + 1):
            residual = matrix[i][j] - math.fsum(lower[i][k] * lower[j][k] for k in range(j))
            if not math.isfinite(residual):
                raise ValueError("岭回归矩阵计算产生非有限值")
            if i == j:
                if residual <= 0:
                    raise ValueError("岭回归矩阵数值上非正定；检查输入或正则化强度")
                lower[i][j] = math.sqrt(residual)
            else:
                lower[i][j] = residual / lower[j][j]
    intermediate = [[0.0] * outputs for _ in range(size)]
    for i in range(size):
        for output in range(outputs):
            intermediate[i][output] = (rhs[i][output] - math.fsum(
                lower[i][j] * intermediate[j][output] for j in range(i))) / lower[i][i]
    coefficients = [[0.0] * outputs for _ in range(size)]
    for i in range(size - 1, -1, -1):
        for output in range(outputs):
            coefficients[i][output] = (intermediate[i][output] - math.fsum(
                lower[j][i] * coefficients[j][output] for j in range(i + 1, size))) / lower[i][i]
    if any(not math.isfinite(value) for row in coefficients for value in row):
        raise ValueError("岭回归系数非有限值")
    return coefficients


def fit_conditional_scores(X: list[list[float]], Y: list[list[float]], ridge: float) -> dict[str, object]:
    """拟合多专家条件预期成绩；只使用传入训练样本，无文件或全局历史读取。

    目标为残差平方和加ridge乘系数平方和，不除样本数。训练总体标准差用于
    特征标准化，常量特征scale=1；目标中心化等价于不惩罚截距。
    调用方必须保证所有训练样本及其事后成绩严格早于预测期。
    """
    x_rows = _cf_matrix(X, "X")
    y_rows = _cf_matrix(Y, "Y")
    strength = _cf_vector([ridge], "ridge")[0]
    if strength <= 0:
        raise ValueError("ridge必须大于0")
    if len(x_rows) != len(y_rows):
        raise ValueError("X和Y样本数不一致")
    n, features, outputs = len(x_rows), len(x_rows[0]), len(y_rows[0])
    x_mean = [_cf_mean([row[j] for row in x_rows]) for j in range(features)]
    y_mean = [_cf_mean([row[j] for row in y_rows]) for j in range(outputs)]
    centered_x = [[row[j] - x_mean[j] for j in range(features)] for row in x_rows]
    centered_y = [[row[j] - y_mean[j] for j in range(outputs)] for row in y_rows]
    if any(not math.isfinite(v) for row in centered_x + centered_y for v in row):
        raise ValueError("中心化数据超出有限数值范围")
    x_scale = []
    for j in range(features):
        peak = max(abs(row[j]) for row in centered_x)
        scale = peak * math.sqrt(math.fsum((row[j] / peak) ** 2 for row in centered_x) / n) if peak else 1.0
        x_scale.append(scale if scale else 1.0)
    standardized = [[row[j] / x_scale[j] for j in range(features)] for row in centered_x]
    gram = [[math.fsum(row[i] * row[j] for row in standardized)
             + (strength if i == j else 0.0) for j in range(features)] for i in range(features)]
    rhs = [[math.fsum(standardized[s][j] * centered_y[s][m] for s in range(n))
            for m in range(outputs)] for j in range(features)]
    coefficients = _cf_solve_spd(gram, rhs)
    return {"x_mean": x_mean, "x_scale": x_scale, "y_mean": y_mean,
            "coefficients": coefficients, "ridge": strength, "n_samples": n,
            "feature_count": features, "output_count": outputs,
            "objective": "sum_squared_error + ridge * sum_squared_coefficients; unpenalized intercept",
            "score_note": "条件预期成绩估计，不是中奖概率；历史时序由调用方严格约束"}


def predict_conditional_scores(state: dict[str, object], x: list[float]) -> list[float]:
    """使用训练阶段保存的均值/尺度，绝不根据当前输入重新拟合。"""
    means = _cf_vector(state.get("x_mean"), "x_mean")
    scales = _cf_vector(state.get("x_scale"), "x_scale", len(means))
    target_means = _cf_vector(state.get("y_mean"), "y_mean")
    coefficients = _cf_matrix(state.get("coefficients"), "coefficients")
    values = _cf_vector(x, "x", len(means))
    if any(scale <= 0 for scale in scales):
        raise ValueError("x_scale必须全部大于0")
    if len(coefficients) != len(means) or len(coefficients[0]) != len(target_means):
        raise ValueError("系数和状态维度不一致")
    standardized = [(value - mean) / scale for value, mean, scale in zip(values, means, scales)]
    if any(not math.isfinite(value) for value in standardized):
        raise ValueError("预测标准化产生非有限值")
    result = [target_means[m] + math.fsum(standardized[j] * coefficients[j][m] for j in range(len(means)))
              for m in range(len(target_means))]
    if any(not math.isfinite(value) for value in result):
        raise ValueError("条件成绩预测产生非有限值")
    return result


def average_rank_similarity(rank_vectors_history: list[list[list[float]]]) -> list[list[float]]:
    """历史统一排名分数先减0.5，再计算余弦；历史均值取正部，保留对角1。

    正式向量为前35及后12号码的标准化完整排名分数，均值恰为0.5。
    输入只应含过去已保存的专家预测，不含当前/未来期。不能先逐期截负后平均。
    此矩阵仅描述预测的正向相似性，不证明模型独立或存在预测优势。
    """
    if not isinstance(rank_vectors_history, (list, tuple)) or not rank_vectors_history:
        raise ValueError("排名历史必须非空")
    first = _cf_matrix(rank_vectors_history[0], "rank_vectors")
    experts, dimensions = len(first), len(first[0])
    totals = [[0.0] * experts for _ in range(experts)]
    for raw in rank_vectors_history:
        vectors = _cf_matrix(raw, "rank_vectors")
        if len(vectors) != experts or len(vectors[0]) != dimensions:
            raise ValueError("排名历史维度不一致")
        if any(value < 0 or value > 1 for vector in vectors for value in vector):
            raise ValueError("统一排名分数必须在[0,1]内")
        centered = [[value - 0.5 for value in vector] for vector in vectors]
        norms = [math.sqrt(math.fsum(value * value for value in vector)) for vector in centered]
        if any(norm == 0 for norm in norms):
            raise ValueError("中心化排名向量不能为全零")
        for i in range(experts):
            for j in range(i):
                # 数学上相同或正负相反的向量给出精确端点，避免开方舍入破坏恒等式。
                if centered[i] == centered[j]:
                    cosine = 1.0
                elif all(a == -b for a, b in zip(centered[i], centered[j])):
                    cosine = -1.0
                else:
                    cosine = math.fsum(a * b for a, b in zip(centered[i], centered[j])) / (norms[i] * norms[j])
                totals[i][j] += min(1.0, max(-1.0, cosine))
    result = [[0.0] * experts for _ in range(experts)]
    for i in range(experts):
        result[i][i] = 1.0
        for j in range(i):
            value = min(1.0, max(0.0, totals[i][j] / len(rank_vectors_history)))
            result[i][j] = result[j][i] = value
    return result


def conditional_expert_weights(predicted_scores: list[float], similarity: list[list[float]],
                               temperature: float = 0.5, deduplicate: bool = True) -> list[float]:
    """softmax条件成绩后按正向相似密度软降权；权重不是概率预测。

    density_i=sum_j similarity_ij，含对角1；w_i正比于softmax_i/density_i。
    这只是软去冗余，不保证删除全部相关，亦不普遍保证复制某专家后族总权重不变。
    """
    scores = _cf_vector(predicted_scores, "predicted_scores")
    matrix = _cf_matrix(similarity, "similarity")
    temp = _cf_vector([temperature], "temperature")[0]
    if temp <= 0 or type(deduplicate) is not bool:
        raise ValueError("temperature必须大于0且deduplicate必须为布尔")
    size = len(scores)
    if len(matrix) != size or len(matrix[0]) != size:
        raise ValueError("相似度矩阵必须与专家数匹配")
    if any(value < 0 or value > 1 for row in matrix for value in row):
        raise ValueError("相似度必须在[0,1]内")
    for i in range(size):
        if not math.isclose(matrix[i][i], 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("相似度对角必须为1")
        for j in range(i):
            if not math.isclose(matrix[i][j], matrix[j][i], rel_tol=0.0, abs_tol=1e-9):
                raise ValueError("相似度矩阵必须对称")
    highest = max(scores)
    raw = [math.exp((value - highest) / temp) for value in scores]
    if deduplicate:
        raw = [value / math.fsum(matrix[i]) for i, value in enumerate(raw)]
    total = math.fsum(raw)
    return [value / total for value in raw]


def fuse_expert_rankings(rankings: list[list[int]], weights: list[float], maximum: int) -> list[int]:
    """融合完整区内排序，返回1..maximum全排列；同分小号优先。

    使用加权Borda整数分计算排序，与统一分数(M-r)/(M-1)加权完全同序，
    同一区共有的除数无需反复计算。不会把排名融合分数输出为中奖概率。
    """
    if type(maximum) is not int or maximum < 2:
        raise ValueError("maximum必须为至少2的整数")
    if not isinstance(rankings, (list, tuple)) or not rankings:
        raise ValueError("rankings必须非空")
    numeric_weights = _cf_vector(weights, "weights", len(rankings))
    total = math.fsum(numeric_weights)
    if any(weight < 0 for weight in numeric_weights) or not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("权重必须非负且和为1")
    expected = set(range(1, maximum + 1))
    positions = []
    for ranking in rankings:
        if not isinstance(ranking, (list, tuple)) or any(type(number) is not int for number in ranking):
            raise ValueError("排名必须为整数序列")
        if len(ranking) != maximum or set(ranking) != expected:
            raise ValueError("每个专家必须提供1..maximum的完整排列")
        positions.append({number: rank for rank, number in enumerate(ranking, start=1)})
    if all(weight == numeric_weights[0] for weight in numeric_weights):
        # 完全等权时直接使用整数Borda，确保数学同分严格按小号排序。
        integer_scores = {number: sum(maximum - position[number] for position in positions)
                          for number in range(1, maximum + 1)}
        return sorted(integer_scores, key=lambda number: (-integer_scores[number], number))
    scores = {number: math.fsum(weight * (maximum - position[number]) / total
                                for weight, position in zip(numeric_weights, positions))
              for number in range(1, maximum + 1)}
    return sorted(scores, key=lambda number: (-scores[number], number))

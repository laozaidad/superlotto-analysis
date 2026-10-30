/** 独立研究契约：排名权重不作为概率，号码池不冒充单式组合。 */
/** @typedef {{name:string,weight:number,raw_weight:number,predicted_reward:number,similarity_density:number}} Expert */
/** @typedef {{schema_version:number,kind:string,model_version:string,target:string,history:{start_issue:string,start_date:string,first_id:string,last_id:string,rows:number},cutoff:Record<string,any>,learning:{rows:number,first_id:string,last_id:string},parameters:{ridge:number,temperature:number,variant:string},experts:Expert[],features:{name:string,value:number}[],similarity:number[][],fused_rankings:{left:number[],right:number[]},pool:{size:string,left:number[],right:number[],basic_combinations:number,basic_cost_yuan:number,joint_probability:{numerator:number,denominator:number}},warnings:string[],runtime?:{data_origin:string,python_version:string,pyodide_version:string,model_sha256:string,research_sha256:string,conditional_core_sha256:string,data_sha256:string}}} ResearchResult */
/** @typedef {{schema_version:number,scope:{start_issue:string,start_date:string},test:{first_id:string,last_id:string,periods:number},status:string,prediction_gate:string,historical_data_previously_seen:boolean,verification:string,source_hashes:Record<string,string>,random_expected:{left:number,right:number},comparisons:{variant:string,label:string,left_hits:number,right_hits:number,full_coverage_count:number,p_left_adjusted:number,p_right_adjusted:number}[],multiple_testing:{method:string,family_size:number},limitations:string[]}} Evidence */

export const POOL_SIZES = Object.freeze({
  "5+2": [5, 2],
  "5+5": [5, 5],
  "7+3": [7, 3],
  "8+3": [8, 3],
});
export const OUTCOME_SPACE = 21425712;
export const EXPERT_NAMES = Object.freeze([
  "legacy_blend",
  "shrink20",
  "shrink100",
  "shrink_all",
  "gap_rank",
]);
export const FEATURE_NAMES = Object.freeze(
  ["left", "right"].flatMap((zone) =>
    [
      "freq20_vs100_rms",
      "concentration20",
      "mean_gap_div100",
      "max_gap_div100",
      "repeat20_share",
    ].map((name) => `${zone}_${name}`),
  ),
);
/** @param {unknown} ok @param {string} message @returns {asserts ok} */
function requireValue(ok, message) {
  if (!ok) throw new Error(message);
}
/** @param {unknown} value @returns {Record<string,any>} */
function object(value) {
  requireValue(
    value !== null && typeof value === "object" && !Array.isArray(value),
    "研究数据必须为对象",
  );
  return /** @type {Record<string,any>} */ (value);
}
/** @param {unknown} value @param {number} min @param {number} max */
function integer(value, min, max) {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= min &&
    value <= max
  );
}
/** @param {unknown} value */
function issue(value) {
  return (
    typeof value === "string" &&
    /^\d{5}$/.test(value) &&
    Number(value) >= 23001 &&
    Number(value.slice(2)) > 0
  );
}
/** @param {unknown} value @param {number} [limit] */
function text(value, limit = 160) {
  return (
    typeof value === "string" &&
    value.trim().length > 0 &&
    value.length <= limit
  );
}
/** @param {unknown} value */
function warnings(value) {
  return (
    Array.isArray(value) &&
    value.length <= 40 &&
    value.every((item) => text(item, 2000))
  );
}
/** @param {unknown} values @param {number} size @param {number} maximum @param {boolean} [sorted] @returns {number[]} */
function numbers(values, size, maximum, sorted = true) {
  requireValue(
    Array.isArray(values) &&
      values.length === size &&
      values.every(
        (n, i) =>
          integer(n, 1, maximum) && (!sorted || i === 0 || n > values[i - 1]),
      ) &&
      new Set(values).size === size,
    "研究号码池或完整排名不合法",
  );
  return values;
}
/** @param {number} n @param {number} k */
export function combinations(n, k) {
  let count = 1;
  for (let i = 1; i <= k; i++) count = (count * (n - i + 1)) / i;
  return Math.round(count);
}
/** @param {unknown} input @returns {ResearchResult} */
export function validateResearchResult(input) {
  const r = object(input),
    h = object(r.history),
    c = object(r.cutoff),
    learning = object(r.learning),
    params = object(r.parameters),
    pool = object(r.pool),
    ranking = object(r.fused_rankings);
  requireValue(
    r.schema_version === 1 &&
      r.kind === "research" &&
      r.model_version === "conditional-fusion-v1",
    "不支持的研究结果版本",
  );
  requireValue(
    r.prediction_gate === "CLOSED" &&
      r.predictive_advantage_claim === false &&
      r.score_not_probability === true,
    "研究结果必须明确无已验证预测优势，权重不是概率",
  );
  requireValue(
    issue(r.target) &&
      h.start_issue === "23001" &&
      h.start_date === "2023-01-01" &&
      issue(h.first_id) &&
      issue(h.last_id) &&
      h.first_id <= h.last_id &&
      h.last_id < r.target &&
      integer(h.rows, 200, 1000000),
    "研究历史范围或目标期截断不合法",
  );
  requireValue(
    c.target === r.target &&
      c.history_start_issue === "23001" &&
      c.history_start_date === "2023-01-01" &&
      c.training_rows === h.rows &&
      c.training_first_id === h.first_id &&
      c.training_last_id === h.last_id,
    "研究截断审计与历史不一致",
  );
  requireValue(
    integer(c.excluded_before_start, 0, 1000000) &&
      integer(c.excluded_future, 0, 1000000),
    "研究截断排除计数必须是非负整数",
  );
  requireValue(
    integer(learning.rows, 100, h.rows) &&
      learning.rows === h.rows - 100 &&
      issue(learning.first_id) &&
      issue(learning.last_id) &&
      learning.first_id > h.first_id &&
      learning.first_id <= learning.last_id &&
      learning.last_id === h.last_id,
    "学习样本必须来自目标期之前的有效历史",
  );
  requireValue(
    params.ridge === 10 &&
      params.temperature === 0.5 &&
      params.variant === "conditional_dedup",
    "研究参数与冻结配置不一致",
  );
  requireValue(
    Array.isArray(r.experts) && r.experts.length === 5,
    "研究需要五个专家权重",
  );
  const names = new Set();
  let weight = 0,
    rawWeight = 0;
  for (const [index, item] of r.experts.entries()) {
    const e = object(item);
    requireValue(
      e.name === EXPERT_NAMES[index] &&
        !names.has(e.name) &&
        Number.isFinite(e.weight) &&
        e.weight >= 0 &&
        e.weight <= 1 &&
        Number.isFinite(e.raw_weight) &&
        e.raw_weight >= 0 &&
        e.raw_weight <= 1 &&
        Number.isFinite(e.predicted_reward) &&
        Number.isFinite(e.similarity_density) &&
        e.similarity_density >= 1 - 1e-8 &&
        e.similarity_density <= 5 + 1e-8,
      "专家权重或评分不合法",
    );
    names.add(e.name);
    weight += e.weight;
    rawWeight += e.raw_weight;
  }
  requireValue(
    Math.abs(weight - 1) < 1e-8 && Math.abs(rawWeight - 1) < 1e-8,
    "专家权重必须归一化",
  );
  const highest = Math.max(...r.experts.map((e) => e.predicted_reward));
  const softmax = r.experts.map((e) =>
    Math.exp((e.predicted_reward - highest) / params.temperature),
  );
  const softmaxTotal = softmax.reduce((a, b) => a + b, 0);
  requireValue(
    softmax.every(
      (value, i) =>
        Math.abs(value / softmaxTotal - r.experts[i].raw_weight) < 1e-8,
    ),
    "原始权重必须对应冻结温度下的条件成绩softmax",
  );
  requireValue(
    Array.isArray(r.features) &&
      r.features.length === 10 &&
      r.features.every(
        (f, i) => f?.name === FEATURE_NAMES[i] && Number.isFinite(f?.value),
      ) &&
      new Set(r.features.map((f) => f.name)).size === 10,
    "历史特征不合法",
  );
  requireValue(
    Array.isArray(r.similarity) &&
      r.similarity.length === 5 &&
      r.similarity.every(
        (row) =>
          Array.isArray(row) &&
          row.length === 5 &&
          row.every((v) => Number.isFinite(v) && v >= 0 && v <= 1 + 1e-8),
      ),
    "相似矩阵不合法",
  );
  for (let i = 0; i < 5; i++)
    for (let j = 0; j < 5; j++)
      requireValue(
        Math.abs(r.similarity[i][j] - r.similarity[j][i]) < 1e-8 &&
          (i !== j || Math.abs(r.similarity[i][i] - 1) < 1e-8),
        "相似矩阵必须对称且对角为1",
      );
  for (let i = 0; i < 5; i++)
    requireValue(
      Math.abs(
        r.experts[i].similarity_density -
          r.similarity[i].reduce(
            (/** @type {number} */ sum, /** @type {number} */ v) => sum + v,
            0,
          ),
      ) < 1e-8,
      "相似密度必须等于对应矩阵行和",
    );
  const discounted = r.experts.map((e) => e.raw_weight / e.similarity_density),
    totalDiscounted = discounted.reduce((a, b) => a + b, 0);
  requireValue(
    totalDiscounted > 0 &&
      discounted.every(
        (w, i) => Math.abs(w / totalDiscounted - r.experts[i].weight) < 1e-8,
      ),
    "最终权重必须对应归一化软去冗余结果",
  );
  const leftRank = numbers(ranking.left, 35, 35, false),
    rightRank = numbers(ranking.right, 12, 12, false);
  requireValue(
    typeof pool.size === "string" && Object.hasOwn(POOL_SIZES, pool.size),
    "不支持的研究号码池规格",
  );
  const [m, n] = POOL_SIZES[/** @type {keyof typeof POOL_SIZES} */ (pool.size)];
  const left = numbers(pool.left, m, 35),
    right = numbers(pool.right, n, 12);
  requireValue(
    JSON.stringify(left) ===
      JSON.stringify(leftRank.slice(0, m).sort((a, b) => a - b)) &&
      JSON.stringify(right) ===
        JSON.stringify(rightRank.slice(0, n).sort((a, b) => a - b)),
    "号码池必须对应融合排名前列",
  );
  const count = combinations(m, 5) * combinations(n, 2),
    probability = object(pool.joint_probability);
  requireValue(
    pool.basic_combinations === count &&
      pool.basic_cost_yuan === count * 2 &&
      probability.numerator === count &&
      probability.denominator === OUTCOME_SPACE,
    "展开注数、基本成本或全覆盖概率不一致",
  );
  requireValue(
    warnings(r.warnings) && r.warnings.length > 0,
    "研究警告缺失或不合法",
  );
  if (r.runtime !== undefined) {
    const runtime = object(r.runtime);
    requireValue(
      ["local", "public"].includes(runtime.data_origin) &&
        text(runtime.python_version, 60) &&
        text(runtime.pyodide_version, 60) &&
        [
          "model_sha256",
          "research_sha256",
          "conditional_core_sha256",
          "data_sha256",
        ].every(
          (key) =>
            typeof runtime[key] === "string" &&
            /^[a-f0-9]{64}$/.test(runtime[key]),
        ),
      "研究运行时审计不合法",
    );
  }
  return /** @type {ResearchResult} */ (r);
}
/** @param {unknown} input @returns {Evidence} */
export function validateResearchEvidence(input) {
  const e = object(input),
    scope = object(e.scope),
    period = object(e.test),
    expected = object(e.random_expected),
    correction = object(e.multiple_testing),
    hashes = object(e.source_hashes);
  requireValue(
    e.schema_version === 1 &&
      scope.start_issue === "23001" &&
      scope.start_date === "2023-01-01",
    "研究证据范围不合法",
  );
  requireValue(
    e.status === "exploratory_no_advantage" &&
      e.prediction_gate === "CLOSED" &&
      e.historical_data_previously_seen === true &&
      e.verification === "recomputed_from_saved_walk_forward",
    "研究证据必须明确为已重复研究的探索性回测",
  );
  requireValue(
    period.first_id === "26001" &&
      period.last_id === "26123" &&
      period.periods === 123,
    "研究证据不属于冻结评估窗口",
  );
  requireValue(
    Number.isFinite(expected.left) &&
      Math.abs(expected.left - (123 * 25) / 35) < 1e-6 &&
      expected.right === 41,
    "研究随机对照不一致",
  );
  requireValue(
    correction.method === "Bonferroni" && correction.family_size === 66,
    "多重比较校正信息不一致",
  );
  requireValue(
    Object.keys(hashes).length > 0 &&
      Object.values(hashes).every(
        (hash) => typeof hash === "string" && /^[a-f0-9]{64}$/.test(hash),
      ),
    "研究证据来源哈希不合法",
  );
  requireValue(
    Array.isArray(e.comparisons) &&
      e.comparisons.length === 3 &&
      new Set(e.comparisons.map((row) => row?.variant)).size ===
        e.comparisons.length,
    "研究比较项不合法",
  );
  const variants = [
    "equal_rank_fusion",
    "conditional_no_dedup",
    "conditional_dedup",
  ];
  for (const raw of e.comparisons) {
    const row = object(raw);
    requireValue(
      variants.includes(row.variant) && row.size === "5+2" && row.n === 123,
      "研究比较规格或样本数与冻结窗口不一致",
    );
    requireValue(
      text(row.variant) &&
        text(row.label) &&
        integer(row.left_hits, 0, 615) &&
        integer(row.right_hits, 0, 246) &&
        integer(row.full_coverage_count, 0, 123) &&
        Number.isFinite(row.p_left_adjusted) &&
        row.p_left_adjusted >= 0.05 &&
        row.p_left_adjusted <= 1 &&
        Number.isFinite(row.p_right_adjusted) &&
        row.p_right_adjusted >= 0.05 &&
        row.p_right_adjusted <= 1,
      "研究累计命中或校正p值不合法",
    );
  }
  requireValue(
    warnings(e.limitations) && e.limitations.length > 0,
    "研究证据缺少局限说明",
  );
  return /** @type {Evidence} */ (e);
}

/** 展示层只校验、格式化现有模型输出，不实现另一套选号算法。 */
/** @typedef {{odd:number,even:number,small:number,large:number,sum:number,span:number,adjacent_pairs:number,max_run:number,repeat_previous:number,hot:number,warm:number,cold:number}} Features */
/** @typedef {{number:number,window:number,count:number,expected:number,sd:number,z:number,label:'hot'|'warm'|'cold',gap:number,gap_censored:boolean}} HeatEntry */
/** @typedef {{index:number,left:number[],right:number[],left_features:Features,right_features:Features}} Group */
/** @typedef {{mode:'coverage'|'uniform',seed:number,model_version:string,history_start_date:string,group_count:number,groups:Group[],coverage:{left_count:number,right_count:number},heat:{left:Record<string,HeatEntry>,right:Record<string,HeatEntry>},prediction_gate:string,predictive_advantage_claim:boolean,cutoff?:{target:string,training_rows:number,training_first_id:string,training_last_id:string,history_start_date:string,history_start_issue:string},web_distributions?:{left:Distribution,right:Distribution},quality_warnings?:string[],runtime?:{data_origin:string,python_version:string,pyodide_version:string,model_sha256:string}}} Portfolio */
/** @typedef {{value:number,count:number}} Bin */
/** @typedef {{odd:Bin[],small:Bin[],adjacent_pairs:Bin[],repeat_previous:Bin[],sample_sizes:Record<string,number>}} Distribution */
/** @typedef {{schema_version:number,generated_at:string,history:{rows:number,first_id:string,last_id:string,first_date:string,last_date:string,history_start_date:string,history_start_issue:string},source:{url:string|null,sha256:string,complete:boolean,warnings:string[]},portfolios:{coverage:Portfolio,uniform:Portfolio},distributions:{left:Distribution,right:Distribution}}} Snapshot */

/** @param {unknown} condition @param {string} message @returns {asserts condition} */
function requireValue(condition, message) {
  if (!condition) throw new Error(message);
}
/** @param {unknown} value @returns {Record<string, any>} */
function object(value) {
  requireValue(
    value !== null && typeof value === "object" && !Array.isArray(value),
    "JSON 必须为对象",
  );
  return /** @type {Record<string, any>} */ (value);
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
    /^[0-9]{5}$/.test(value) &&
    Number(value.slice(2)) > 0 &&
    Number(value) >= 23001
  );
}
/** @param {unknown} value */
function calendarDate(value) {
  if (
    typeof value !== "string" ||
    !/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(value) ||
    !Number.isFinite(Date.parse(value))
  )
    return false;
  const day = value.slice(0, 10),
    parsed = new Date(`${day}T00:00:00Z`);
  return (
    Number.isFinite(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === day
  );
}
/** @param {Portfolio} p @param {number} rows */
function validateWindows(p, rows) {
  requireValue(
    p.heat.left["1"].window === Math.min(rows, 100) &&
      p.heat.right["1"].window === Math.min(rows, 100),
    "冷热窗口与历史样本数不一致",
  );
  for (const zone of /** @type {const} */ (["left", "right"]))
    for (const h of Object.values(p.heat[zone]))
      requireValue(
        h.gap <= rows && (h.gap_censored ? h.gap === rows : h.gap < rows),
        "遗漏与历史样本数不一致",
      );
}
/** @param {unknown} values @param {number} length @param {number} maximum @returns {number[]} */
function numbers(values, length, maximum) {
  requireValue(
    Array.isArray(values) && values.length === length,
    "组合号码数量不正确",
  );
  requireValue(
    values.every(
      (n, i) => integer(n, 1, maximum) && (i === 0 || n > values[i - 1]),
    ),
    "号码必须合法、升序且不重复",
  );
  return values;
}
/** @param {unknown} input @param {number} maximum @param {number} size */
function validateHeat(input, maximum, size) {
  const data = object(input);
  let total = 0;
  let window = 0;
  for (let i = 1; i <= maximum; i++) {
    const h = object(data[i]);
    requireValue(
      h.number === i &&
        integer(h.window, 1, 100) &&
        integer(h.count, 0, h.window),
      "冷热统计的号码、窗口或次数不合法",
    );
    requireValue(i === 1 || h.window === window, "冷热统计窗口不一致");
    requireValue(
      Number.isFinite(h.z) &&
        integer(h.gap, 0, 1000000) &&
        typeof h.gap_censored === "boolean",
      "冷热统计缺少有效 z 值或遗漏",
    );
    const expected = (h.window * size) / maximum;
    const sd = Math.sqrt(((h.window * size) / maximum) * (1 - size / maximum));
    requireValue(
      Math.abs(h.z - (h.count - expected) / sd) < 1e-8,
      "冷热 z 值与频数不一致",
    );
    requireValue(
      h.label === (h.z >= 1 ? "hot" : h.z <= -1 ? "cold" : "warm"),
      "冷热标签与 z 值不一致",
    );
    window = h.window;
    total += h.count;
  }
  requireValue(total === window * size, "冷热频数总和不正确");
}
/** @param {unknown} input @returns {Portfolio} */
export function validatePortfolio(input) {
  const p = object(input);
  requireValue(
    p.mode === "coverage" || p.mode === "uniform",
    "不支持的组合策略",
  );
  requireValue(
    p.history_start_date === "2023-01-01",
    "只接受2023-01-01起的数据模型",
  );
  requireValue(
    p.prediction_gate === "CLOSED" && p.predictive_advantage_claim === false,
    "输出必须明确关闭预测准入，且不声称预测优势",
  );
  requireValue(
    Number.isSafeInteger(p.seed) && typeof p.model_version === "string",
    "缺少有效模型版本或随机种子",
  );
  requireValue(
    integer(p.group_count, 1, 100) &&
      Array.isArray(p.groups) &&
      p.groups.length === p.group_count,
    "网页支持1至100组有效组合",
  );
  const heat = object(p.heat);
  validateHeat(heat.left, 35, 5);
  validateHeat(heat.right, 12, 2);
  /** @type {Set<number>} */ const left = new Set();
  /** @type {Set<number>} */ const right = new Set();
  const full = new Set();
  for (const [index, raw] of p.groups.entries()) {
    const g = object(raw);
    requireValue(g.index === index + 1, "组号必须连续递增");
    const l = numbers(g.left, 5, 35),
      r = numbers(g.right, 2, 12);
    full.add([...l, ...r].join(","));
    l.forEach((n) => left.add(n));
    r.forEach((n) => right.add(n));
    for (const [
      zone,
      nums,
      maximum,
    ] of /** @type {['left'|'right',number[],number][]} */ ([
      ["left", l, 35],
      ["right", r, 12],
    ])) {
      const f = object(g[`${zone}_features`]);
      const odd = nums.filter((n) => n % 2 === 1).length,
        small = nums.filter((n) => n <= Math.floor(maximum / 2)).length;
      const adjacent = nums.filter(
        (n, i) => i > 0 && n === nums[i - 1] + 1,
      ).length;
      requireValue(
        f.odd === odd &&
          f.even === nums.length - odd &&
          f.small === small &&
          f.large === nums.length - small &&
          f.sum === nums.reduce((a, b) => a + b, 0) &&
          f.span === nums[nums.length - 1] - nums[0] &&
          f.adjacent_pairs === adjacent,
        "组合特征与号码不一致",
      );
      requireValue(
        integer(f.repeat_previous, 0, nums.length),
        "重号数量不合法",
      );
      for (const label of ["hot", "warm", "cold"])
        requireValue(
          f[label] === nums.filter((n) => heat[zone][n].label === label).length,
          "组合冷热数量不一致",
        );
    }
  }
  requireValue(full.size === p.group_count, "完整组合不能重复");
  const coverage = object(p.coverage);
  requireValue(
    coverage.left_count === left.size && coverage.right_count === right.size,
    "覆盖统计与组合不一致",
  );
  if (p.mode === "coverage")
    requireValue(
      p.group_count <= 6 &&
        left.size === p.group_count * 5 &&
        right.size === p.group_count * 2,
      "覆盖模式的组间号码不能重叠",
    );
  return /** @type {Portfolio} */ (p);
}

/** @param {unknown} input @returns {Snapshot} */
export function validateSnapshot(input) {
  const s = object(input),
    h = object(s.history),
    source = object(s.source),
    portfolios = object(s.portfolios);
  requireValue(s.schema_version === 1, "不支持的快照格式");
  requireValue(
    h.history_start_date === "2023-01-01" &&
      h.history_start_issue === "23001" &&
      integer(h.rows, 1, 1000000),
    "快照的数据范围不正确",
  );
  requireValue(
    issue(h.first_id) && issue(h.last_id) && h.first_id <= h.last_id,
    "快照期号不正确",
  );
  requireValue(
    calendarDate(h.first_date) &&
      calendarDate(h.last_date) &&
      h.first_date >= "2023-01-01" &&
      Date.parse(h.last_date) >= Date.parse(h.first_date) &&
      h.first_date.slice(2, 4) === h.first_id.slice(0, 2) &&
      h.last_date.slice(2, 4) === h.last_id.slice(0, 2),
    "快照日期不正确",
  );
  requireValue(
    typeof s.generated_at === "string" &&
      Number.isFinite(Date.parse(s.generated_at)),
    "快照生成时间不合法",
  );
  requireValue(
    (source.url === null ||
      (typeof source.url === "string" &&
        source.url.startsWith("https://datachart.500.com/dlt/"))) &&
      /^[a-f0-9]{64}$/.test(source.sha256) &&
      source.complete === false &&
      Array.isArray(source.warnings) &&
      source.warnings.every((w) => typeof w === "string"),
    "快照来源或完整性标记不正确",
  );
  for (const mode of ["coverage", "uniform"]) {
    const p = validatePortfolio(portfolios[mode]);
    requireValue(p.mode === mode, "快照策略与内容不一致");
    validateWindows(p, h.rows);
  }
  const distributions = object(s.distributions);
  for (const zone of ["left", "right"]) {
    const d = object(distributions[zone]),
      sizes = object(d.sample_sizes);
    for (const feature of [
      "odd",
      "small",
      "adjacent_pairs",
      "repeat_previous",
    ]) {
      const sampleSize = feature === "repeat_previous" ? h.rows - 1 : h.rows;
      requireValue(
        sizes[feature] === sampleSize &&
          Array.isArray(d[feature]) &&
          d[feature].every(
            (bin) =>
              integer(bin.value, 0, zone === "left" ? 5 : 2) &&
              integer(bin.count, 0, h.rows),
          ),
        "历史分布不合法",
      );
      requireValue(
        d[feature].reduce((sum, bin) => sum + bin.count, 0) === sampleSize,
        "历史分布样本数不一致",
      );
    }
  }
  return /** @type {Snapshot} */ (s);
}

/** @param {string} text @returns {Portfolio} */
export function parseLocalResult(text) {
  requireValue(
    text.length <= 2 * 1024 * 1024,
    "文件过大，请使用不超过2MB的Skill结果",
  );
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("无法解析 JSON，请选择 Skill 导出的结果文件");
  }
  const p = validatePortfolio(data),
    cutoff = object(data.cutoff);
  requireValue(
    cutoff.history_start_date === "2023-01-01" &&
      cutoff.history_start_issue === "23001",
    "结果缺少2023年起的截断审计",
  );
  requireValue(
    issue(cutoff.target) &&
      issue(cutoff.training_first_id) &&
      issue(cutoff.training_last_id) &&
      cutoff.training_first_id <= cutoff.training_last_id &&
      cutoff.training_last_id < cutoff.target &&
      integer(cutoff.training_rows, 1, 1000000),
    "目标期或历史截断不合法",
  );
  validateWindows(p, cutoff.training_rows);
  return p;
}

/** @param {number} value */
export function pad(value) {
  return String(value).padStart(2, "0");
}

/** 保留UTF-8 BOM，使Python审计哈希对应用户选中的原始字节。 @param {ArrayBuffer} bytes */
export function decodeCsv(bytes) {
  return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(
    bytes,
  );
}
/** @param {number} count @param {number} total */
export function percent(count, total) {
  return total > 0 ? `${((count / total) * 100).toFixed(1)}%` : "—";
}
/** @param {Features} f @returns {string[]} */
export function featureValues(f) {
  return [
    `${f.odd} : ${f.even}`,
    `${f.small} : ${f.large}`,
    String(f.sum),
    String(f.span),
    `${f.adjacent_pairs} 对`,
    `${f.repeat_previous} 个`,
    `${f.hot} / ${f.warm} / ${f.cold}`,
  ];
}

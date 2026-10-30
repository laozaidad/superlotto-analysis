import { runResearch, cancelAnalysis } from "./engine.js";
import {
  validateResearchResult,
  validateResearchEvidence,
} from "./research.js";
import { pad } from "./data.js";
/** @type {Record<string,string>} */
const EXPERT_LABELS = {
  legacy_blend: "短长频率融合",
  shrink20: "20期频率收缩",
  shrink100: "100期频率收缩",
  shrink_all: "全历史频率收缩",
  gap_rank: "遗漏排序",
};
/** @typedef {import('./research.js').ResearchResult} ResearchResult */
/** @typedef {{getCSV:()=>string|undefined,getSourceLabel:()=>string,isBusy:()=>boolean,setBusy:(busy:boolean)=>void}} ResearchHost */
/** @param {string} id */
function el(id) {
  const item = document.getElementById(id);
  if (!item) throw new Error(`缺少研究界面 ${id}`);
  return item;
}
/** @param {string} tag @param {string} [className] @param {string} [text] */
function node(tag, className = "", text = "") {
  const item = document.createElement(tag);
  item.className = className;
  item.textContent = text;
  return item;
}
/** @param {ResearchHost} host */
export function initResearchUI(host) {
  /** @type {ResearchResult|null} */ let current = null;
  let run = 0,
    running = false,
    evidenceLoading = false;
  function markDirty() {
    if (running) return;
    el("research-status").textContent = current
      ? "输入已改变。下方仍是上次研究结果，点击“运行实验”后才更新。"
      : "输入已改变，请点击“运行实验”。权重与排名不代表中奖概率。";
    el("research-status").className = "run-status";
  }
  function sourceChanged() {
    el("research-source").textContent = host.getSourceLabel();
    markDirty();
  }
  /** @param {ResearchResult} result */
  function render(result) {
    const p = result.pool;
    const origin =
      result.runtime?.data_origin === "local"
        ? "本地 CSV（未上传）"
        : "公共历史";
    el("research-result-origin").textContent =
      `目标 ${result.target} · ${origin} · 历史 ${result.history.first_id}–${result.history.last_id} · ${result.history.rows} 期`;
    for (const zone of /** @type {const} */ (["left", "right"])) {
      const holder = el(`research-${zone}`);
      holder.replaceChildren();
      p[zone].forEach((n) => holder.append(node("span", "ball", pad(n))));
    }
    el("research-count").textContent = `${p.basic_combinations} 注`;
    el("research-cost").textContent = `${p.basic_cost_yuan} 元`;
    el("research-learning").textContent = `${result.learning.rows} 行`;
    el("research-probability").textContent =
      `号码池 ${p.size}：C(${p.left.length},5) × C(${p.right.length},2) = ${p.basic_combinations}。均匀、两区独立假设下，同期全部七码覆盖概率为 ${p.joint_probability.numerator} / ${p.joint_probability.denominator.toLocaleString("en-US")}；不是任意奖率，不代表已证实预测能力。`;
    const weights = el("research-weights");
    weights.replaceChildren();
    for (const expert of result.experts) {
      const row = node("div", "research-weight"),
        track = node("div", "bar-track"),
        fill = node("div", "bar-fill");
      fill.style.width = `${expert.weight * 100}%`;
      track.append(fill);
      track.setAttribute("aria-hidden", "true");
      const label = node(
        "span",
        "research-expert-label",
        EXPERT_LABELS[expert.name],
      );
      label.append(node("small", "", expert.name));
      row.append(
        label,
        track,
        node("span", "bar-value", `${(expert.weight * 100).toFixed(2)}%`),
      );
      weights.append(row);
    }
    const features = el("research-features");
    features.replaceChildren();
    for (const feature of result.features)
      features.append(
        node("dt", "", feature.name),
        node("dd", "", feature.value.toPrecision(6)),
      );
    const runtime = result.runtime;
    el("research-runtime").textContent =
      `学习记录 ${result.learning.first_id}–${result.learning.last_id}；仅使用目标之前的记录。` +
      (runtime
        ? ` Python ${runtime.python_version} / Pyodide ${runtime.pyodide_version}；模型 SHA-256 ${runtime.model_sha256}；研究模块 ${runtime.research_sha256}；核心 ${runtime.conditional_core_sha256}；输入数据 ${runtime.data_sha256}。`
        : "");
    const warnings = el("research-warnings");
    warnings.replaceChildren();
    result.warnings.forEach((w) => warnings.append(node("p", "", w)));
    el("research-result").hidden = false;
  }
  el("research-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (host.isBusy() || running) return;
    const target = /** @type {HTMLInputElement} */ (
      el("research-target")
    ).value.trim();
    const poolSize =
      /** @type {import('./engine.js').ResearchParameters['poolSize']} */ (
        /** @type {HTMLSelectElement} */ (el("research-pool")).value
      );
    const csvText = host.getCSV(),
      id = ++run;
    running = true;
    host.setBusy(true);
    el("research-status").className = "run-status busy";
    el("research-status").textContent = "准备研究计算；保留上次有效结果。";
    try {
      const output = await runResearch(
        { target, poolSize, ...(csvText !== undefined ? { csvText } : {}) },
        (message) => {
          if (id === run) el("research-status").textContent = message;
        },
      );
      if (id !== run) return;
      const result = validateResearchResult(output);
      // 请求身份也需要吻合，不能显示迟到或不匹配的模型输出。
      if (result.target !== target || result.pool.size !== poolSize)
        throw new Error("研究结果与本次请求不一致");
      if (
        !result.runtime ||
        result.runtime.data_origin !==
          (csvText === undefined ? "public" : "local")
      )
        throw new Error("研究结果缺少匹配的数据来源审计");
      render(result);
      current = result;
      el("research-status").textContent =
        `研究计算完成：${result.pool.size}，${result.history.rows}期历史、${result.learning.rows}行学习样本。下方权重不是中奖概率，尚无已证实的预测优势。`;
      el("research-status").className = "run-status";
    } catch (error) {
      if (id !== run) return;
      el("research-status").textContent =
        `实验未产生新结果：${error instanceof Error ? error.message : "计算失败"}。原有研究结果保留，可修正输入后重试。`;
      el("research-status").className = "run-status error";
    } finally {
      if (id === run) {
        running = false;
        host.setBusy(false);
      }
    }
  });
  el("research-cancel").addEventListener("click", () => {
    if (!running) return;
    run++;
    cancelAnalysis();
    running = false;
    host.setBusy(false);
    el("research-status").textContent = "已取消实验，原有研究结果未改动。";
    el("research-status").className = "run-status";
  });
  for (const id of ["research-target", "research-pool"])
    el(id).addEventListener("input", markDirty);
  el("research-download").addEventListener("click", () => {
    if (!current) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(current, null, 2)], {
        type: "application/json",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `superlotto-research-${current.target}-${current.pool.size}.json`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  async function loadEvidence() {
    if (evidenceLoading) return;
    evidenceLoading = true;
    el("evidence-status").textContent = "正在读取历史证据…";
    el("evidence-retry").hidden = true;
    try {
      const response = await fetch(
        new URL("../data/research-evidence.json", import.meta.url),
        { credentials: "omit", signal: AbortSignal.timeout(15000) },
      );
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const evidence = validateResearchEvidence(await response.json());
      el("evidence-caption").textContent =
        `研究范围：${evidence.scope.start_date}起。旧冻结探索窗口 ${evidence.test.first_id}–${evidence.test.last_id}（${evidence.test.periods}期）；由存档逐期记录重新汇总，不是新版前瞻盲测。`;
      const body = el("evidence-rows");
      body.replaceChildren();
      for (const item of evidence.comparisons) {
        const row = node("tr");
        row.append(
          node("th", "", item.label),
          node("td", "", String(item.left_hits)),
          node("td", "", String(item.right_hits)),
          node(
            "td",
            "",
            `${item.full_coverage_count}/${evidence.test.periods}`,
          ),
          node(
            "td",
            "",
            `${item.p_left_adjusted.toFixed(3)} / ${item.p_right_adjusted.toFixed(3)}`,
          ),
        );
        row.firstElementChild?.setAttribute("scope", "row");
        body.append(row);
      }
      el("evidence-baseline").textContent =
        `同规模随机对照：前区累计期望 ${evidence.random_expected.left.toFixed(2)}、后区 ${evidence.random_expected.right.toFixed(2)}。${evidence.multiple_testing.family_size}项探索性比较采用${evidence.multiple_testing.method}校正；未发现显著优势。`;
      const limitations = el("evidence-limitations");
      limitations.replaceChildren();
      evidence.limitations.forEach((item) =>
        limitations.append(node("li", "", item)),
      );
      el("evidence-content").hidden = false;
      el("evidence-status").textContent = "";
    } catch (error) {
      el("evidence-content").hidden = true;
      el("evidence-status").textContent =
        `历史证据未加载：${error instanceof Error ? error.message : "未知错误"}。不以示例数字填充，也不据此开放预测声明。`;
      el("evidence-retry").hidden = false;
    } finally {
      evidenceLoading = false;
    }
  }
  el("evidence-retry").addEventListener("click", loadEvidence);
  el("research-source").textContent = host.getSourceLabel();
  void loadEvidence();
  return { sourceChanged };
}

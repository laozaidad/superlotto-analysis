import {
  validateSnapshot,
  parseLocalResult,
  pad,
  percent,
  featureValues,
  decodeCsv,
} from "./data.js";
import { runAnalysis, cancelAnalysis } from "./engine.js";
/** @typedef {import('./data.js').Snapshot} Snapshot */
/** @typedef {import('./data.js').Portfolio} Portfolio */
/** @typedef {import('./data.js').HeatEntry} HeatEntry */
/** @param {string} id @returns {HTMLElement} */
function el(id) {
  const node = document.getElementById(id);
  if (!node) throw new Error(`缺少界面元素 ${id}`);
  return node;
}
/** @param {string} tag @param {string} [className] @param {string} [text] */
function node(tag, className = "", text = "") {
  const item = document.createElement(tag);
  item.className = className;
  item.textContent = text;
  return item;
}
/** @type {Snapshot|null} */ let snapshot = null;
/** @type {Portfolio|null} */ let local = null;
const mode = "coverage";
/** @type {'left'|'right'} */ let zone = "left";
/** @type {'snapshot'|'imported'|'computed'} */ let resultKind = "snapshot";
/** @type {string|undefined} */ let csvText;
let csvReadVersion = 0;
let activeRun = 0;
let busy = false;
let csvReading = false;
let selected = 0;
let selectedNumber = 1;
let importVersion = 0;
let loading = false;
/** @returns {Portfolio|null} */
function portfolio() {
  return local || snapshot?.portfolios[mode] || null;
}

for (let i = 1; i <= 35; i++)
  el("number-field").append(
    node("span", [3, 12, 19, 27, 34].includes(i) ? "selected" : "", pad(i)),
  );

/** @param {string} text */
function toast(text) {
  el("toast").textContent = text;
  window.setTimeout(() => {
    el("toast").textContent = "";
  }, 3000);
}

function renderPortfolio() {
  const p = portfolio();
  if (!p) return;
  selected = Math.min(selected, p.groups.length - 1);
  const tickets = el("tickets");
  tickets.replaceChildren();
  for (const [i, g] of p.groups.entries()) {
    const button = document.createElement("button");
    button.className = "ticket";
    button.type = "button";
    button.setAttribute("aria-pressed", String(selected === i));
    button.setAttribute(
      "aria-label",
      `第${i + 1}组，前区 ${g.left.map(pad).join(" ")}，后区 ${g.right.map(pad).join(" ")}`,
    );
    button.append(node("span", "ticket-index", pad(i + 1)));
    for (const side of /** @type {const} */ (["left", "right"])) {
      const balls = node("span", `balls ${side}`);
      g[side].forEach((n) => balls.append(node("span", "ball", pad(n))));
      button.append(balls);
    }
    button.addEventListener("click", () => {
      selected = i;
      document
        .querySelectorAll(".ticket")
        .forEach((b, idx) => b.setAttribute("aria-pressed", String(idx === i)));
      renderFeatures();
    });
    tickets.append(button);
  }
  el("result-mode").textContent =
    `${p.mode === "coverage" ? "分散覆盖" : "均匀抽样"} · ${resultKind === "computed" ? "网页计算结果" : resultKind === "imported" ? "导入结果" : "演示"}`;
  el("strategy-note").textContent =
    p.mode === "coverage"
      ? "在候选分区中选择形态更多样的组合；不使用冷热作为预测权重。"
      : "均匀抽样作为对照；只排除历史中已见的完整组合及本次重复组合，不使用形态评分。";
  el("seed-label").textContent = `SEED ${p.seed} · ${p.group_count} GROUPS`;
  el("left-coverage").textContent = String(p.coverage.left_count);
  el("right-coverage").textContent = String(p.coverage.right_count);
  /** @type {HTMLButtonElement} */ (el("download")).disabled = false;
  el("result-origin").textContent = local
    ? `${resultKind === "computed" ? "浏览器实际计算" : "本地文件（来源未核验）"} · 目标 ${local.cutoff?.target} · 历史截至 ${local.cutoff?.training_last_id} · ${local.cutoff?.training_rows} 期`
    : "公共快照 · 截至历史末期的组合设计演示，不绑定目标期";
  el("reset").hidden = !local;
  el("runtime-info").textContent =
    resultKind === "computed" && p.runtime
      ? `本机 Web Worker · Python ${p.runtime.python_version} / Pyodide ${p.runtime.pyodide_version} · 模型 SHA-256 ${p.runtime.model_sha256}`
      : "";
  renderFeatures();
  renderHeat();
  renderDistribution();
}

function renderFeatures() {
  const p = portfolio();
  if (!p) return;
  const g = p.groups[selected];
  el("inspector-title").textContent = `第 ${pad(selected + 1)} 组结构`;
  const a = featureValues(g.left_features),
    b = featureValues(g.right_features);
  const body = el("features-body");
  body.replaceChildren();
  [
    "奇 : 偶",
    "小 : 大",
    "和值",
    "跨度",
    "连号",
    "上期重号",
    "热 / 温 / 冷",
  ].forEach((label, i) => {
    const row = node("tr");
    row.append(
      node("td", "", label),
      node("td", "mono", a[i]),
      node("td", "mono", b[i]),
    );
    body.append(row);
  });
}

function renderHeat() {
  const p = portfolio();
  if (!p) return;
  const heat = p.heat[zone],
    maximum = zone === "left" ? 35 : 12;
  selectedNumber = Math.min(selectedNumber, maximum);
  const grid = el("heatmap");
  grid.className = `heatmap ${zone === "right" ? "right-zone" : ""}`;
  grid.replaceChildren();
  for (let n = 1; n <= maximum; n++) {
    const h = heat[n],
      button = document.createElement("button");
    button.className = `heat-cell ${h.label}`;
    button.textContent = pad(n);
    button.type = "button";
    const label = { hot: "热", warm: "温", cold: "冷" }[h.label];
    button.setAttribute(
      "aria-label",
      `${pad(n)}号，${label}，最近${h.window}期出现${h.count}次`,
    );
    button.setAttribute("aria-pressed", String(selectedNumber === n));
    button.addEventListener("click", () => {
      selectedNumber = n;
      grid
        .querySelectorAll("button")
        .forEach((b, index) =>
          b.setAttribute("aria-pressed", String(index + 1 === n)),
        );
      showHeatDetail(h);
    });
    grid.append(button);
  }
  el("heat-description").textContent =
    `${local ? "本地结果" : "公共快照"} · 最近 ${heat[1].window} 期的出现频数，相对于均匀基准。`;
  showHeatDetail(heat[selectedNumber]);
}
/** @param {HeatEntry} h */
function showHeatDetail(h) {
  el("heat-detail").textContent =
    `${zone === "left" ? "Left" : "Right"} ${pad(h.number)} · ${h.window} 期出现 ${h.count} 次 · z = ${h.z.toFixed(2)} · ${h.gap_censored ? `样本内未出现（至少 ${h.gap} 期）` : `遗漏 ${h.gap} 期`}`;
}

function renderDistribution() {
  const area = el("distribution-bars");
  area.replaceChildren();
  if (local && (resultKind !== "computed" || !local.web_distributions)) {
    area.append(
      node(
        "p",
        "small-note",
        "本地结果不含完整历史形态分布，不混用公共快照。上方冷热图与组合均来自导入文件。",
      ),
    );
    el("distribution-caption").textContent =
      "如需历史分布，请回到公共快照或在本地使用历史 CSV 分析。";
    return;
  }
  if (!snapshot && !local?.web_distributions) return;
  const choice =
    /** @type {'odd'|'small'|'adjacent_pairs'|'repeat_previous'} */ (
      /** @type {HTMLSelectElement} */ (el("distribution")).value
    );
  const d = (
    resultKind === "computed" && local?.web_distributions
      ? local.web_distributions
      : snapshot?.distributions
  )?.[zone];
  if (!d) return;
  const bins = d[choice],
    total = d.sample_sizes[choice];
  const max = Math.max(1, ...bins.map((b) => b.count));
  for (const bin of bins) {
    const row = node("div", "bar-row"),
      track = node("div", "bar-track"),
      fill = node("div", "bar-fill");
    fill.style.width = `${(bin.count / max) * 100}%`;
    track.append(fill);
    track.setAttribute("aria-hidden", "true");
    row.append(
      node(
        "span",
        "",
        `${bin.value} ${choice === "adjacent_pairs" ? "对" : "个"}`,
      ),
      track,
      node("span", "bar-value", `${bin.count} · ${percent(bin.count, total)}`),
    );
    area.append(row);
  }
  el("distribution-caption").textContent =
    `${total.toLocaleString("zh-CN")} 个有效样本${choice === "repeat_previous" ? "（首期无上期，不纳入）" : ""}。条形按最大频数缩放，右侧为次数与占比；不是中奖概率。`;
}

async function loadSnapshot() {
  if (loading) return;
  loading = true;
  el("load-status").textContent = "正在读取公开快照…";
  el("load-status").className = "notice";
  el("retry").hidden = true;
  try {
    const response = await fetch(
      new URL("../data/snapshot.json", import.meta.url),
      { signal: AbortSignal.timeout(15000) },
    );
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    snapshot = validateSnapshot(await response.json());
    el("history-count").replaceChildren(
      document.createTextNode(
        snapshot.history.rows.toLocaleString("zh-CN") + " ",
      ),
      node("small", "", "期"),
    );
    el("history-last").textContent = snapshot.history.last_date.slice(0, 10);
    const date = new Date(snapshot.generated_at).toLocaleDateString("zh-CN", {
      timeZone: "Asia/Singapore",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
    el("snapshot-time").textContent = `发布快照 ${date} · 非实时`;
    el("snapshot-source-label").textContent = snapshot.source.url
      ? "公开数据快照"
      : "来源未核验快照";
    el("source-hash").textContent = snapshot.source.sha256;
    el("provenance").textContent =
      `数据范围 ${snapshot.history.first_id}–${snapshot.history.last_id}，共 ${snapshot.history.rows} 期。${snapshot.source.warnings.join(" ")}`;
    if (csvText === undefined)
      el("data-detail").textContent =
        `${snapshot.history.first_id}–${snapshot.history.last_id} · ${snapshot.history.rows.toLocaleString("zh-CN")} 期 · 非实时`;
    el("load-status").textContent = "";
    renderPortfolio();
  } catch (error) {
    el("load-status").textContent =
      `快照加载失败：${error instanceof Error ? error.message : "未知错误"}。可重试或导入本地 Skill JSON；不使用伪造数据填充。`;
    el("load-status").className = "notice error";
    el("retry").hidden = false;
    el("history-last").textContent = "未加载";
  } finally {
    loading = false;
  }
}

document.querySelectorAll("button[data-zone]").forEach((button) =>
  button.addEventListener("click", () => {
    if (!(button instanceof HTMLButtonElement)) return;
    zone = button.dataset.zone === "right" ? "right" : "left";
    document
      .querySelectorAll("button[data-zone]")
      .forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    renderHeat();
    renderDistribution();
  }),
);
el("distribution").addEventListener("change", renderDistribution);
el("retry").addEventListener("click", loadSnapshot);
el("reset").addEventListener("click", () => {
  importVersion++;
  local = null;
  resultKind = "snapshot";
  el("run-warnings").replaceChildren();
  el("run-warnings").hidden = true;
  el("run-status").textContent = "已返回固定演示。填写目标期后可重新生成。";
  el("run-status").className = "run-status";
  selected = 0;
  /** @type {HTMLInputElement} */ (el("import-file")).value = "";
  el("import-status").textContent = "";
  el("reset").hidden = true;
  if (snapshot) {
    renderPortfolio();
    return;
  }
  el("tickets").replaceChildren(
    node("p", "loading-placeholder", "组合将在快照载入后显示"),
  );
  for (const id of ["features-body", "heatmap", "distribution-bars"])
    el(id).replaceChildren();
  for (const id of ["left-coverage", "right-coverage"])
    el(id).textContent = "—";
  el("heat-detail").textContent = "等待历史统计数据";
  el("heat-description").textContent = "未加载统计数据";
  el("distribution-caption").textContent = "未加载历史分布";
  el("result-origin").textContent = "未加载组合数据";
  el("seed-label").textContent = "NO DATA";
  el("strategy-note").textContent = "请选择重试，或导入一份有效的 Skill 结果。";
  el("inspector-title").textContent = "组合结构";
  el("result-mode").textContent = "未加载组合";
  el("runtime-info").textContent = "";
  /** @type {HTMLButtonElement} */ (el("download")).disabled = true;
  void loadSnapshot();
});
el("import-file").addEventListener("change", async () => {
  const input = /** @type {HTMLInputElement} */ (el("import-file")),
    file = input.files?.[0];
  if (!file) return;
  const version = ++importVersion;
  el("import-status").textContent = "正在本地校验…";
  try {
    if (file.size > 2 * 1024 * 1024)
      throw new Error("文件超过2MB，请选择较小的Skill结果");
    const text = await file.text();
    if (version !== importVersion) return;
    const result = parseLocalResult(text);
    local = result;
    resultKind = "imported";
    el("run-warnings").replaceChildren();
    el("run-warnings").hidden = true;
    selected = 0;
    el("import-status").textContent =
      "已在本地读取；未上传文件。结构检查通过不代表来源真实。";
    renderPortfolio();
    el("run-status").textContent =
      "当前显示导入结果。上方参数仅用于下一次网页计算。";
    el("run-status").className = "run-status";
    el("analysis").scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
  } catch (error) {
    el("import-status").textContent =
      `导入失败：${error instanceof Error ? error.message : "未知错误"}。保留当前有效结果。`;
  } finally {
    input.value = "";
  }
});
el("download").addEventListener("click", () => {
  const p = portfolio();
  if (!p) return;
  // 公共演示没有目标期，使用展示封装，避免冒充带截断审计的CLI结果。
  const result = local || {
    type: "public-display-portfolio",
    description: "展示快照，不绑定目标期；不是可导入的CLI结果。",
    history: snapshot?.history,
    source: snapshot?.source,
    portfolio: p,
  };
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = `superlotto-${resultKind === "computed" ? "browser" : local ? "local-result" : "display"}-${local?.cutoff?.target || "snapshot"}-${p.mode}.json`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast("已导出当前展示结果");
});
el("copy-command").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(el("command").textContent || "");
    toast("命令已复制，请先设置 TARGET");
  } catch {
    toast("浏览器不允许自动复制，请手动选择命令");
  }
});

/** @param {boolean} value */
function setBusy(value) {
  busy = value;
  el("analysis-form").setAttribute("aria-busy", String(value));
  for (const id of [
    "generate",
    "target-issue",
    "random-seed",
    "group-count",
    "analysis-mode",
    "csv-file",
    "use-public-data",
    "import-file",
    "reset",
  ]) {
    /** @type {HTMLInputElement|HTMLButtonElement|HTMLSelectElement} */ (
      el(id)
    ).disabled = value;
  }
  el("cancel-run").hidden = !value;
  el("generate").textContent = value ? "正在计算…" : "生成组合 →";
}
el("analysis-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy || csvReading) return;
  const target = /** @type {HTMLInputElement} */ (
    el("target-issue")
  ).value.trim();
  const seedValue = /** @type {HTMLInputElement} */ (el("random-seed")).value;
  const groupsValue = /** @type {HTMLInputElement} */ (el("group-count")).value;
  if (!target || !seedValue || !groupsValue) {
    el("run-status").textContent = "请填写目标期号、整数种子和1–6组数量。";
    el("run-status").className = "run-status error";
    return;
  }
  const params = {
    target,
    seed: Number(seedValue),
    groups: Number(groupsValue),
    mode: /** @type {'coverage'|'uniform'} */ (
      /** @type {HTMLSelectElement} */ (el("analysis-mode")).value
    ),
    ...(csvText !== undefined ? { csvText } : {}),
  };
  const id = ++activeRun;
  setBusy(true);
  el("run-status").className = "run-status busy";
  el("run-status").textContent =
    "正在准备浏览器计算环境；当前组合保留到新结果通过校验。";
  try {
    const output = await runAnalysis(params, (message) => {
      if (id === activeRun) el("run-status").textContent = message;
    });
    if (id !== activeRun) return;
    const result = parseLocalResult(JSON.stringify(output));
    local = result;
    resultKind = "computed";
    selected = 0;
    importVersion++;
    el("import-status").textContent = "";
    renderPortfolio();
    const warnings = el("run-warnings");
    warnings.replaceChildren();
    for (const warning of result.quality_warnings || [])
      warnings.append(node("p", "", warning));
    warnings.hidden = warnings.childElementCount === 0;
    const origin =
      result.runtime?.data_origin === "local"
        ? "你的本地 CSV（未上传）"
        : "公共历史快照";
    el("run-status").textContent =
      `计算完成：${result.group_count}组，使用${result.cutoff?.training_rows.toLocaleString("zh-CN")}期历史，截止${result.cutoff?.training_last_id}期。数据：${origin}。这是组合设计，不是预测承诺。`;
    el("run-status").className = "run-status";
  } catch (error) {
    if (id !== activeRun) return;
    el("run-status").textContent =
      `未生成新结果：${error instanceof Error ? error.message : "计算失败"}。原有结果未改动，可修正输入后重试。`;
    el("run-status").className = "run-status error";
  } finally {
    if (id === activeRun) setBusy(false);
  }
});
el("cancel-run").addEventListener("click", () => {
  activeRun++;
  cancelAnalysis();
  setBusy(false);
  el("run-status").textContent = "已取消计算，原有结果未改动。可重新生成。";
  el("run-status").className = "run-status";
});
for (const id of [
  "target-issue",
  "random-seed",
  "group-count",
  "analysis-mode",
]) {
  el(id).addEventListener("input", () => {
    if (!busy) {
      el("run-status").textContent =
        "参数已更改，点击“生成组合”运行模型；下方当前结果尚未更新。";
      el("run-status").className = "run-status";
    }
  });
}
el("csv-file").addEventListener("change", async () => {
  const input = /** @type {HTMLInputElement} */ (el("csv-file")),
    file = input.files?.[0];
  if (!file || busy) return;
  const id = ++csvReadVersion;
  csvReading = true;
  /** @type {HTMLButtonElement} */ (el("generate")).disabled = true;
  try {
    if (file.size > 2 * 1024 * 1024) throw new Error("CSV超过2MB上限");
    const bytes = await file.arrayBuffer();
    if (id !== csvReadVersion) return;
    const text = decodeCsv(bytes);
    if (!text.trim()) throw new Error("CSV为空");
    csvText = text;
    el("active-data").textContent = "已选择本地 CSV";
    el("data-detail").textContent =
      `${file.name} · ${(file.size / 1024).toFixed(1)} KB · 未上传`;
    el("use-public-data").hidden = false;
    el("run-status").textContent =
      "数据源已更改，点击“生成组合”完整校验并计算。下方仍保留上次结果。";
    el("run-status").className = "run-status";
  } catch (error) {
    el("run-status").textContent =
      `无法使用CSV：${error instanceof Error ? error.message : "读取失败"}。请使用UTF-8格式。数据源保持不变。`;
    el("run-status").className = "run-status error";
  } finally {
    input.value = "";
    if (id === csvReadVersion) {
      csvReading = false;
      /** @type {HTMLButtonElement} */ (el("generate")).disabled = busy;
    }
  }
});
el("use-public-data").addEventListener("click", () => {
  csvReadVersion++;
  csvText = undefined;
  el("use-public-data").hidden = true;
  csvReading = false;
  /** @type {HTMLButtonElement} */ (el("generate")).disabled = busy;
  el("active-data").textContent = "使用公共历史";
  el("data-detail").textContent = snapshot
    ? `${snapshot.history.first_id}–${snapshot.history.last_id} · ${snapshot.history.rows.toLocaleString("zh-CN")}期 · 非实时`
    : "2013年起 · 生成时校验公共历史";
  el("run-status").textContent = "已改用公共历史。点击“生成组合”重新计算。";
  el("run-status").className = "run-status";
});
void loadSnapshot();

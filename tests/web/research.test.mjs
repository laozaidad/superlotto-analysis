import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { Window } from "happy-dom";
import { initResearchUI } from "../../site/assets/research-ui.js";
import {
  validateResearchResult,
  validateResearchEvidence,
  combinations,
} from "../../site/assets/research.js";
import {
  runAnalysis,
  runResearch,
  validateResearchParameters,
  cancelAnalysis,
  ANALYSIS_TIMEOUT_MS,
} from "../../site/assets/engine.js";
const root = fileURLToPath(new URL("../../", import.meta.url));
const generated = spawnSync(
  "python3",
  [
    "-c",
    `
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'skills/superlotto/scripts'))
import model,research
records,_=model.load_data(root/'site/runtime/history.csv')
print(json.dumps({size:research.generate_research(records,'26999',size) for size in ['5+2','5+5','7+3','8+3']}))
`,
    root,
  ],
  { encoding: "utf8" },
);
assert.equal(generated.status, 0, generated.stderr);
const outputs = JSON.parse(generated.stdout);
const clone = () => structuredClone(outputs["5+2"]);
const evidence = JSON.parse(
  readFileSync(
    new URL("../../site/data/research-evidence.json", import.meta.url),
    "utf8",
  ),
);
test("真实Python研究输出与四种精确注数/成本契约一致，不冒充Portfolio", () => {
  for (const [size, count] of [
    ["5+2", 1],
    ["5+5", 10],
    ["7+3", 63],
    ["8+3", 168],
  ]) {
    const r = validateResearchResult(outputs[size]);
    assert.equal(r.pool.basic_combinations, count);
    assert.equal(r.pool.basic_cost_yuan, count * 2);
    assert.deepEqual(r.pool.joint_probability, {
      numerator: count,
      denominator: 21425712,
    });
    assert.equal(r.history.start_date, "2023-01-01");
    assert.ok(!("groups" in r));
  }
  assert.equal(combinations(35, 5) * combinations(12, 2), 21425712);
});
test("研究结果拒绝旧范围、未来/当期学习样本、矛盾截止与伪造预测声明", () => {
  for (const change of [
    (r) => (r.history.start_date = "2013-01-01"),
    (r) => (r.history.start_issue = "13001"),
    (r) => (r.history.last_id = r.target),
    (r) => (r.learning.last_id = r.target),
    (r) => r.cutoff.training_rows++,
    (r) => (r.cutoff.training_last_id = "26998"),
    (r) => (r.prediction_gate = "OPEN"),
    (r) => (r.predictive_advantage_claim = true),
    (r) => (r.score_not_probability = false),
    (r) => (r.parameters.ridge = 100),
    (r) => (r.parameters.temperature = 1),
    (r) => (r.learning.rows = 1),
    (r) => r.learning.rows--,
    (r) => (r.learning.first_id = r.history.first_id),
    (r) => (r.learning.last_id = "26122"),
    (r) => (r.cutoff.excluded_future = -1),
    (r) => (r.cutoff.excluded_before_start = 0.5),
    (r) => {
      r.history.rows = 199;
      r.cutoff.training_rows = 199;
      r.learning.rows = 99;
    },
    (r) => {
      r.history.rows = 1;
      r.cutoff.training_rows = 1;
      r.learning.rows = 1;
    },
  ]) {
    const r = clone();
    change(r);
    assert.throws(() => validateResearchResult(r));
  }
});
test("研究结果拒绝非有限/负权重、不归一化、密度/矩阵不一致和伪造特征", () => {
  for (const change of [
    (r) => (r.experts[0].weight = NaN),
    (r) => (r.experts[0].weight = -1),
    (r) => (r.experts[0].raw_weight = Infinity),
    (r) => (r.experts[0].predicted_reward = NaN),
    (r) => (r.experts[0].similarity_density = 0),
    (r) => (r.experts[0].similarity_density = 1),
    (r) => (r.experts[0].weight += 0.01),
    (r) => (r.experts[0].name = r.experts[1].name),
    (r) => (r.experts[0].name = "unknown"),
    (r) => r.experts.reverse(),
    (r) => (r.features[0].name = "unknown"),
    (r) => r.features.reverse(),
    (r) => (r.experts[0].predicted_reward += 1),
    (r) => (r.warnings = []),
    (r) => (r.features[0].value = Infinity),
    (r) => (r.similarity[0][1] = -0.1),
    (r) => (r.similarity[0][0] = 0.5),
  ]) {
    const r = clone();
    change(r);
    assert.throws(() => validateResearchResult(r));
  }
});
test("号码池必须是合法完整排名的前列，计数和概率均可核对", () => {
  for (const change of [
    (r) => (r.pool.size = "6+6"),
    (r) => (r.pool.left[0] = 99),
    (r) => (r.pool.right[1] = r.pool.right[0]),
    (r) => (r.pool.basic_combinations = 2),
    (r) => (r.pool.basic_cost_yuan = 100),
    (r) => (r.pool.joint_probability.denominator = 123),
    (r) => r.fused_rankings.left.reverse(),
    (r) => (r.fused_rankings.right[0] = r.fused_rankings.right[1]),
  ]) {
    const r = clone();
    change(r);
    assert.throws(() => validateResearchResult(r));
  }
});
test("冻结探索性证据可展示，拒绝前瞻或预测成功包装", () => {
  assert.equal(validateResearchEvidence(evidence).test.periods, 123);
  for (const change of [
    (e) => (e.scope.start_date = "2013-01-01"),
    (e) => (e.status = "confirmed"),
    (e) => (e.historical_data_previously_seen = false),
    (e) => (e.prediction_gate = "OPEN"),
    (e) => (e.test.last_id = "26999"),
    (e) => (e.multiple_testing.family_size = 1),
    (e) => (e.random_expected.right = 42),
    (e) => (e.comparisons[0].p_left_adjusted = 0),
    (e) => (e.source_hashes = { a: "not-a-hash" }),
    (e) => (e.comparisons[0].size = "8+3"),
    (e) => (e.comparisons[0].n = 1),
    (e) => (e.comparisons[0].variant = "future_test"),
  ]) {
    const e = structuredClone(evidence);
    change(e);
    assert.throws(() => validateResearchEvidence(e));
  }
});
const originalWorker = globalThis.Worker;
class FakeWorker {
  static list = [];
  constructor() {
    this.handlers = {};
    this.sent = [];
    this.stopped = false;
    FakeWorker.list.push(this);
  }
  addEventListener(name, callback) {
    this.handlers[name] = callback;
  }
  postMessage(message) {
    this.sent.push(message);
  }
  terminate() {
    this.stopped = true;
  }
  result(result) {
    this.handlers.message({
      data: { type: "result", id: this.sent.at(-1).id, result },
    });
  }
}
const originalGlobals = {
  document: globalThis.document,
  window: globalThis.window,
  fetch: globalThis.fetch,
};
const windows = [];
afterEach(async () => {
  cancelAnalysis();
  globalThis.Worker = originalWorker;
  FakeWorker.list = [];
  for (const window of windows.splice(0)) await window.happyDOM.close();
  Object.assign(globalThis, originalGlobals);
});
test("研究请求只接受四种固定规格，旧年份/空CSV/过大CSV被拒绝", () => {
  const p = { target: "26999", poolSize: "5+2" };
  assert.deepEqual(validateResearchParameters({ ...p, python: "print(1)" }), p);
  for (const change of [
    (p) => (p.target = "23001"),
    (p) => (p.target = "22099"),
    (p) => (p.poolSize = "35+12"),
    (p) => (p.csvText = ""),
    (p) => (p.csvText = "汉".repeat(1048576)),
  ]) {
    const x = { ...p };
    change(x);
    assert.throws(() => validateResearchParameters(x));
  }
});
test("研究与基础分析共享排他worker，不上传参数，成功结果保持原schema", async () => {
  globalThis.Worker = FakeWorker;
  const request = runResearch({
    target: "26999",
    poolSize: "7+3",
    csvText: "local CSV",
  });
  const w = FakeWorker.list[0];
  assert.equal(w.sent[0].task, "research");
  assert.equal(w.sent[0].params.poolSize, "7+3");
  await assert.rejects(
    runAnalysis({ target: "26999", seed: 0, groups: 5, mode: "coverage" }),
    /已有推演/,
  );
  w.result(outputs["7+3"]);
  assert.deepEqual(await request, outputs["7+3"]);
  const analysis = runAnalysis({
    target: "26999",
    seed: 0,
    groups: 5,
    mode: "coverage",
  });
  assert.equal(FakeWorker.list.length, 1);
  assert.equal(w.sent.at(-1).task, "analysis");
  w.result({ ok: true });
  await analysis;
});
test("研究取消终止共享worker，随后可以重新运行；加载超时仍有上限", async () => {
  globalThis.Worker = FakeWorker;
  const request = runResearch({ target: "26999", poolSize: "5+5" });
  cancelAnalysis();
  await assert.rejects(request, /取消/);
  assert.ok(FakeWorker.list[0].stopped);
  const next = runResearch({ target: "26999", poolSize: "5+2" });
  FakeWorker.list[1].result(outputs["5+2"]);
  await next;
  assert.equal(ANALYSIS_TIMEOUT_MS, 120000);
});
test("worker研究适配器调用原模块，结果与Python直接调用相同，审计去除路径", () => {
  const worker = readFileSync(
    new URL("../../site/assets/engine-worker.js", import.meta.url),
    "utf8",
  );
  const code = worker.match(/const RESEARCH = `([\s\S]*?)`;/)?.[1];
  assert.ok(code);
  const result = spawnSync(
    "python3",
    [
      "-c",
      `
import json,sys,tempfile
from pathlib import Path
root=Path(sys.argv[1]); payload=json.load(sys.stdin);sys.path.insert(0,str(root/'skills/superlotto/scripts'))
import model,research
from run_skill import data_quality
records,_=model.load_data(root/'site/runtime/history.csv')
expected=research.generate_research(records,'26999','8+3')
with tempfile.TemporaryDirectory() as directory:
    p=Path(directory)/'input.csv';p.write_bytes((root/'site/runtime/history.csv').read_bytes())
    scope={'_browser_parameters':json.dumps({'target':'26999','poolSize':'8+3'}),'_browser_context':json.dumps({'pyodide_version':'test','model_sha256':'a'*64,'research_sha256':'b'*64,'conditional_core_sha256':'c'*64,'data_origin':'local'})}
    exec(payload['code'].replace("'/input.csv'",repr(str(p))),scope)
    output=json.loads(scope['_browser_research']())
    assert all(output[key]==value for key,value in expected.items() if key!='warnings')
    assert output['warnings'][:len(expected['warnings'])]==expected['warnings']
    history,_=model.select_history(records,'26999')
    assert output['data_quality']==data_quality(history,'26999')
    assert all(warning in output['warnings'] for warning in output['audit']['warnings'])
    assert any(f"数据截止{history[-1]['id']}" in warning and '26999' in warning for warning in output['warnings'])
    assert any('200期' in warning for warning in output['warnings'])
    assert 'source_path' not in output['audit']
    assert output['runtime']['data_origin']=='local'
    print('research adapter parity passed')
`,
      root,
    ],
    { input: JSON.stringify({ code }), encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /parity passed/);
  for (const name of [
    "research_sha256",
    "conditional_core_sha256",
    "model_sha256",
  ])
    assert.ok(worker.includes(name));
});

const researchMarkup = readFileSync(
  new URL("../../site/index.html", import.meta.url),
  "utf8",
).match(/<section[^>]*id="research"[\s\S]*?<\/section>/)?.[0];
assert.ok(researchMarkup);
function uiOutput(size = "5+2", origin = "public") {
  return {
    ...structuredClone(outputs[size]),
    runtime: {
      data_origin: origin,
      python_version: "3.14",
      pyodide_version: "314.0.7",
      model_sha256: "a".repeat(64),
      research_sha256: "b".repeat(64),
      conditional_core_sha256: "c".repeat(64),
      data_sha256: "d".repeat(64),
    },
  };
}
async function flushUI() {
  await new Promise((resolve) => setImmediate(resolve));
}
function uiFixture({ csvText, evidenceResult = evidence } = {}) {
  const window = new Window({ url: "https://example.test/" });
  windows.push(window);
  const document = window.document;
  document.body.innerHTML = researchMarkup;
  globalThis.document = document;
  globalThis.window = window;
  globalThis.Worker = FakeWorker;
  const requests = [];
  let evidencePayload = evidenceResult;
  globalThis.fetch = async (url, options) => {
    requests.push({ url: String(url), options });
    return { ok: true, json: async () => structuredClone(evidencePayload) };
  };
  const state = { busy: false, csvText, source: "测试公共历史" };
  const ui = initResearchUI({
    getCSV: () => state.csvText,
    getSourceLabel: () => state.source,
    isBusy: () => state.busy,
    setBusy: (value) => {
      state.busy = value;
    },
  });
  const el = (id) => document.getElementById(id);
  function submit(size = "5+2") {
    el("research-target").value = "26999";
    el("research-pool").value = size;
    el("research-form").dispatchEvent(
      new window.Event("submit", { bubbles: true, cancelable: true }),
    );
  }
  return {
    window,
    document,
    el,
    state,
    ui,
    requests,
    submit,
    setEvidence: (value) => {
      evidencePayload = value;
    },
  };
}
test("研究界面本地CSV仅交给worker，独立渲染中文专家、精确成本与旧探索证据", async () => {
  const f = uiFixture({ csvText: "\ufefflocal CSV\r\n" });
  await flushUI();
  assert.equal(f.el("evidence-rows").children.length, 3);
  assert.match(
    f.el("evidence-caption").textContent,
    /旧冻结探索.*不是新版前瞻盲测/,
  );
  assert.match(f.el("evidence-baseline").textContent, /66项.*未发现显著优势/);
  f.submit("5+5");
  assert.equal(f.state.busy, true);
  const w = FakeWorker.list[0];
  assert.equal(w.sent[0].params.csvText, "\ufefflocal CSV\r\n");
  assert.equal(w.sent[0].task, "research");
  w.result(uiOutput("5+5", "local"));
  await flushUI();
  assert.equal(f.state.busy, false);
  assert.equal(f.el("research-result").hidden, false);
  assert.equal(f.el("research-count").textContent, "10 注");
  assert.equal(f.el("research-cost").textContent, "20 元");
  assert.match(
    f.el("research-weights").textContent,
    /短长频率融合legacy_blend/,
  );
  assert.match(f.el("research-weights").textContent, /遗漏排序gap_rank/);
  assert.match(
    f.el("research-probability").textContent,
    /10 \/ 21,425,712.*不是任意奖率/,
  );
  assert.equal(f.requests.length, 1);
  assert.match(f.requests[0].url, /research-evidence\.json$/);
  assert.equal(f.requests[0].options.credentials, "omit");
});
test("研究失败、伪造输出、取消和旧worker迟到均保留上次结果，重试可用", async () => {
  const f = uiFixture();
  f.submit();
  FakeWorker.list[0].result(uiOutput());
  await flushUI();
  const valid = f.el("research-result").innerHTML;
  f.submit("8+3");
  FakeWorker.list[0].result(uiOutput());
  await flushUI();
  assert.match(f.el("research-status").textContent, /与本次请求不一致/);
  assert.equal(f.el("research-result").innerHTML, valid);
  f.submit();
  const first = FakeWorker.list[0];
  first.handlers.message({
    data: {
      type: "error",
      id: first.sent.at(-1).id,
      error: "只有9期，研究至少需要200期",
    },
  });
  await flushUI();
  assert.match(f.el("research-status").textContent, /只有9期/);
  assert.equal(f.el("research-result").innerHTML, valid);
  f.submit("7+3");
  const cancelled = FakeWorker.list[1];
  f.el("research-cancel").click();
  await flushUI();
  assert.ok(cancelled.stopped);
  assert.equal(f.state.busy, false);
  assert.match(f.el("research-status").textContent, /已取消/);
  assert.equal(f.el("research-result").innerHTML, valid);
  f.submit("8+3");
  cancelled.result(uiOutput("7+3"));
  assert.equal(f.el("research-result").innerHTML, valid);
  FakeWorker.list[2].result(uiOutput("8+3"));
  await flushUI();
  assert.equal(f.el("research-count").textContent, "168 注");
  assert.equal(f.state.busy, false);
});
test("研究来源和参数改变只提示过期，不自动重算；基础分析忙时不能启动研究", async () => {
  const f = uiFixture();
  f.submit();
  FakeWorker.list[0].result(uiOutput());
  await flushUI();
  const originalOrigin = f.el("research-result-origin").textContent;
  f.state.source = "本地私有CSV（未上传）";
  f.state.csvText = "private CSV";
  f.ui.sourceChanged();
  assert.equal(f.el("research-result-origin").textContent, originalOrigin);
  assert.match(f.el("research-source").textContent, /本地私有/);
  assert.match(f.el("research-status").textContent, /下方仍是上次研究结果/);
  f.el("research-pool").value = "5+5";
  f.el("research-pool").dispatchEvent(
    new f.window.Event("input", { bubbles: true }),
  );
  assert.equal(FakeWorker.list[0].sent.length, 1);
  f.state.busy = true;
  f.submit("5+5");
  assert.equal(FakeWorker.list[0].sent.length, 1);
  f.state.busy = false;
  f.submit("5+5");
  assert.equal(FakeWorker.list[0].sent.at(-1).params.csvText, "private CSV");
  FakeWorker.list[0].result(uiOutput("5+5", "local"));
  await flushUI();
  assert.equal(f.requests.length, 1);
});
test("损坏证据不填示例数字，明确失败且支持重新读取", async () => {
  const f = uiFixture({ evidenceResult: {} });
  await flushUI();
  assert.equal(f.el("evidence-content").hidden, true);
  assert.equal(f.el("evidence-retry").hidden, false);
  assert.equal(f.el("evidence-rows").children.length, 0);
  assert.match(f.el("evidence-status").textContent, /未加载.*不以示例数字填充/);
  f.setEvidence(evidence);
  f.el("evidence-retry").click();
  await flushUI();
  assert.equal(f.el("evidence-content").hidden, false);
  assert.equal(f.el("evidence-retry").hidden, true);
  assert.equal(f.el("evidence-rows").children.length, 3);
});

test("研究下载保留原schema；失败或更换来源后仍下载上次有效结果", async (context) => {
  const f = uiFixture(),
    downloads = [],
    blobs = [];
  context.mock.method(URL, "createObjectURL", (blob) => {
    blobs.push(blob);
    return "blob:test-research";
  });
  context.mock.method(URL, "revokeObjectURL", () => {});
  context.mock.method(
    f.window.HTMLAnchorElement.prototype,
    "click",
    function () {
      downloads.push({ href: this.href, name: this.download });
    },
  );
  const expected = uiOutput("5+5");
  f.submit("5+5");
  FakeWorker.list[0].result(expected);
  await flushUI();
  f.state.csvText = "new local file";
  f.state.source = "本地新文件";
  f.ui.sourceChanged();
  f.submit("8+3");
  FakeWorker.list[0].result(uiOutput("8+3", "public"));
  await flushUI();
  assert.match(f.el("research-status").textContent, /数据来源审计/);
  f.el("research-download").click();
  assert.equal(downloads[0].name, "superlotto-research-26999-5+5.json");
  assert.deepEqual(JSON.parse(await blobs[0].text()), expected);
  assert.equal(f.requests.length, 1);
});

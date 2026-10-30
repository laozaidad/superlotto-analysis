import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  runAnalysis,
  cancelAnalysis,
  validateParameters,
  MAX_CSV_BYTES,
  ANALYSIS_TIMEOUT_MS,
  readableError,
} from "../../site/assets/engine.js";

const params = { target: "26999", seed: 0, groups: 5, mode: "coverage" };
const originalWorker = globalThis.Worker;
test("Python校验失败显示明确原因而不是整段内部堆栈", () => {
  assert.equal(
    readableError(
      'Traceback (most recent call last):\n  File "/model.py", line 56\nValueError: CSV 表头错误\n',
    ),
    "ValueError: CSV 表头错误",
  );
  assert.equal(readableError("无法读取模型"), "无法读取模型");
});
class MockWorker {
  static instances = [];
  constructor(url, options) {
    this.url = url;
    this.options = options;
    this.listeners = new Map();
    this.sent = [];
    this.terminated = false;
    MockWorker.instances.push(this);
  }
  addEventListener(type, callback) {
    this.listeners.set(type, callback);
  }
  postMessage(message) {
    this.sent.push(message);
  }
  terminate() {
    this.terminated = true;
  }
  emit(type, event) {
    this.listeners.get(type)?.(event);
  }
  result(value, id = this.sent.at(-1).id) {
    this.emit("message", { data: { id, type: "result", result: value } });
  }
}
function mockWorker() {
  MockWorker.instances = [];
  globalThis.Worker = MockWorker;
}
afterEach(() => {
  cancelAnalysis();
  globalThis.Worker = originalWorker;
});

test("推演参数仅接受明确的五位期号、安全整数种子和1至6组", () => {
  assert.deepEqual(validateParameters(params), params);
  assert.equal(
    validateParameters({ ...params, seed: -42, groups: 6 }).seed,
    -42,
  );
  for (const target of [
    "13001",
    "12001",
    "13000",
    "",
    "2612",
    "26x01",
    "２６１０１",
    "26999\nprint(1)",
  ])
    assert.throws(() => validateParameters({ ...params, target }));
  for (const seed of [1.1, Infinity, NaN, Number.MAX_SAFE_INTEGER + 1, "0"])
    assert.throws(() => validateParameters({ ...params, seed }));
  for (const groups of [0, 7, -1, 1.5, "5"])
    assert.throws(() => validateParameters({ ...params, groups }));
  assert.throws(() => validateParameters({ ...params, mode: "prediction" }));
});
test("CSV按UTF-8字节计2MB上限且不接受空内容，额外执行字段被剔除", () => {
  assert.throws(() => validateParameters({ ...params, csvText: "" }), /为空/);
  assert.throws(
    () =>
      validateParameters({
        ...params,
        csvText: "汉".repeat(MAX_CSV_BYTES / 2),
      }),
    /2MB/,
  );
  const clean = validateParameters({
    ...params,
    csvText: "No.,L1",
    python: "print(1)",
    url: "https://example.com",
  });
  assert.equal(clean.csvText, "No.,L1");
  assert.ok(!("python" in clean));
  assert.ok(!("url" in clean));
});
test("无效输入不会创建worker或请求网络", async () => {
  mockWorker();
  await assert.rejects(runAnalysis({ ...params, target: "" }));
  assert.equal(MockWorker.instances.length, 0);
});
test("module worker传递参数、进度和结果，成功后复用运行时", async () => {
  mockWorker();
  const progress = [];
  const promise = runAnalysis(params, (text) => progress.push(text));
  const worker = MockWorker.instances[0];
  assert.equal(worker.options.type, "module");
  assert.match(worker.url.href, /engine-worker\.js$/);
  assert.deepEqual(worker.sent[0].params, params);
  worker.emit("message", {
    data: { id: worker.sent[0].id, type: "progress", text: "正在计算" },
  });
  worker.result({ groups: [] });
  assert.deepEqual(await promise, { groups: [] });
  assert.equal(progress.at(-1), "正在计算");
  const again = runAnalysis(params);
  assert.equal(MockWorker.instances.length, 1);
  worker.result({ seed: 0 });
  assert.deepEqual(await again, { seed: 0 });
});
test("并发调用被拒绝而不终止正在进行的请求", async () => {
  mockWorker();
  const first = runAnalysis(params);
  const worker = MockWorker.instances[0];
  await assert.rejects(runAnalysis(params), /已有推演/);
  assert.equal(worker.terminated, false);
  worker.result({ ok: true });
  assert.deepEqual(await first, { ok: true });
});
test("取消会终止加载并拒绝Promise；重试新建worker，忽略旧消息", async () => {
  mockWorker();
  const first = runAnalysis(params);
  const old = MockWorker.instances[0];
  cancelAnalysis();
  await assert.rejects(first, /取消/);
  assert.equal(old.terminated, true);
  const second = runAnalysis(params);
  const current = MockWorker.instances[1];
  old.result({ stale: true }, current.sent[0].id);
  current.result({ fresh: true });
  assert.deepEqual(await second, { fresh: true });
});
test("worker错误和加载错误可读并在下次重新创建", async () => {
  mockWorker();
  const promise = runAnalysis(params);
  const first = MockWorker.instances[0];
  first.emit("message", {
    data: { id: first.sent[0].id, type: "error", error: "CSV表头错误" },
  });
  await assert.rejects(promise, /CSV表头错误/);
  assert.ok(first.terminated);
  const next = runAnalysis(params);
  MockWorker.instances[1].emit("error", {
    message: "下载失败",
    preventDefault() {},
  });
  await assert.rejects(next, /下载失败/);
});
test("超过120秒停止worker，不让无限加载占用页面", async (context) => {
  context.mock.timers.enable({ apis: ["setTimeout"] });
  mockWorker();
  const promise = runAnalysis(params);
  assert.equal(ANALYSIS_TIMEOUT_MS, 120000);
  context.mock.timers.tick(120000);
  await assert.rejects(promise, /120秒/);
  assert.ok(MockWorker.instances[0].terminated);
});
test("Worker构造失败与进度回调失败均可恢复，无悬空请求", async () => {
  globalThis.Worker = class {
    constructor() {
      throw new Error("worker被阻止");
    }
  };
  await assert.rejects(runAnalysis(params), /worker被阻止/);
  mockWorker();
  await assert.rejects(
    runAnalysis(params, () => {
      throw new Error("回调失败");
    }),
    /回调失败/,
  );
  assert.ok(MockWorker.instances[0].terminated);
  const next = runAnalysis(params);
  MockWorker.instances[1].result({ ok: true });
  assert.deepEqual(await next, { ok: true });
});
test("Python适配器直接调用原模型，输出与CLI核心结果相等且分布截止一致", () => {
  const worker = readFileSync(
    new URL("../../site/assets/engine-worker.js", import.meta.url),
    "utf8",
  );
  const code = worker.match(/const ANALYZE = `([\s\S]*?)`;/)?.[1];
  assert.ok(code, "固定Python适配器必须存在");
  const root = fileURLToPath(new URL("../../", import.meta.url));
  const script = `
import json,sys,os,tempfile
from pathlib import Path
root=Path(sys.argv[1]); payload=json.load(sys.stdin)
sys.path.insert(0,str(root/'skills/superlotto/scripts'))
import model
records,audit=model.load_data(root/'site/runtime/history.csv')
history,cutoff=model.select_history(records,'23010')
expected=json.loads(json.dumps(model.generate_portfolio(history,seed=7,groups=3,mode='coverage')))
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp)/'input.csv';p.write_bytes((root/'site/runtime/history.csv').read_bytes())
    code=payload['code'].replace("'/input.csv'",repr(str(p)))
    scope={'_browser_parameters':json.dumps({'target':'23010','seed':7,'groups':3,'mode':'coverage'}),'_browser_context':json.dumps({'pyodide_version':'test','model_sha256':'test','data_origin':'public'})}
    exec(code,scope)
    result=json.loads(scope['_browser_analyze']())
    assert all(result[k]==v for k,v in expected.items())
    assert result['cutoff']['training_last_id']=='23009'
    assert result['cutoff']['excluded_future']>0
    assert 'source_path' not in result['audit']
    assert result['web_distributions']['left']['sample_sizes']['odd']==len(history)
    assert result['web_distributions']['left']['sample_sizes']['repeat_previous']==len(history)-1
    assert result['runtime']['data_origin']=='public'
    assert result['quality_warnings']
    print('adapter parity and target cutoff passed')
`;
  const result = spawnSync("python3", ["-c", script, root], {
    input: JSON.stringify({ code }),
    encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /parity and target cutoff passed/);
});
test("引擎只从固定CDN和本站读取；无上传请求与用户Python执行入口", () => {
  const worker = readFileSync(
    new URL("../../site/assets/engine-worker.js", import.meta.url),
    "utf8",
  );
  assert.ok(
    !/method:\s*["']POST|sendBeacon|XMLHttpRequest|loadPackagesFromImports|micropip/.test(
      worker,
    ),
  );
  assert.match(worker, /cdn\.jsdelivr\.net\/pyodide/);
  assert.match(worker, /credentials: ["']omit/);
  assert.match(worker, /crypto\.subtle\.digest/);
  assert.match(worker, /model\.select_history/);
});

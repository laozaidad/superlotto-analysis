import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { Window } from "happy-dom";
import { initCustomSelects } from "../../site/assets/select.js";

const original = {
  fetch: globalThis.fetch,
  self: globalThis.self,
  document: globalThis.document,
  window: globalThis.window,
};
const windows = [];
afterEach(async () => {
  for (const window of windows.splice(0)) {
    initCustomSelects(window.document).forEach((control) => control.destroy());
    await window.happyDOM.close();
  }
  Object.assign(globalThis, original);
});

test("页面启动重验证公共快照缓存，改参数不自动请求新数据或重算", async () => {
  const window = new Window({ url: "https://example.test/" });
  windows.push(window);
  const html = readFileSync(new URL("../../site/index.html", import.meta.url), "utf8");
  const body = html.match(/<body>([\s\S]*?)<\/body>/)?.[1];
  assert.ok(body);
  window.document.body.innerHTML = body.replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, "");
  globalThis.document = window.document;
  globalThis.window = window;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    const filename = new URL(url).pathname.split("/").at(-1);
    assert.ok(["snapshot.json", "research-evidence.json"].includes(filename));
    requests.push({ filename, options });
    return new Response(
      readFileSync(new URL(`../../site/data/${filename}`, import.meta.url)),
    );
  };
  await import("../../site/assets/app.js?refresh-cache-test");
  await new Promise((resolve) => setImmediate(resolve));
  const snapshots = requests.filter((request) => request.filename === "snapshot.json");
  assert.equal(snapshots.length, 1);
  assert.equal(snapshots[0].options.cache, "no-cache");
  assert.ok(snapshots[0].options.signal instanceof AbortSignal);
  const snapshot = JSON.parse(readFileSync(new URL("../../site/data/snapshot.json", import.meta.url), "utf8"));
  assert.equal(window.document.getElementById("history-last").textContent, snapshot.history.last_date.slice(0, 10));
  assert.ok(window.document.getElementById("data-detail").textContent.includes(snapshot.history.last_id));
  const tickets = window.document.getElementById("tickets").textContent;
  const target = window.document.getElementById("target-issue");
  target.value = "26999";
  target.dispatchEvent(new window.Event("input", { bubbles: true }));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(requests.filter((request) => request.filename === "snapshot.json").length, 1);
  assert.equal(window.document.getElementById("tickets").textContent, tickets);
});

test("worker重验证全部公共运行资源；跨版本CSV哈希不符时停止而不计算", async () => {
  const requests = [], messages = [];
  let onMessage;
  globalThis.self = {
    addEventListener: (name, callback) => {
      assert.equal(name, "message");
      onMessage = callback;
    },
    postMessage: (message) => messages.push(message),
  };
  globalThis.fetch = async (url, options) => {
    const filename = new URL(url).pathname.split("/").at(-1);
    requests.push({ filename, options });
    const bytes = readFileSync(new URL(`../../site/runtime/${filename}`, import.meta.url));
    if (filename === "history.csv") bytes[bytes.length - 1] ^= 1;
    return new Response(bytes);
  };
  await import("../../site/assets/engine-worker.js?refresh-cache-test");
  assert.equal(typeof onMessage, "function");
  await onMessage({ data: { type: "run", task: "analysis", id: 1,
    params: { target: "26999", seed: 0, groups: 1, mode: "uniform" } } });
  assert.deepEqual(requests.map((request) => request.filename), [
    "manifest.json", "model.py", "research.py", "conditional_core.py", "history.csv",
  ]);
  for (const { options } of requests) {
    assert.equal(options.cache, "no-cache");
    assert.equal(options.credentials, "omit");
    assert.ok(options.signal instanceof AbortSignal);
  }
  assert.equal(messages.at(-1).type, "error");
  assert.match(messages.at(-1).error, /公共历史数据哈希.*不一致/);
  assert.equal(messages.some((message) => message.type === "result"), false);
  assert.equal(messages.some((message) => message.text?.includes("正在加载 Python")), false);
});

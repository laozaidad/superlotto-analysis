import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  validateSnapshot,
  validatePortfolio,
  parseLocalResult,
  featureValues,
  pad,
  percent,
  decodeCsv,
} from "../../site/assets/data.js";

test("CSV解码保留BOM与CRLF，重编码字节及审计哈希不改变", () => {
  const bytes = new TextEncoder().encode(
    "\uFEFFNo.,Date\r\n13001,2013-01-02\r\n",
  );
  const decoded = decodeCsv(bytes.buffer);
  assert.equal(decoded.charCodeAt(0), 0xfeff);
  assert.deepEqual(new TextEncoder().encode(decoded), bytes);
  assert.throws(() => decodeCsv(new Uint8Array([0xff]).buffer));
});

const snapshot = JSON.parse(
  readFileSync(
    new URL("../../site/data/snapshot.json", import.meta.url),
    "utf8",
  ),
);
const clone = (x) => structuredClone(x);
function localResult() {
  return {
    ...clone(snapshot.portfolios.coverage),
    cutoff: {
      history_start_date: "2013-01-01",
      history_start_issue: "13001",
      target: "26999",
      training_first_id: snapshot.history.first_id,
      training_last_id: snapshot.history.last_id,
      training_rows: snapshot.history.rows,
    },
  };
}
test("公开快照通过结构与2013范围校验，两种模式独立有效", () => {
  assert.equal(validateSnapshot(snapshot).schema_version, 1);
  for (const mode of ["uniform", "coverage"])
    assert.equal(validatePortfolio(snapshot.portfolios[mode]).mode, mode);
});
test("本地结果需带目标期截断审计", () => {
  assert.equal(parseLocalResult(JSON.stringify(localResult())).group_count, 5);
  assert.throws(
    () => parseLocalResult(JSON.stringify(snapshot.portfolios.coverage)),
    /JSON 必须为对象/,
  );
});
test("拒绝目标期与历史重叠及2013以前范围", () => {
  const r = localResult();
  r.cutoff.target = r.cutoff.training_last_id;
  assert.throws(() => parseLocalResult(JSON.stringify(r)), /截断不合法/);
  r.cutoff.target = "26999";
  r.cutoff.training_first_id = "12001";
  assert.throws(() => parseLocalResult(JSON.stringify(r)), /截断不合法/);
  const p = clone(snapshot.portfolios.coverage);
  p.history_start_date = "2023-01-01";
  assert.throws(() => validatePortfolio(p), /2013/);
});
test("拒绝声称预测优势、重复和越界号码、伪造覆盖", () => {
  for (const mutate of [
    (p) => {
      p.prediction_gate = "OPEN";
    },
    (p) => {
      p.predictive_advantage_claim = true;
    },
    (p) => {
      p.groups[0].left[0] = 99;
    },
    (p) => {
      p.groups[0].left[1] = p.groups[0].left[0];
    },
    (p) => {
      p.coverage.left_count = 35;
    },
    (p) => {
      p.groups[0].left_features.sum++;
    },
    (p) => {
      p.groups[0].right_features.hot++;
    },
  ]) {
    const p = clone(snapshot.portfolios.coverage);
    mutate(p);
    assert.throws(() => validatePortfolio(p));
  }
});
test("拒绝伪造冷热频数、z值、标签与遗漏", () => {
  for (const mutate of [
    (h) => {
      h.count = 101;
    },
    (h) => {
      h.z = 100;
    },
    (h) => {
      h.label = "hot";
    },
    (h) => {
      h.gap = -1;
    },
    (h) => {
      h.window = 99;
    },
  ]) {
    const p = clone(snapshot.portfolios.coverage);
    mutate(p.heat.left["1"]);
    assert.throws(() => validatePortfolio(p));
  }
});
test("重号分布分母是期数减1，不隐藏完整性限制", () => {
  assert.equal(
    snapshot.distributions.left.sample_sizes.repeat_previous,
    snapshot.history.rows - 1,
  );
  const s = clone(snapshot);
  s.distributions.left.sample_sizes.repeat_previous++;
  assert.throws(() => validateSnapshot(s), /分布不合法/);
  s.distributions.left.sample_sizes.repeat_previous--;
  s.source.complete = true;
  assert.throws(() => validateSnapshot(s), /完整性/);
});
test("拒绝损坏、空白、原型字段、过大结果，不将网页快照当CLI结果", () => {
  for (const text of [
    "",
    "<html>",
    "{}",
    "null",
    "[]",
    '{"__proto__":{"mode":"coverage"}}',
    JSON.stringify(snapshot),
  ])
    assert.throws(() => parseLocalResult(text));
  assert.throws(
    () => parseLocalResult(" ".repeat(2 * 1024 * 1024 + 1)),
    /过大/,
  );
});
test("公共快照无本地路径与固定目标期，不公开完整CSV", () => {
  const raw = JSON.stringify(snapshot);
  assert.ok(!/\/Users\/|\/tmp\/|source_path|"target"/.test(raw));
  assert.ok(snapshot.recent_draws.length <= 8);
});
test("合法的未知来源快照可以展示但不冒充500网来源", () => {
  const s = clone(snapshot);
  s.source.url = null;
  assert.equal(validateSnapshot(s).source.url, null);
});
test("非法日历日期、期号年份不一致和样本窗口矛盾被拒绝", () => {
  const s = clone(snapshot);
  s.history.first_date = "9999-99-99";
  s.history.last_date = "9999-99-99";
  assert.throws(() => validateSnapshot(s), /日期/);
  s.history.first_date = "2013-02-30";
  assert.throws(() => validateSnapshot(s), /日期/);
  const r = localResult();
  r.cutoff.training_rows = 1;
  assert.throws(() => parseLocalResult(JSON.stringify(r)), /窗口/);
});
test("格式化和值跨度等特征不转成预测分数", () => {
  assert.equal(pad(1), "01");
  assert.equal(pad(35), "35");
  assert.equal(percent(2, 3), "66.7%");
  assert.equal(percent(0, 0), "—");
  const f = snapshot.portfolios.coverage.groups[0].left_features;
  assert.deepEqual(featureValues(f), [
    `${f.odd} : ${f.even}`,
    `${f.small} : ${f.large}`,
    String(f.sum),
    String(f.span),
    `${f.adjacent_pairs} 对`,
    `${f.repeat_previous} 个`,
    `${f.hot} / ${f.warm} / ${f.cold}`,
  ]);
});
test("展示资源使用相对路径，入口不上传数据或注入HTML", () => {
  const html = readFileSync(
    new URL("../../site/index.html", import.meta.url),
    "utf8",
  );
  assert.match(html, /lang="zh-CN"/);
  assert.match(html, /src="assets\/app.js"/);
  assert.match(html, /href="assets\/style.css"/);
  assert.ok(!/<script[^>]*src="https?:/.test(html));
  const js = readFileSync(
    new URL("../../site/assets/app.js", import.meta.url),
    "utf8",
  );
  assert.ok(!/innerHTML|insertAdjacentHTML|localStorage|sendBeacon/.test(js));
  assert.equal((js.match(/fetch\(/g) || []).length, 1);
});

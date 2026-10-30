/** 固定版本 Pyodide 在独立线程运行仓库模型，页面无服务端计算。 */
import {
  validateParameters,
  validateResearchParameters,
  MAX_CSV_BYTES,
} from "./engine.js";
/** @typedef {import('./engine.js').AnalysisParameters} AnalysisParameters */
/** @typedef {import('./engine.js').ResearchParameters} ResearchParameters */
/** @typedef {{FS:{writeFile:(path:string,data:Uint8Array|string)=>void,unlink:(path:string)=>void},globals:{set:(name:string,value:unknown)=>void,delete:(name:string)=>void},runPythonAsync:(code:string)=>Promise<any>,version:string}} PythonRuntime */
/** @typedef {{schema_version:number,model_sha256:string,research_sha256:string,conditional_core_sha256:string,data_sha256:string,history:{rows:number,first_id:string,last_id:string},source?:{url?:string|null,warnings?:string[]}}} Manifest */

export const PYODIDE_VERSION = "314.0.7";
const PYODIDE_BASE = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
/** @type {Promise<PythonRuntime>|null} */ let runtimePromise = null;
/** @type {Promise<{manifest:Manifest,model:Uint8Array,research:Uint8Array,conditional:Uint8Array}>|null} */ let assetsPromise =
  null;
/** @type {Uint8Array|null} */ let publicCSV = null;
let running = false;

/** @param {number} id @param {string} text */
function progress(id, text) {
  self.postMessage({ type: "progress", id, text });
}
/** @param {Uint8Array} bytes @returns {Promise<string>} */
async function sha256(bytes) {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new Uint8Array(bytes).buffer,
  );
  return [...new Uint8Array(digest)]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}
/** @param {string} filename @param {number} limit */
async function readAsset(filename, limit) {
  const response = await fetch(
    new URL(`../runtime/${filename}`, import.meta.url),
    { cache: "no-cache", credentials: "omit", signal: AbortSignal.timeout(30000) },
  );
  if (!response.ok)
    throw new Error(`无法读取${filename}（HTTP ${response.status}）`);
  const announced = Number(response.headers.get("Content-Length"));
  if (announced > limit) throw new Error(`${filename}超过文件大小上限`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength > limit) throw new Error(`${filename}超过文件大小上限`);
  return bytes;
}
async function getAssets() {
  if (!assetsPromise)
    assetsPromise = (async () => {
      const bytes = await readAsset("manifest.json", 65536);
      const manifest = /** @type {Manifest} */ (
        JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes))
      );
      if (
        manifest.schema_version !== 1 ||
        !/^[a-f0-9]{64}$/.test(manifest.model_sha256) ||
        !/^[a-f0-9]{64}$/.test(manifest.data_sha256) ||
        !/^[a-f0-9]{64}$/.test(manifest.research_sha256) ||
        !/^[a-f0-9]{64}$/.test(manifest.conditional_core_sha256)
      )
        throw new Error("发布清单格式错误，停止计算");
      const model = await readAsset("model.py", 1024 * 1024);
      if ((await sha256(model)) !== manifest.model_sha256)
        throw new Error("Python模型哈希与发布清单不一致，请刷新页面后重试");
      const research = await readAsset("research.py", 1024 * 1024);
      const conditional = await readAsset("conditional_core.py", 1024 * 1024);
      if (
        (await sha256(research)) !== manifest.research_sha256 ||
        (await sha256(conditional)) !== manifest.conditional_core_sha256
      )
        throw new Error("研究模块哈希与发布清单不一致，停止计算");
      return { manifest, model, research, conditional };
    })();
  return assetsPromise;
}
/** @returns {Promise<PythonRuntime>} */
async function getRuntime() {
  if (!runtimePromise)
    runtimePromise = (async () => {
      // 动态导入仅使用官方文档提供的固定版本CDN，不拼接任何用户参数。
      const entry = `${PYODIDE_BASE}pyodide.mjs`;
      const { loadPyodide } = await import(entry);
      return /** @type {PythonRuntime} */ (
        await loadPyodide({ indexURL: PYODIDE_BASE })
      );
    })();
  return runtimePromise;
}

// 参数通过JSON数据传入，不在Python源码中插值；不执行用户提供的代码。
const ANALYZE = `
import json, sys
from collections import Counter
from pathlib import Path
import model

def _browser_analyze():
    params = json.loads(_browser_parameters)
    context = json.loads(_browser_context)
    records, audit = model.load_data('/input.csv')
    history, cutoff = model.select_history(records, params['target'])
    result = model.generate_portfolio(history, seed=params['seed'], groups=params['groups'], mode=params['mode'])
    audit.pop('source_path', None)
    result['audit'] = audit
    result['cutoff'] = cutoff
    warnings = list(audit['warnings'])
    warnings.append('第三方历史数据与完整性未作官方核验；本工具不声称预测优势。')
    if len(history) < 100:
        warnings.append(f'只有{len(history)}期历史，少于100期；按实际样本计算，不补造数据。')
    if history[0]['id'] != model.HISTORY_START_ISSUE:
        warnings.append('有效历史未从23001开始，不能视为2023年以来的完整数据。')
    gaps = [{'after': a['id'], 'before': b['id']} for a, b in zip(history, history[1:])
            if (a['id'][:2] == b['id'][:2] and int(b['id']) != int(a['id']) + 1)
            or int(b['id'][:2]) > int(a['id'][:2]) + 1]
    if gaps:
        warnings.append('历史存在同年或整年缺口；频率窗口、重号及遗漏按已有记录而非连续实际期数计算。')
    target = params['target']
    last_id = history[-1]['id']
    predecessor_present = int(target[2:]) > 1 and int(last_id) == int(target) - 1
    if int(target[2:]) > 1 and not predecessor_present:
        warnings.append(f'数据截止{last_id}，未包含目标{target}的上一期，可能陈旧或目标尚远；不宣称最新完整。')
    if int(target[2:]) == 1:
        warnings.append('目标为当年首期；五位期号不能证明上年末期完整性。')
    if context['data_origin'] == 'local':
        warnings.append('使用用户在浏览器本地选择的CSV；来源真实性未核验，文件未上传。')
    else:
        warnings.append('使用已发布的公共历史快照；后台定时检查不等于实时更新，获取新版本需刷新网页并重新生成。')
    result['quality_warnings'] = warnings
    result['data_quality'] = {'training_count': len(history), 'training_last_id': last_id,
        'target_predecessor_present': predecessor_present, 'history_gaps': gaps,
        'complete_history_verified': False, 'warnings': warnings}
    result['runtime'] = {'name': 'Pyodide', 'pyodide_version': context['pyodide_version'],
        'python_version': sys.version.split()[0], 'model_sha256': context['model_sha256'],
        'data_origin': context['data_origin'], 'data_sha256': audit['source_sha256']}
    result['display_name'] = '大乐透选号分析'
    metrics = ('odd', 'small', 'sum', 'span', 'adjacent_pairs', 'repeat_previous')
    distribution = {}
    for zone, maximum in (('left', 35), ('right', 12)):
        counts = {metric: Counter() for metric in metrics}
        for index, row in enumerate(history):
            previous = history[index - 1][zone] if index else ()
            profile = model.features(row[zone], maximum, previous)
            for metric in metrics:
                if metric != 'repeat_previous' or index:
                    counts[metric][profile[metric]] += 1
        distribution[zone] = {metric: [{'value': value, 'count': count} for value, count in sorted(counts[metric].items())] for metric in metrics}
        distribution[zone]['sample_sizes'] = {metric: len(history) - (metric == 'repeat_previous') for metric in metrics}
    result['web_distributions'] = distribution
    return json.dumps(result, ensure_ascii=False, allow_nan=False)

_browser_analyze()
`;

// 独立研究返回结构，不把号码池伪装成单式Portfolio。
const RESEARCH = `
import json, sys
import model, research

def _browser_research():
    params = json.loads(_browser_parameters)
    context = json.loads(_browser_context)
    records, audit = model.load_data('/input.csv')
    result = research.generate_research(records, params['target'], params['poolSize'])
    history, _ = model.select_history(records, params['target'])
    # 与 CLI data_quality 保持同级检查；不能把结构合法或成功计算说成历史完整。
    target = params['target']
    quality_warnings = []
    if history[0]['id'] != model.HISTORY_START_ISSUE:
        quality_warnings.append('有效历史未从23001开始，不能视为2023年以来的完整数据。')
    missing = [{'after': a['id'], 'before': b['id']} for a, b in zip(history, history[1:])
               if (a['id'][:2] == b['id'][:2] and int(b['id'][2:]) != int(a['id'][2:]) + 1)
               or int(b['id'][:2]) > int(a['id'][:2]) + 1]
    if missing:
        quality_warnings.append('存在同年或整年期号缺口；频率窗口和遗漏按已有记录计数，不代表连续实际期数。')
    last_id = history[-1]['id']
    predecessor_present = int(target[2:]) > 1 and int(last_id) == int(target) - 1
    if int(target[2:]) > 1 and not predecessor_present:
        quality_warnings.append(f'数据截止{last_id}，未包含目标{target}的上一期；可能陈旧或目标尚远，不宣称最新完整。')
    if int(target[2:]) == 1:
        quality_warnings.append('目标为当年首期；仅凭五位期号不能确认上年最后一期完整性。')
    result['data_quality'] = {'training_count': len(history), 'training_last_id': last_id,
        'target_predecessor_present': predecessor_present, 'within_year_gaps': missing,
        'warnings': quality_warnings, 'complete_history_verified': False,
        'completeness_note': '连续性和上一期检查不是第三方数据准确性或跨年全量完整性的证明。'}
    audit.pop('source_path', None)
    result['audit'] = audit
    result['runtime'] = {'name': 'Pyodide', 'pyodide_version': context['pyodide_version'],
        'python_version': sys.version.split()[0], 'model_sha256': context['model_sha256'],
        'research_sha256': context['research_sha256'], 'conditional_core_sha256': context['conditional_core_sha256'],
        'data_origin': context['data_origin'], 'data_sha256': audit['source_sha256']}
    result['warnings'] = list(dict.fromkeys([
        *result['warnings'], *audit['warnings'], *quality_warnings,
        '第三方数据未逐条官方核验；来源哈希不证明真实性或完整性。',
        '研究仅在至少200期有效历史（100期特征预热 + 100行学习样本）时运行；不足时停止，不回退到其他模式。',
        '本地CSV未上传，来源未核验。' if context['data_origin'] == 'local' else '使用已发布公共历史；后台定时检查不保证最新完整，更新后需刷新网页再运行实验。',
    ]))
    return json.dumps(result, ensure_ascii=False, allow_nan=False)

_browser_research()
`;

/** @param {number} id @param {AnalysisParameters|ResearchParameters} input @param {'analysis'|'research'} task */
async function analyze(id, input, task) {
  const params =
    task === "research"
      ? validateResearchParameters(/** @type {ResearchParameters} */ (input))
      : validateParameters(/** @type {AnalysisParameters} */ (input));
  progress(id, "正在校验发布模型与历史数据…");
  const { manifest, model, research, conditional } = await getAssets();
  let csv;
  if (params.csvText !== undefined)
    csv = new TextEncoder().encode(params.csvText);
  else {
    if (!publicCSV) {
      const bytes = await readAsset("history.csv", MAX_CSV_BYTES);
      if ((await sha256(bytes)) !== manifest.data_sha256)
        throw new Error("公共历史数据哈希与发布清单不一致，停止计算");
      publicCSV = bytes;
    }
    csv = publicCSV;
  }
  // 使用原始UTF-8字节，以便Python审计哈希反映实际输入，不悄悄改写CSV。
  new TextDecoder("utf-8", { fatal: true }).decode(csv);
  progress(id, "正在加载 Python 运行时（首次下载较慢，可取消）…");
  const python = await getRuntime();
  python.FS.writeFile("/model.py", model);
  python.FS.writeFile("/research.py", research);
  python.FS.writeFile("/conditional_core.py", conditional);
  python.FS.writeFile("/input.csv", csv);
  python.globals.set(
    "_browser_parameters",
    JSON.stringify(
      Object.fromEntries(
        Object.entries(params).filter(([key]) => key !== "csvText"),
      ),
    ),
  );
  python.globals.set(
    "_browser_context",
    JSON.stringify({
      model_sha256: manifest.model_sha256,
      research_sha256: manifest.research_sha256,
      conditional_core_sha256: manifest.conditional_core_sha256,
      pyodide_version: PYODIDE_VERSION,
      data_origin: params.csvText !== undefined ? "local" : "public",
    }),
  );
  progress(
    id,
    task === "research"
      ? "研究模型正在生成历史学习样本、拟合条件权重与固定规模号码池…"
      : "原版模型正在校验CSV、截断目标期并生成组合…",
  );
  try {
    await python.runPythonAsync(
      "import sys\nif '/' not in sys.path: sys.path.insert(0, '/')",
    );
    const result = await python.runPythonAsync(
      task === "research" ? RESEARCH : ANALYZE,
    );
    if (typeof result !== "string")
      throw new Error("Python未返回有效JSON字符串");
    return JSON.parse(result);
  } finally {
    python.FS.unlink("/input.csv");
    python.globals.delete("_browser_parameters");
    python.globals.delete("_browser_context");
  }
}

self.addEventListener("message", async (event) => {
  const message = event.data;
  if (message?.type !== "run" || !Number.isSafeInteger(message.id)) return;
  if (running) {
    self.postMessage({
      type: "error",
      id: message.id,
      error: "计算线程忙，请等待当前推演结束",
    });
    return;
  }
  running = true;
  try {
    if (message.task !== "research" && message.task !== "analysis")
      throw new Error("未知计算任务");
    const result = await analyze(message.id, message.params, message.task);
    self.postMessage({ type: "result", id: message.id, result });
  } catch (error) {
    self.postMessage({
      type: "error",
      id: message.id,
      error: error instanceof Error ? error.message : String(error),
    });
  } finally {
    running = false;
  }
});

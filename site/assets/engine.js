/** 浏览器内的原版 Python 模型入口；不把参数或 CSV 发往服务器。 */
/** @typedef {{target:string,seed:number,groups:number,mode:'coverage'|'uniform',csvText?:string}} AnalysisParameters */
/** @typedef {{target:string,poolSize:"5+2"|"5+5"|"7+3"|"8+3",csvText?:string}} ResearchParameters */
/** @typedef {Record<string, any>} AnalysisResult */
/** @typedef {{id:number,resolve:(value:AnalysisResult)=>void,reject:(error:Error)=>void,progress:(text:string)=>void,timer:ReturnType<typeof setTimeout>}} Pending */

export const MAX_CSV_BYTES = 2 * 1024 * 1024;
export const ANALYSIS_TIMEOUT_MS = 120000;
/** UI显示Python异常结论；原始堆栈保留在Error.cause，不伪装为成功。 @param {unknown} input */
export function readableError(input) {
  const raw = String(input);
  const lines = raw.trim().split(/\r?\n/);
  return raw.includes("Traceback (most recent call last)")
    ? lines[lines.length - 1] || raw
    : raw;
}
/** @type {Worker|null} */ let worker = null;
/** @type {Pending|null} */ let pending = null;
let nextId = 0;

/** 只接受固定参数，不开放任意 Python 执行。 @param {AnalysisParameters} params @returns {AnalysisParameters} */
export function validateParameters(params) {
  if (!params || typeof params !== "object") throw new Error("缺少推演参数");
  if (
    typeof params.target !== "string" ||
    !/^[0-9]{5}$/.test(params.target) ||
    Number(params.target.slice(2)) < 1
  )
    throw new Error("目标期号必须为五位数字，且年内序号大于0");
  if (Number(params.target) <= 23001)
    throw new Error(
      "2023-01-01起且目标期之前没有历史数据；目标期必须晚于23001",
    );
  if (!Number.isSafeInteger(params.seed))
    throw new Error("随机种子必须是安全整数");
  if (
    !Number.isSafeInteger(params.groups) ||
    params.groups < 1 ||
    params.groups > 6
  )
    throw new Error("网页支持1至6组组合");
  if (params.mode !== "coverage" && params.mode !== "uniform")
    throw new Error("请选择分散覆盖或均匀抽样");
  if (
    params.csvText !== undefined &&
    (typeof params.csvText !== "string" || !params.csvText.trim())
  )
    throw new Error("导入的CSV为空或不是文本");
  if (
    params.csvText !== undefined &&
    new TextEncoder().encode(params.csvText).byteLength > MAX_CSV_BYTES
  )
    throw new Error("CSV超过2MB上限");
  return {
    target: params.target,
    seed: params.seed,
    groups: params.groups,
    mode: params.mode,
    ...(params.csvText !== undefined ? { csvText: params.csvText } : {}),
  };
}

/** @param {Error} error */
function fail(error) {
  const request = pending;
  pending = null;
  worker?.terminate();
  worker = null;
  if (request) {
    clearTimeout(request.timer);
    request.reject(error);
  }
}

/** 中断包括首次加载的整个 worker；下一次运行重新创建，旧消息不能覆盖结果。 */
export function cancelAnalysis() {
  fail(new Error("推演已取消，保留上一次有效结果"));
}

/** @param {ResearchParameters} params @returns {ResearchParameters} */
export function validateResearchParameters(params) {
  if (!params || !["5+2", "5+5", "7+3", "8+3"].includes(params.poolSize))
    throw new Error("研究号码池必须为5+2、5+5、7+3或8+3");
  const common = validateParameters({
    target: params.target,
    seed: 0,
    groups: 1,
    mode: "uniform",
    ...(params.csvText !== undefined ? { csvText: params.csvText } : {}),
  });
  return {
    target: common.target,
    poolSize: params.poolSize,
    ...(common.csvText !== undefined ? { csvText: common.csvText } : {}),
  };
}
/** @param {AnalysisParameters} params @param {(text:string)=>void} [onProgress] @returns {Promise<AnalysisResult>} */
export function runAnalysis(params, onProgress = () => {}) {
  try {
    return launch(validateParameters(params), "analysis", onProgress);
  } catch (error) {
    return Promise.reject(error);
  }
}
/** @param {ResearchParameters} params @param {(text:string)=>void} [onProgress] @returns {Promise<AnalysisResult>} */
export function runResearch(params, onProgress = () => {}) {
  try {
    return launch(validateResearchParameters(params), "research", onProgress);
  } catch (error) {
    return Promise.reject(error);
  }
}
/** @param {AnalysisParameters|ResearchParameters} clean @param {'analysis'|'research'} task @param {(text:string)=>void} onProgress @returns {Promise<AnalysisResult>} */
function launch(clean, task, onProgress) {
  if (pending)
    return Promise.reject(new Error("已有推演正在进行，请等待完成或先取消"));
  if (typeof Worker === "undefined")
    return Promise.reject(
      new Error("此浏览器不支持Web Worker，请使用较新的浏览器"),
    );
  return new Promise((resolve, reject) => {
    try {
      if (!worker) {
        const owned = new Worker(
          new URL("./engine-worker.js", import.meta.url),
          { type: "module" },
        );
        worker = owned;
        owned.addEventListener("message", (event) => {
          if (worker !== owned || !pending || event.data?.id !== pending.id)
            return;
          const message = event.data;
          if (message.type === "progress") {
            try {
              pending.progress(String(message.text));
            } catch (error) {
              fail(error instanceof Error ? error : new Error(String(error)));
            }
            return;
          }
          if (message.type === "error") {
            fail(
              new Error(readableError(message.error), {
                cause: String(message.error),
              }),
            );
            return;
          }
          if (message.type === "result") {
            const request = pending;
            pending = null;
            clearTimeout(request.timer);
            request.resolve(message.result);
          }
        });
        owned.addEventListener("error", (event) => {
          if (worker !== owned) return;
          event.preventDefault();
          fail(
            new Error(
              `浏览器计算引擎启动失败：${event.message || "无法加载运行时，请检查网络后重试"}`,
            ),
          );
        });
        owned.addEventListener("messageerror", () => {
          if (worker === owned)
            fail(new Error("无法读取浏览器计算结果，请重试"));
        });
      }
      const id = ++nextId;
      pending = {
        id,
        resolve,
        reject,
        progress: onProgress,
        timer: setTimeout(
          () =>
            fail(
              new Error("推演超过120秒，已停止。请检查运行时下载网络后重试"),
            ),
          ANALYSIS_TIMEOUT_MS,
        ),
      };
      onProgress("准备浏览器计算引擎；首次需下载 Python 运行时…");
      worker.postMessage({ type: "run", task, id, params: clean });
    } catch (error) {
      const reason = error instanceof Error ? error : new Error(String(error));
      if (pending) fail(reason);
      else reject(reason);
    }
  });
}

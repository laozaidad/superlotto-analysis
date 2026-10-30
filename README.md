# 大乐透选号分析

可复现、可审计的大乐透选号分析 Skill。内部标识为 `superlotto`，适用于 **Left 35选5 / Right 12选2**。

计算奇偶比、大小比、和值、跨度、连号、重号与冷热，生成分散覆盖参考组合；另提供隔离的条件融合研究入口与固定规格单式/复式号码池。记录实际数据范围、参数、代码和数据哈希。

**数据范围固定为2023-01-01起（含当天，对应23001起），且严格早于用户指定的目标期。** 原CSV可保留更早记录，但旧记录只用于输入审计，不进入分析或选号。

**可靠指数据处理与计算可验证，不代表可以预测开奖。** 独立均匀假设下，每个固定完整组合全中概率都是 `1 / 21,425,712`。冷热、遗漏和形态分数不是中奖置信度，不构成购彩建议。

## 网页分析与推演

[打开大乐透选号分析网页](https://laozaidad.github.io/superlotto-analysis/)

网页使用 GitHub Pages 托管，可查看历史统计，也可**在浏览器中实际运行本仓库原版 Python 模型**。计算由独立的 module worker 执行，不另写一套 JavaScript 选号算法，不需要自建服务器或登录账户。

### 在网页上生成

1. 填写**五位目标期号**，不预设某一期；输入随机种子（默认0）与组数（1–6组），选择分散覆盖或均匀抽样。
2. 使用已发布的公共历史，或选择本地 CSV。网页仅纳入2023-01-01起且严格早于目标期的有效记录；本地文件无效时会报错，不偷偷换成公共数据。
3. 点击生成，浏览器执行原版模型，显示实际训练截止期、号码、形态特征和冷热。更改参数不会悄悄重算，需要再次点击生成；固定种子用于复现，不代表概率优势。
4. 可下载新计算的 JSON，也可导入本版本2023范围的普通 Skill JSON 查看。旧2013范围结果应保留原档，不改元数据冒充新版结果。初始 `site/data/snapshot.json` 只是展示基准，不代替点击生成时的实际计算。

页面的独立“条件融合研究”区可选目标和固定号码池规格，显示样本截止、专家权重、组合数与基本金额；不足200条有效此前历史时拒绝。研究与普通结果分开展示、分开下载。页面也展示已留档2026探索的复核证据，不把未检出优势包装成更准的预测。

**首次运行需要联网加载 Python WebAssembly 运行时。** 页面固定使用 [Pyodide 314.0.7](https://pyodide.org/en/stable/usage/webworker.html)，从 jsDelivr 下载；首次加载可能较慢，界面提供进度状态、失败重试与取消。取消会停止当前 worker，后续生成可重新初始化。浏览器须支持 WebAssembly 和 module worker；运行时下载失败时不会以预存组合冒充计算结果，仍可使用本地 Python CLI。

### 数据、隐私与边界

- **公共历史不是实时数据。** `site/runtime/history.csv` 是为网页独立从500网获取的2023年以来公开历史，不是用户的私人 CSV。页面标明实际截止范围；500网是第三方数据源，抓取成功不等于官方认证或全历史无缺漏。
- **原模型与数据可核对。** `site/runtime/` 中的 `model.py`、`research.py`、`conditional_core.py` 与 Skill 脚本逐字节一致；`manifest.json` 记录三个模块和网页历史 CSV 的 SHA-256。worker 在计算前校验这些文件，失败则停止。哈希验证的是文件一致性，不是开奖来源真实性。
- **本地 CSV、JSON 不上传。** 应用仅在当前浏览器中读取所选文件和计算；不会把文件内容发送给 GitHub、jsDelivr 或500网。页面与公共数据仍从 GitHub Pages 下载，Python 运行时从 jsDelivr 下载，因此首次使用不是完全离线，也会向这些服务发起普通资源请求。
- **后台定时检查，浏览器不实时刷新。** GitHub Actions 每天北京时间（UTC+8）07:30、22:30 检查500网公开历史；有新增且校验通过后才更新并发布。浏览器不会跨域抓500网，也不会自动重算已显示结果。更新发布后请刷新网页，再点击生成；本地 CSV 不受后台任务影响。
- **仅发布 `site/`。** 发布内容包括网页、展示快照、独立公共历史、原版模型和清单；用户工作目录、私人 CSV、个人路径与验证日志不随网页发布。生成结果仍是组合设计，不是已经证实的开奖预测。

### 本地预览

在仓库根目录启动静态服务，然后访问 `http://localhost:8000`；不要直接双击 HTML，以免浏览器限制模块和 JSON 加载。

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory site
```

### 更新公共数据与运行资源

`Deploy analysis website` 在每天北京时间（与新加坡同为 UTC+8）**07:30、22:30**，以及推送到 `main` 或手动运行时检查公开历史。cron 使用 UTC 的 `30 14,23 * * *`。流程如下：

1. 从500网独立抓取23001起的公开数据到临时目录，不读取用户私人 CSV。
2. 校验来源侧车与哈希、号码和日期、期号连续性；候选必须保留全部已发布记录，拒绝修改旧开奖、丢失记录、缺期或未来日期。
3. 无新增时保持公开文件与时间戳不变，不创建空提交；有新增时从同一份来源重建快照、公共 CSV、模型副本及哈希清单，通过检查后仅提交受控公共产物，并在同次 workflow 部署。固定研究回测证据不会随数据更新被重写。

每次成功的定时检查都会验证并部署当前保存的版本，即使没有新增数据也会尝试部署，以恢复前次可能发生的部署失败；这不会改写数据或制造空提交。

抓取或校验失败时不提交新数据，保留旧公共历史；若数据已成功推送但部署失败，仓库可能已有新数据，线上仍是旧版。以页面显示的实际截止期和 Actions 部署结果为准，不把任务启动视为更新成功。

查看或重试：[Actions → Deploy analysis website](https://github.com/laozaidad/superlotto-analysis/actions/workflows/pages.yml) → **Run workflow**，选择 `main`。`refresh_history` 默认启用；源站故障期间需要仅发布代码修复时，可取消勾选，沿用已保存的公共历史。

GitHub 的定时任务可能延迟或被丢弃；公开仓库连续60天无活动会自动停用定时 workflow，需在 Actions 中重新启用。因此这不是实时数据服务，也不承诺准点或永不中断。见 [GitHub schedule 官方说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

在完整仓库中手动执行同样的更新校验：

```bash
python3 scripts/update_history.py --site-dir site
```

也可显式提供独立取得的公共 CSV，必须同时保留与其哈希匹配的原始500网来源侧车：

```bash
python3 scripts/update_history.py --site-dir site \
  --source-csv "${PUBLIC_CSV:?请设置独立公开CSV路径}"
```

本地命令只更新工作目录的受控公共文件，不自动提交或发布。不要将私人 CSV、带个人路径的原始运行报告放进 `site/`。只更新模型运行资源时，仍可从明确可公开的同一来源显式构建：

```bash
PUBLIC_DATA_DIR=$(mktemp -d)
python3 skills/superlotto/scripts/fetch_data.py \
  --output "$PUBLIC_DATA_DIR/numbers.csv" --start 23001
python3 scripts/build_site_data.py \
  --data "$PUBLIC_DATA_DIR/numbers.csv" \
  --output "$PUBLIC_DATA_DIR/snapshot.json" \
  --runtime-dir "$PUBLIC_DATA_DIR/runtime"
```

核对新文件的实际首末期、记录数、来源警告与哈希，确认没有个人信息后，将 `snapshot.json` 替换到 `site/data/snapshot.json`，并将同次生成的 `runtime/model.py`、`runtime/research.py`、`runtime/conditional_core.py`、`runtime/history.csv`、`runtime/manifest.json` 一起替换到 `site/runtime/`，不要混用不同批次。修改模型后也需重新生成运行资源，以通过部署前的一致性检查。

清单中的 `data_sha256` 对应规范化后的 `site/runtime/history.csv`；`source.sha256` 对应抓取时的原 CSV，两者可能因为编码和换行规范化不同，不应混淆。原始抓取文件及其侧车可保留在维护者本地，不必另行入库。

### 发布方式

仓库的 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。`Deploy analysis website` workflow 按上面的开关检查公开历史，执行 Python 与网页检查，验证运行模型与仓库模型相同、清单哈希匹配，再仅打包 `site/` 并部署到 `github-pages` 环境。自动数据提交与部署在同次流程完成，不依赖机器人推送再次触发 workflow；PR 不触发网站部署，手动选择其他分支也不会发布。

配置遵循 [GitHub Pages 自定义 workflow 文档](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。网站是否已发布，以 Actions 部署成功和实际网址可访问为准。

## 运行要求

- **命令行 Skill：** Python **3.10+**，模型仅使用标准库，无需安装第三方 Python 包。
- 命令行有本地历史 CSV 时可以完全离线运行；没有数据时需访问 [500网大乐透历史数据](https://datachart.500.com/dlt/)。
- **网页：** 支持 WebAssembly、module worker 的现代浏览器；首次计算需联网下载上述固定版本 Pyodide，不需要在电脑上安装 Python。
- 仓库只发布独立获取的2023年以来公共历史，不上传用户私人数据，也不内置固定目标期推荐。

## 安装 Skill

将本仓库的 `skills/superlotto` 文件夹复制到 Codex 的 `~/.codex/skills/superlotto`。如果使用自定义 `CODEX_HOME`，安装到其 `skills/superlotto` 下。已有同名目录时先比较内容，不直接覆盖。

也可以让 Codex 的 skill-installer 从本仓库安装，指定仓库内路径 **`skills/superlotto`**。

随后可以这样调用：

> 使用 $superlotto 分析我指定的目标期，只考虑2023年以来的数据，优先读取我的历史CSV；没有数据则从500网获取，输出5组覆盖型参考组合及数据截止期。

## 命令行使用

先将环境变量 `TARGET` 设置为用户指定的五位目标期号，再在仓库根目录运行；不预设当前期次：

```bash
python3 skills/superlotto/scripts/run_skill.py \
  --data data/numbers.csv \
  --target "${TARGET:?请先设置用户指定的五位目标期号}" \
  --seed 0 \
  --groups 5 \
  --output outputs/result.json
```

只有2023-01-01起且目标之前的历史才会进入模型。更早记录、目标期及未来期不会影响生成；筛选后没有有效记录时拒绝生成。随机种子默认0，仅用于复现。

- 默认模式 `coverage`，支持1–6组；5组可覆盖25个Left和10个Right，组间各区不重号。
- 加 `--mode uniform` 使用同组数均匀抽样对照。
- 只需要一组时使用 `--groups 1`。组数是输出规模，不是建议购买量。
- 相同数据、代码/Python版本、目标、参数和种子可复现结果。不要频繁换种子挑选结果后宣称有预测优势。
- 输出文件已存在时拒绝覆盖，请使用新的 `--output` 路径。入口没有 `--refresh` 或 `--overwrite` 参数。

JSON 包含号码、逐组特征、冷热、覆盖和交集、源数据审计、训练截止期与概率事件说明。当前 `prediction_gate` 保持 `CLOSED`，不会将历史统计包装成已验证的预测权重。

## 条件融合研究入口

此模式复用附件研究中的纯函数，把硬编码期次与本地目录依赖移除。它不是精度提升承诺，也不会替换默认coverage／uniform。

```bash
python3 skills/superlotto/scripts/run_research.py \
  --data data/numbers.csv \
  --target "${TARGET:?请先设置用户指定的五位目标期号}" \
  --pool-size 5+2 \
  --output outputs/research-result.json
```

- 至少200条2023起且目标之前记录：100期形成历史特征，至少100行已揭晓学习样本训练条件成绩。
- 固定5专家、10维历史状态、岭系数10、温度0.5，按此前排名相似度软降权；权重不是中奖概率。
- 固定规格可选5+2、5+5、7+3、8+3；基本组合数分别1、10、63、168，基本金额分别2、20、126、336元，不含追加。只作计数说明，不执行购彩。
- 输出保留训练/学习截止、权重、相似度、参数、代码与输入哈希；已有文件拒绝覆盖。本地快照不提供可信时间戳或不可篡改证明。
- 2026年123期已查看历史中，等权单式命中85/40、条件权重81/45、条件＋软降冗余91/36；没有证明比同规模随机更准。参数来源是已有探索，不声称任意历史期都曾事前预注册。

可独立复核已留档的逐期预测与实际结果（不重新训练，也不是新增盲测）：

```bash
python3 scripts/build_research_evidence.py \
  --input site/data/research-study.json \
  --output site/data/research-evidence.json
```

完整定义、费用规则来源与未来验证要求见 [条件融合研究说明](skills/superlotto/references/research.md)。

## 数据依赖与自动获取

CSV 表头必须为：

```csv
No.,L1,L2,L3,L4,L5,R1,R2,Date
```

- `No.`：五位期号字符串，保留前导0，按期号递增。
- `L1`–`L5`：1–35中5个不同号码，升序。
- `R1`–`R2`：1–12中2个不同号码，升序。
- `Date`：`YYYY-MM-DD`，或可解析的ISO时间戳；日期递增。

数据策略：

| 情况 | 行为 |
|---|---|
| 指定 CSV 存在且有效 | 保留原文件，仅使用2023年以来且目标之前的记录，不自动刷新、不混入外部数据 |
| 指定 CSV 不存在 | 默认从23001起获取500网历史数据，校验后写入并记录来源元数据 |
| 文件存在但无效 | 报错，不悄悄替换用户文件 |
| 网页失败或结构不符 | 停止，不伪造历史；可提供合规CSV或保存的历史页HTML |
| 普通模式不足100期或数据陈旧 | 使用真实样本并明确报告局限，不补造期次 |
| 条件融合研究不足200条有效此前历史 | 明确拒绝，不借用早年数据或自动换算法 |

500网是第三方数据源，不是官方核验。抓取成功也不代表全历史完整；需查看记录数、实际首末期、目标附近覆盖及元数据警告。CLI 已有数据不会因运行选号而自动刷新；需要更新本地数据时显式抓取到新路径，核对后使用。网页公共历史由上述后台任务独立维护，不会更新本地文件。独立抓取参数见 `python3 skills/superlotto/scripts/fetch_data.py --help`。

独立抓取脚本的 `--overwrite` 仅用于用户明确要求覆盖数据的操作；不会由选号入口自动启用。解析或数据校验失败时入口退出码为2，不生成假结果。

抓取参数 `--start` 不得早于23001；离线HTML导入也会过滤2023年以前的记录。旧记录不参与频率、遗漏、上期重号、历史完整组合排除、形态评分或选号，不会从旧年借用“上期”数据。

完整历史组重复会告警但保留。默认生成器仅排除有效分析范围内已见完整组，这是自定义生成约束，不代表开奖不会重复，也不提高单组命中概率。

详见 [数据格式与来源说明](skills/superlotto/references/data-schema.md)。

## 方法与边界

模型采用“均匀概率基线＋历史特征描述＋组合覆盖＋预测验证准入”。不强制奇偶均衡、和值范围、冷热混搭或禁止连号；三连号计2对相邻连号。冷热使用最近100期相对均匀基准的 `z` 值标签，缺少100期时按实际可用数量计算，不把标签当显著性结论。

大数定律不是冷号补齐，均值回归不是反向补偿，覆盖增加不意味着单注全中概率增加。没有当期官方奖级、奖金及销量资料，不输出中奖收益或分奖优势。

此前使用更早年份数据得到的回测结果不作为本范围的验证。调整数据范围后，仍需按新范围重新计算并区分探索性回测与真正新增数据的确认。

详见 [模型与验证方法](skills/superlotto/references/methodology.md)。设计参考 [SSQ Analysis](https://github.com/TouKenAI/ssq-analysis)、[Daletou Analysis](https://github.com/TouKenAI/daletou-analysis) 的数据流程和独立核验思路；运行不依赖、也不执行这两个项目的代码。

## 开发验证

仅开发检查需要第三方依赖，建议使用独立虚拟环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/python -m unittest discover -s tests -v
```

GitHub Actions 在 Python 3.10、3.12 上执行同样的检查。单元测试默认离线；HTML夹具仅为解析测试用的少量公开历史行，不是默认历史数据库。真实网络抓取应另外验证来源、记录范围和校验结果。

修改网页还需 Node.js **22.13+（22.x）**，以满足当前锁定的 ESLint 10 开发依赖。安装锁定依赖后执行类型、lint 与网页测试；这些 Node 开发依赖不打包到网页中，也不是命令行 Skill 的运行依赖：

```bash
npm ci
npm run check
npm test
```

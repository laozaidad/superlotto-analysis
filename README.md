# 大乐透选号分析

可复现、可审计的大乐透选号分析 Skill。内部标识为 `superlotto`，适用于 **Left 35选5 / Right 12选2**。

计算奇偶比、大小比、和值、跨度、连号、重号与冷热，生成分散覆盖参考组合，并记录数据来源、截断期号、随机种子与数据哈希。

**数据范围固定为2013-01-01起（含当天，对应13001起），且严格早于用户指定的目标期。** 原CSV可保留更早记录，但旧记录只用于输入审计，不进入分析或选号。

**可靠指数据处理与计算可验证，不代表可以预测开奖。** 独立均匀假设下，每个固定完整组合全中概率都是 `1 / 21,425,712`。冷热、遗漏和形态分数不是中奖置信度，不构成购彩建议。

## 网页分析与推演

[打开大乐透选号分析网页](https://laozaidad.github.io/superlotto-analysis/)

网页使用 GitHub Pages 托管，可查看历史统计，也可**在浏览器中实际运行本仓库原版 Python 模型**。计算由独立的 module worker 执行，不另写一套 JavaScript 选号算法，不需要自建服务器或登录账户。

### 在网页上生成

1. 填写**五位目标期号**，不预设某一期；输入随机种子（默认0）与组数（1–6组），选择分散覆盖或均匀抽样。
2. 使用已发布的公共历史，或选择本地 CSV。网页仅纳入2013-01-01起且严格早于目标期的有效记录；本地文件无效时会报错，不偷偷换成公共数据。
3. 点击生成，浏览器执行原版模型，显示实际训练截止期、号码、形态特征和冷热。更改参数不会悄悄重算，需要再次点击生成；固定种子用于复现，不代表概率优势。
4. 可下载新计算的 JSON，也可导入已有 Skill JSON 查看。初始 `site/data/snapshot.json` 只是展示基准，不代替点击生成时的实际计算。

**首次运行需要联网加载 Python WebAssembly 运行时。** 页面固定使用 [Pyodide 314.0.7](https://pyodide.org/en/stable/usage/webworker.html)，从 jsDelivr 下载；首次加载可能较慢，界面提供进度状态、失败重试与取消。取消会停止当前 worker，后续生成可重新初始化。浏览器须支持 WebAssembly 和 module worker；运行时下载失败时不会以预存组合冒充计算结果，仍可使用本地 Python CLI。

### 数据、隐私与边界

- **公共历史不是实时数据。** `site/runtime/history.csv` 是为网页独立从500网获取的2013年以来公开历史，不是用户的私人 CSV。页面标明实际截止范围；500网是第三方数据源，抓取成功不等于官方认证或全历史无缺漏。
- **原模型与数据可核对。** `site/runtime/model.py` 与 `skills/superlotto/scripts/model.py` 逐字节一致；`site/runtime/manifest.json` 记录模型和网页历史 CSV 的 SHA-256。worker 在计算前校验这些文件，失败则停止。哈希验证的是文件一致性，不是开奖来源真实性。
- **本地 CSV、JSON 不上传。** 应用仅在当前浏览器中读取所选文件和计算；不会把文件内容发送给 GitHub、jsDelivr 或500网。页面与公共数据仍从 GitHub Pages 下载，Python 运行时从 jsDelivr 下载，因此首次使用不是完全离线，也会向这些服务发起普通资源请求。
- **不直接抓500网，不自动更新。** 网页使用已发布的公共 CSV，或用户明确选择的本地 CSV；不会跨域抓取500网、自动刷新已发布历史或定时获取数据。需要更近期数据时导入自己的合规 CSV，或由维护者显式更新公开版本。
- **仅发布 `site/`。** 发布内容包括网页、展示快照、独立公共历史、原版模型和清单；用户工作目录、私人 CSV、个人路径与验证日志不随网页发布。生成结果仍是组合设计，不是已经证实的开奖预测。

### 本地预览

在仓库根目录启动静态服务，然后访问 `http://localhost:8000`；不要直接双击 HTML，以免浏览器限制模块和 JSON 加载。

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory site
```

### 更新公共数据与运行资源

更新是显式维护操作，发布 workflow 不联网抓取开奖数据。先独立获取公开数据到新目录，再从**同一份来源**同时导出展示快照和浏览器运行资源。`--runtime-dir` 会生成可公开下载的历史 CSV，必须使用明确可公开的独立数据，不能用用户私人 CSV；也不要把带个人路径的原始运行报告直接提交到 `site/`。

```bash
PUBLIC_DATA_DIR=$(mktemp -d)
python3 skills/superlotto/scripts/fetch_data.py \
  --output "$PUBLIC_DATA_DIR/numbers.csv" --start 13001
python3 scripts/build_site_data.py \
  --data "$PUBLIC_DATA_DIR/numbers.csv" \
  --output "$PUBLIC_DATA_DIR/snapshot.json" \
  --runtime-dir "$PUBLIC_DATA_DIR/runtime"
```

核对新文件的实际首末期、记录数、来源警告与哈希，确认没有个人信息后，将 `snapshot.json` 替换到 `site/data/snapshot.json`，并将同次生成的 `runtime/model.py`、`runtime/history.csv`、`runtime/manifest.json` 一起替换到 `site/runtime/`，不要混用不同批次。修改模型后也需重新生成运行资源，以通过部署前的一致性检查。

清单中的 `data_sha256` 对应规范化后的 `site/runtime/history.csv`；`source.sha256` 对应抓取时的原 CSV，两者可能因为编码和换行规范化不同，不应混淆。原始抓取文件及其侧车可保留在维护者本地，不必另行入库。

### 发布方式

仓库的 **Settings → Pages → Build and deployment → Source** 选择 **GitHub Actions**。推送到 `main` 后，`Deploy analysis website` workflow 会先执行 Python 与网页检查，验证运行模型与仓库模型相同、清单哈希匹配，再仅打包 `site/` 并部署到 `github-pages` 环境；也可从 Actions 手动运行。PR 不触发网站部署，手动选择其他分支也不会发布。

配置遵循 [GitHub Pages 自定义 workflow 文档](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。网站是否已发布，以 Actions 部署成功和实际网址可访问为准。

## 运行要求

- **命令行 Skill：** Python **3.10+**，模型仅使用标准库，无需安装第三方 Python 包。
- 命令行有本地历史 CSV 时可以完全离线运行；没有数据时需访问 [500网大乐透历史数据](https://datachart.500.com/dlt/)。
- **网页：** 支持 WebAssembly、module worker 的现代浏览器；首次计算需联网下载上述固定版本 Pyodide，不需要在电脑上安装 Python。
- 仓库只发布独立获取的2013年以来公共历史，不上传用户私人数据，也不内置固定目标期推荐。

## 安装 Skill

将本仓库的 `skills/superlotto` 文件夹复制到 Codex 的 `~/.codex/skills/superlotto`。如果使用自定义 `CODEX_HOME`，安装到其 `skills/superlotto` 下。已有同名目录时先比较内容，不直接覆盖。

也可以让 Codex 的 skill-installer 从本仓库安装，指定仓库内路径 **`skills/superlotto`**。

随后可以这样调用：

> 使用 $superlotto 分析我指定的目标期，只考虑2013年以来的数据，优先读取我的历史CSV；没有数据则从500网获取，输出5组覆盖型参考组合及数据截止期。

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

只有2013-01-01起且目标之前的历史才会进入模型。更早记录、目标期及未来期不会影响生成；筛选后没有有效记录时拒绝生成。随机种子默认0，仅用于复现。

- 默认模式 `coverage`，支持1–6组；5组可覆盖25个Left和10个Right，组间各区不重号。
- 加 `--mode uniform` 使用同组数均匀抽样对照。
- 只需要一组时使用 `--groups 1`。组数是输出规模，不是建议购买量。
- 相同数据、代码/Python版本、目标、参数和种子可复现结果。不要频繁换种子挑选结果后宣称有预测优势。
- 输出文件已存在时拒绝覆盖，请使用新的 `--output` 路径。入口没有 `--refresh` 或 `--overwrite` 参数。

JSON 包含号码、逐组特征、冷热、覆盖和交集、源数据审计、训练截止期与概率事件说明。当前 `prediction_gate` 保持 `CLOSED`，不会将历史统计包装成已验证的预测权重。

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
| 指定 CSV 存在且有效 | 保留原文件，仅使用2013年以来且目标之前的记录，不自动刷新、不混入外部数据 |
| 指定 CSV 不存在 | 默认从13001起获取500网历史数据，校验后写入并记录来源元数据 |
| 文件存在但无效 | 报错，不悄悄替换用户文件 |
| 网页失败或结构不符 | 停止，不伪造历史；可提供合规CSV或保存的历史页HTML |
| 不足100期或数据陈旧 | 使用真实样本并明确报告局限，不补造期次 |

500网是第三方数据源，不是官方核验。抓取成功也不代表全历史完整；需查看记录数、实际首末期、目标附近覆盖及元数据警告。现有数据不会因运行选号而自动刷新；需要更新时显式抓取到新路径，核对后使用。独立抓取参数见 `python3 skills/superlotto/scripts/fetch_data.py --help`。

独立抓取脚本的 `--overwrite` 仅用于用户明确要求覆盖数据的操作；不会由选号入口自动启用。解析或数据校验失败时入口退出码为2，不生成假结果。

抓取参数 `--start` 不得早于13001；离线HTML导入也会过滤2013年以前的记录。旧记录不参与频率、遗漏、上期重号、历史完整组合排除、形态评分或选号，不会从旧年借用“上期”数据。

完整历史组重复会告警但保留。生成器仅排除有效分析范围内已见完整组，这是自定义生成约束，不代表开奖不会重复，也不提高单组命中概率。

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

#!/usr/bin/env python3
"""从500网已公开的大乐透历史页面取得CSV；不替换现有本地数据。"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timezone
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

HISTORY_URL = "https://datachart.500.com/dlt/history/history.shtml"
# 来自上述页面getChartdata()实际使用的地址与start/end参数，不是猜测接口。
DATA_URL = "https://datachart.500.com/dlt/history/newinc/history.php"
HEADERS = ["No.", "L1", "L2", "L3", "L4", "L5", "R1", "R2", "Date"]
MAX_RESPONSE_BYTES = 20 * 1024 * 1024
HISTORY_START_DATE = "2023-01-01"
HISTORY_START_ISSUE = "23001"


class FetchError(ValueError):
    """下载、页面结构或数据校验失败；不以示例数据代替。"""


def validate_issue(value: str, label: str = "期号") -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{5}", value) is None or int(value[2:]) < 1:
        raise FetchError(f"{label}必须为五位数字字符串，保留前导0")
    return value


class HistoryParser(HTMLParser):
    """只读tbody#tdata里的开奖行，不读取广告、销售额、登录表单。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_data = False
        self.sections = 0
        self.in_row = False
        self.in_cell = False
        self.cell_class: set[str] = set()
        self.cell_text: list[str] = []
        self.cells: list[tuple[set[str], str]] = []
        self.raw_rows: list[list[tuple[set[str], str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "tbody" and attributes.get("id") == "tdata":
            if self.in_data:
                raise FetchError("历史表格嵌套结构异常")
            self.in_data = True
            self.sections += 1
        elif self.in_data and tag == "tr":
            if self.in_row:
                raise FetchError("开奖行未正常结束")
            self.in_row = True
            self.cells = []
        elif self.in_data and self.in_row and tag == "td":
            if self.in_cell:
                raise FetchError("开奖单元格未正常结束")
            self.in_cell = True
            self.cell_class = set((attributes.get("class") or "").split())
            self.cell_text = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self.in_cell:
            self.cells.append((self.cell_class, "".join(self.cell_text).strip()))
            self.in_cell = False
        elif tag == "tr" and self.in_data and self.in_row:
            if self.in_cell:
                raise FetchError("开奖单元格不完整")
            self.raw_rows.append(self.cells)
            self.in_row = False
        elif tag == "tbody" and self.in_data:
            if self.in_row or self.in_cell:
                raise FetchError("历史数据被截断")
            self.in_data = False


def decode_html(raw: bytes) -> tuple[str, str]:
    """历史主页实测GB18030，查询片段实测UTF-8；严格解码，不丢弃非法字节。"""
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise FetchError("网页编码不是可识别的UTF-8或GB18030")


def parse_history_html(html: str) -> list[dict[str, Any]]:
    parser = HistoryParser()
    parser.feed(html)
    parser.close()
    if parser.sections != 1 or parser.in_data or parser.in_row or parser.in_cell:
        raise FetchError("找不到唯一且完整的tbody#tdata；网站结构可能已变化")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cells in parser.raw_rows:
        if not cells:
            continue
        number_cells = [text for classes, text in cells if classes & {"cfont2", "cfont4"}]
        identity = cells[0][1]
        if re.fullmatch(r"\d{5}", identity) is None:
            if number_cells or re.fullmatch(r"\d+", identity):
                raise FetchError(f"无法识别开奖期号：{identity!r}")
            # 广告/说明行允许跳过，但包含号码类或数字期号的坏行不得忽略。
            continue
        validate_issue(identity)
        if identity in seen:
            raise FetchError(f"重复期号：{identity}")
        left_text = [text for classes, text in cells if "cfont2" in classes]
        right_text = [text for classes, text in cells if "cfont4" in classes]
        if len(left_text) != 5 or len(right_text) != 2:
            raise FetchError(f"{identity}的5前2后结构不符，拒绝猜测新页面布局")
        if any(re.fullmatch(r"\d{1,2}", text) is None for text in left_text + right_text):
            raise FetchError(f"{identity}号码不是整数")
        left, right = sorted(map(int, left_text)), sorted(map(int, right_text))
        if len(set(left)) != 5 or not 1 <= min(left) <= max(left) <= 35:
            raise FetchError(f"{identity}前区重复或越界")
        if len(set(right)) != 2 or not 1 <= min(right) <= max(right) <= 12:
            raise FetchError(f"{identity}后区重复或越界")
        date_values = [text for _, text in cells if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text)]
        if len(date_values) != 1:
            raise FetchError(f"{identity}缺少唯一开奖日期")
        try:
            parsed_date = date.fromisoformat(date_values[0])
        except ValueError as exc:
            raise FetchError(f"{identity}开奖日期非法") from exc
        if parsed_date.year % 100 != int(identity[:2]):
            raise FetchError(f"{identity}期号年份与日期不一致")
        seen.add(identity)
        records.append({"id": identity, "left": left, "right": right, "date": parsed_date.isoformat()})
    if not records:
        raise FetchError("页面没有有效开奖行；可能为验证码、拦截页或结构变化")
    records.sort(key=lambda row: int(row["id"]))
    for previous, current in zip(records, records[1:]):
        if previous["date"] >= current["date"]:
            raise FetchError("按期号排序后开奖日期不是严格递增")
    return records


def read_url(url: str) -> tuple[bytes, str]:
    """仅访问公开HTTPS，超时20秒、最多2次尝试，不绕过TLS或登录验证。"""
    if urlsplit(url).scheme != "https" or urlsplit(url).hostname != "datachart.500.com":
        raise FetchError("仅允许500网数据域名的HTTPS地址")
    for attempt in range(2):
        request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html", "Accept-Encoding": "identity"})
        try:
            with urlopen(request, timeout=20) as response:
                final_url = response.geturl()
                if urlsplit(final_url).scheme != "https" or urlsplit(final_url).hostname != "datachart.500.com":
                    raise FetchError("数据地址重定向到非预期位置")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise FetchError("HTML超过20MB上限，停止而不是截断解析")
                return raw, final_url
        except HTTPError as exc:
            exc.close()
            if attempt == 0 and exc.code in (429, 500, 502, 503, 504):
                time.sleep(1)
                continue
            raise FetchError(f"500网返回HTTP {exc.code}；请稍后重试或下载公开历史HTML后用--html导入") from exc
        except (URLError, TimeoutError, OSError) as exc:
            if attempt == 0:
                time.sleep(1)
                continue
            raise FetchError(f"无法连接500网：{type(exc).__name__}；没有生成替代数据") from exc
    raise FetchError("下载未完成")


def _csv_bytes(records: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(HEADERS)
    for row in records:
        writer.writerow([row["id"], *(f"{number:02d}" for number in row["left"] + row["right"]), row["date"]])
    return output.getvalue().encode("utf-8-sig")


def _atomic_write(path: Path, payload: bytes, overwrite: bool) -> None:
    """同目录临时文件+原子替换/硬链接，拒绝覆盖时也防检查后的竞争写入。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
        temporary.unlink(missing_ok=True)
    except FileExistsError as exc:
        raise FetchError(f"文件已存在，未覆盖：{path}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def fetch_data(output: str | Path, target: str | None = None, start: str = HISTORY_START_ISSUE,
               end: str | None = None, html_path: str | Path | None = None,
               overwrite: bool = False) -> dict[str, Any]:
    """取得全部可用范围；metadata明确说明无法独立证明跨年完整性。"""
    output = Path(output).expanduser().resolve()
    metadata_path = output.with_suffix(output.suffix + ".metadata.json")
    if not overwrite and (output.exists() or metadata_path.exists()):
        raise FetchError("输出CSV或来源metadata已存在；默认不覆盖，可显式使用--overwrite")
    start = validate_issue(start, "起始期号")
    if int(start) < int(HISTORY_START_ISSUE):
        raise FetchError("只考虑2023-01-01以来的数据，起始期号不得早于23001")
    if target is not None:
        target = validate_issue(str(target), "目标期号")
    if end is not None:
        end = validate_issue(end, "结束期号")
    if target is not None and int(start) >= int(target):
        raise FetchError("起始期号必须早于目标期")
    if end is not None and int(start) > int(end):
        raise FetchError("起始期号晚于结束期号")
    source_urls: list[str] = []
    latest_observed: str | None = None
    effective_end: str | None = None
    if html_path is not None:
        source_path = Path(html_path).expanduser().resolve()
        raw = source_path.read_bytes()
        if len(raw) > MAX_RESPONSE_BYTES:
            raise FetchError("离线HTML超过20MB上限")
        source_kind = "offline_html"
    else:
        latest_raw, latest_url = read_url(HISTORY_URL)
        latest_html, _ = decode_html(latest_raw)
        latest_observed = parse_history_html(latest_html)[-1]["id"]
        desired_end = min(int(latest_observed), int(end) if end else int(latest_observed),
                          int(target)-1 if target else int(latest_observed))
        if desired_end < int(start):
            raise FetchError("网站尚无所请求范围的数据")
        effective_end = f"{desired_end:05d}"
        url = DATA_URL + "?" + urlencode({"start": start, "end": effective_end})
        raw, final_url = read_url(url)
        source_urls = [latest_url, final_url]
        source_kind = "500.com"
    html, encoding = decode_html(raw)
    parsed = parse_history_html(html)
    rows = [row for row in parsed if int(row["id"]) >= int(start)
            and row["date"] >= HISTORY_START_DATE
            and (end is None or int(row["id"]) <= int(end))
            and (target is None or int(row["id"]) < int(target))]
    if not rows:
        raise FetchError("严格过滤目标期和范围后没有历史数据")
    if html_path is None and rows[0]["id"] != start:
        raise FetchError(f"服务器返回范围可能被截断：请求起始{start}，实际起始{rows[0]['id']}；未保存部分数据")
    if effective_end is not None and effective_end == latest_observed and int(rows[-1]["id"]) < int(effective_end):
        raise FetchError(f"服务器未返回主页可见末期{latest_observed}，实际末期{rows[-1]['id']}；未保存可能被截断的数据")
    gaps: list[dict[str, str]] = []
    for previous, current in zip(rows, rows[1:]):
        if previous["id"][:2] == current["id"][:2] and int(current["id"]) != int(previous["id"]) + 1:
            gaps.append({"after": previous["id"], "before": current["id"]})
        elif int(current["id"][:2]) > int(previous["id"][:2]) + 1:
            gaps.append({"after": previous["id"], "before": current["id"]})
    if gaps:
        raise FetchError(f"公开数据存在期号缺口，未保存不完整CSV：{gaps[:3]}")
    payload = _csv_bytes(rows)
    metadata: dict[str, Any] = {
        "source": source_kind, "source_urls": source_urls,
        "source_path": str(Path(html_path).expanduser().resolve()) if html_path else None,
        "path": str(output), "metadata_path": str(metadata_path),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_html_sha256": hashlib.sha256(raw).hexdigest(), "encoding": encoding,
        "sha256": hashlib.sha256(payload).hexdigest(), "rows": len(rows),
        "first_id": rows[0]["id"], "last_id": rows[-1]["id"],
        "latest_observed_on_site": latest_observed, "target_exclusive": target,
        "history_start_date": HISTORY_START_DATE, "history_start_issue": HISTORY_START_ISSUE,
        "requested_start": start, "requested_end": end, "effective_requested_end": effective_end,
        "parsed_rows": len(parsed), "filtered_rows": len(parsed)-len(rows),
        "within_year_sequence_checked": True, "complete": False,
        "completeness_note": "已验证范围、号码、日期及同年期号连续；仅凭第三方页面不能证明每年末期和历史全量无缺漏，也不能证明其为官方最新数据。",
        "warnings": ["第三方公开数据，未与官方开奖源交叉核验；不补齐、不伪造缺失结果。"],
    }
    if html_path is not None:
        metadata["warnings"].append("离线HTML仅代表该快照范围，不代表全历史或实时最新。")
    if effective_end is not None and int(rows[-1]["id"]) < int(effective_end):
        metadata["warnings"].append(f"返回末期{rows[-1]['id']}早于请求上限{effective_end}；可能该上限并非开奖期号或响应尾部缺失，请核对，不声称完整。")
    if target is not None and int(rows[-1]["id"]) < int(target)-1:
        metadata["warnings"].append("历史末期小于目标期数值前一期；可能跨年、尚未开奖或缺数据，请核对，不自动补齐。")
    # 解析与校验全部结束才落盘。先写metadata，CSV出现即代表数据已完成写入。
    metadata_bytes = (json.dumps(metadata, ensure_ascii=False, indent=2)+"\n").encode("utf-8")
    old_metadata = metadata_path.read_bytes() if metadata_path.exists() else None
    _atomic_write(metadata_path, metadata_bytes, overwrite)
    try:
        _atomic_write(output, payload, overwrite)
    except OSError:
        if old_metadata is None:
            metadata_path.unlink(missing_ok=True)
        else:
            _atomic_write(metadata_path, old_metadata, True)
        raise
    except FetchError:
        if old_metadata is None:
            metadata_path.unlink(missing_ok=True)
        else:
            _atomic_write(metadata_path, old_metadata, True)
        raise
    return metadata


def ensure_data(path: str | Path, target: str | None = None) -> dict[str, Any]:
    """已有文件不联网、不更改；其内容合法性由选号模型校验。缺失才抓取。"""
    path = Path(path).expanduser().resolve()
    if path.exists():
        if not path.is_file():
            raise FetchError(f"数据路径不是文件：{path}")
        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        result: dict[str, Any] = {
            "source": "local", "path": str(path), "sha256": sha256,
            "downloaded": False, "target_exclusive": target, "warnings": [],
            "history_start_date": HISTORY_START_DATE, "history_start_issue": HISTORY_START_ISSUE,
        }
        metadata_path = path.with_suffix(path.suffix + ".metadata.json")
        if metadata_path.exists():
            try:
                provenance = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                result["warnings"].append("已有来源侧车无法解析；未采用其中来源，不联网、不修改本地文件。")
            else:
                if isinstance(provenance, dict) and provenance.get("sha256") == sha256:
                    result["provenance"] = provenance
                    result["provenance_hash_matches"] = True
                    result["provenance_note"] = "哈希匹配仅表示此侧车对应当前CSV，不是对来源真实性的独立认证。"
                else:
                    result["warnings"].append("已有来源侧车哈希不匹配或结构无效；未采用其中来源，不联网、不修改本地文件。")
        return result
    result = fetch_data(path, target=target)
    result["downloaded"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--target")
    parser.add_argument("--start", default=HISTORY_START_ISSUE, help="起始期号，固定下限23001")
    parser.add_argument("--end")
    parser.add_argument("--html", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = fetch_data(args.output, target=args.target, start=args.start,
                            end=args.end, html_path=args.html, overwrite=args.overwrite)
    except (FetchError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""抓取器离线测试：不联网，不把快照当历史全量。"""
import csv
from email.message import Message
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "skills/superlotto/scripts/fetch_data.py"
SPEC = importlib.util.spec_from_file_location("fetch_data_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
fetch = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fetch
SPEC.loader.exec_module(fetch)
FIXTURE = ROOT / "tests/fixtures/500_history_sample.html"
HTML = FIXTURE.read_text(encoding="utf-8")


class ParseTests(unittest.TestCase):
    def test_public_rows_and_encoding(self) -> None:
        records = fetch.parse_history_html(HTML)
        self.assertEqual([r["id"] for r in records], ["26121", "26122", "26123"])
        self.assertEqual(records[-1]["left"], [13, 18, 19, 20, 28])
        self.assertEqual(records[-1]["right"], [9, 11])
        self.assertEqual(records[-1]["date"], "2026-10-28")
        gb = HTML.encode("gb18030")
        decoded, encoding = fetch.decode_html(gb)
        self.assertEqual(encoding, "gb18030")
        self.assertEqual(fetch.parse_history_html(decoded), records)

    def test_ignores_advert_and_comments(self) -> None:
        changed = HTML.replace('</tbody>', '<tr><td colspan="15">推广说明，不是开奖行</td></tr></tbody>')
        self.assertEqual(fetch.parse_history_html(changed), fetch.parse_history_html(HTML))

    def test_structure_change_and_challenge_fail(self) -> None:
        broken = [HTML.replace('id="tdata"', 'id="other"'),
                  HTML.replace('class="cfont2"', 'class="new_ball"', 1),
                  '<html>请完成验证码</html>', HTML.replace('</tbody>', ''),
                  HTML.replace('>26123<', '>2026123<', 1)]
        for page in broken:
            with self.subTest(page=page[:100]):
                with self.assertRaises(fetch.FetchError):
                    fetch.parse_history_html(page)

    def test_bad_numbers_and_dates_fail(self) -> None:
        for old, new in [('>13<', '>36<'), ('>13<', '>18<'),
                         ('>2026-10-28<', '>2026-99-28<'),
                         ('>2026-10-28<', '>2025-10-28<'),
                         ('>2026-10-28<', '>2026-10-25<')]:
            with self.subTest(new=new):
                with self.assertRaises(fetch.FetchError):
                    fetch.parse_history_html(HTML.replace(old, new, 1))

    def test_duplicate_period_rejected(self) -> None:
        with self.assertRaisesRegex(fetch.FetchError, "重复期号"):
            fetch.parse_history_html(HTML.replace('>26122<', '>26123<', 1))


class SaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "numbers.csv"

    def test_offline_filter_and_provenance(self) -> None:
        result = fetch.fetch_data(self.output, target="26123", html_path=FIXTURE)
        with self.output.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([r['No.'] for r in rows], ["26121", "26122"])
        self.assertEqual(rows[0]["L1"], "06")
        self.assertEqual(rows[0]["Date"], "2026-10-24")
        self.assertEqual(result['filtered_rows'], 1)
        self.assertFalse(result['complete'])
        self.assertEqual(result['source'], 'offline_html')
        self.assertEqual(json.loads(Path(result['metadata_path']).read_text()), result)

    def test_refuse_overwrite(self) -> None:
        self.output.write_text("original")
        with self.assertRaisesRegex(fetch.FetchError, "不覆盖"):
            fetch.fetch_data(self.output, html_path=FIXTURE)
        self.assertEqual(self.output.read_text(), "original")
        self.assertFalse(self.output.with_suffix('.csv.metadata.json').exists())

    def test_explicit_overwrite(self) -> None:
        self.output.write_text("original")
        result = fetch.fetch_data(self.output, html_path=FIXTURE, overwrite=True)
        self.assertEqual(result['rows'], 3)

    def test_failed_validation_writes_nothing(self) -> None:
        bad = Path(self.temp.name) / "bad.html"
        bad.write_text('<html>HTTP200验证码</html>')
        with self.assertRaises(fetch.FetchError):
            fetch.fetch_data(self.output, html_path=bad)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix('.csv.metadata.json').exists())

    def test_gap_rejected(self) -> None:
        bad = Path(self.temp.name) / "gap.html"
        page = re.sub(r'<tr class="t_tr1">(?:(?!</tr>).)*>26122<.*?</tr>', '', HTML, count=1, flags=re.S)
        bad.write_text(page)
        with self.assertRaisesRegex(fetch.FetchError, "缺口"):
            fetch.fetch_data(self.output, html_path=bad)
        self.assertFalse(self.output.exists())

    def test_existing_local_file_is_not_downloaded_or_repaired(self) -> None:
        self.output.write_bytes(b"bad local file")
        with patch.object(fetch, "read_url", side_effect=AssertionError("must not fetch")):
            result = fetch.ensure_data(self.output, target="26124")
        self.assertEqual(result['source'], 'local')
        self.assertFalse(result['downloaded'])
        self.assertEqual(self.output.read_bytes(), b"bad local file")

    def test_missing_local_file_calls_fetch(self) -> None:
        with patch.object(fetch, "fetch_data", return_value={"source": "500.com"}) as download:
            result = fetch.ensure_data(self.output, target="26124")
        download.assert_called_once_with(self.output.resolve(), target="26124")
        self.assertTrue(result['downloaded'])

    def test_existing_valid_provenance_is_retained(self) -> None:
        self.output.write_bytes(b"local fixture data")
        metadata = {"sha256": hashlib.sha256(self.output.read_bytes()).hexdigest(),
                    "source": "500.com", "complete": False}
        sidecar = self.output.with_suffix('.csv.metadata.json')
        sidecar.write_text(json.dumps(metadata))
        before = sidecar.read_bytes()
        with patch.object(fetch, 'read_url', side_effect=AssertionError('must not fetch')):
            result = fetch.ensure_data(self.output)
        self.assertEqual(result['provenance'], metadata)
        self.assertTrue(result['provenance_hash_matches'])
        self.assertEqual(result['source'], 'local')
        self.assertEqual(sidecar.read_bytes(), before)

    def test_existing_invalid_provenance_warns_without_repair(self) -> None:
        self.output.write_bytes(b"local fixture data")
        sidecar = self.output.with_suffix('.csv.metadata.json')
        for contents in ('not JSON', '[]', '{"sha256":"wrong","source":"untrusted"}'):
            with self.subTest(contents=contents):
                sidecar.write_text(contents)
                with patch.object(fetch, 'read_url', side_effect=AssertionError('must not fetch')):
                    result = fetch.ensure_data(self.output)
                self.assertNotIn('provenance', result)
                self.assertTrue(result['warnings'])
                self.assertEqual(sidecar.read_text(), contents)

    def test_network_range_uses_observed_latest_and_target(self) -> None:
        raw = HTML.encode('utf-8')
        with patch.object(fetch, "read_url", side_effect=[(raw, fetch.HISTORY_URL), (raw, fetch.DATA_URL)]) as request:
            result = fetch.fetch_data(self.output, target="26124", start="26121")
        self.assertEqual(request.call_args_list[1].args[0], fetch.DATA_URL+'?start=26121&end=26123')
        self.assertEqual(result['latest_observed_on_site'], '26123')
        self.assertEqual(result['effective_requested_end'], '26123')
        self.assertEqual(result['rows'], 3)

    def test_latest_tail_truncation_is_not_saved(self) -> None:
        raw = HTML.encode('utf-8')
        missing_last = re.sub(r'<tr class="t_tr1">(?:(?!</tr>).)*>26123<.*?</tr>', '', HTML, count=1, flags=re.S).encode('utf-8')
        with patch.object(fetch, "read_url", side_effect=[(raw, fetch.HISTORY_URL), (missing_last, fetch.DATA_URL)]):
            with self.assertRaisesRegex(fetch.FetchError, "主页可见末期"):
                fetch.fetch_data(self.output, start="26121")
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix('.csv.metadata.json').exists())

    def test_requested_past_end_gap_is_marked_not_claimed_complete(self) -> None:
        raw = HTML.encode('utf-8')
        first_only = re.sub(r'<tr class="t_tr1">(?:(?!</tr>).)*>2612[23]<.*?</tr>', '', HTML, flags=re.S).encode('utf-8')
        with patch.object(fetch, "read_url", side_effect=[(raw, fetch.HISTORY_URL), (first_only, fetch.DATA_URL)]):
            result = fetch.fetch_data(self.output, start="26121", target="26123")
        self.assertEqual(result['effective_requested_end'], '26122')
        self.assertEqual(result['last_id'], '26121')
        self.assertTrue(any('早于请求上限' in warning for warning in result['warnings']))
        self.assertFalse(result['complete'])

    def test_truncated_full_range_is_not_saved(self) -> None:
        raw = HTML.encode('utf-8')
        with patch.object(fetch, "read_url", side_effect=[(raw, fetch.HISTORY_URL), (raw, fetch.DATA_URL)]):
            with self.assertRaisesRegex(fetch.FetchError, "截断"):
                fetch.fetch_data(self.output, target="26124")
        self.assertFalse(self.output.exists())

    def test_invalid_target_and_empty_cutoff(self) -> None:
        for target in ('2612', 'abcde', '07001'):
            with self.assertRaises(fetch.FetchError):
                fetch.fetch_data(self.output, target=target, html_path=FIXTURE)


class NetworkTests(unittest.TestCase):
    def test_not_retrying_auth_or_access_denial(self) -> None:
        error = HTTPError(fetch.HISTORY_URL, 403, 'forbidden', Message(), io.BytesIO())
        with patch.object(fetch, 'urlopen', side_effect=error) as request:
            with self.assertRaisesRegex(fetch.FetchError, 'HTTP 403'):
                fetch.read_url(fetch.HISTORY_URL)
        self.assertEqual(request.call_count, 1)

    def test_bounded_service_error_retry(self) -> None:
        error = HTTPError(fetch.HISTORY_URL, 503, 'unavailable', Message(), io.BytesIO())
        with patch.object(fetch, 'urlopen', side_effect=error) as request, patch.object(fetch.time, 'sleep'):
            with self.assertRaisesRegex(fetch.FetchError, 'HTTP 503'):
                fetch.read_url(fetch.HISTORY_URL)
        self.assertEqual(request.call_count, 2)

    def test_arbitrary_network_hosts_not_allowed(self) -> None:
        for url in ('http://datachart.500.com/dlt/', 'https://example.com/', 'file:///tmp/data'):
            with self.assertRaises(fetch.FetchError):
                fetch.read_url(url)


if __name__ == '__main__':
    unittest.main(verbosity=2)

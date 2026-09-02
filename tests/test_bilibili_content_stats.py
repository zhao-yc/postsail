# tests/test_bilibili_content_stats.py
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from uploader.bilibili_uploader.content_stats import (
    BilibiliStatsSyncError,
    load_bilibili_cookies,
    parse_bilibili_item,
    parse_bilibili_list_payload,
    sync_recent_items,
)


SAMPLE = {
    "code": 0,
    "message": "OK",
    "data": {
        "arc_audits": [
            {
                "Archive": {
                    "aid": 1,
                    "bvid": "BVold",
                    "title": "旧稿",
                    "cover": "http://example.com/old.jpg",
                    "state_desc": "开放浏览",
                    "ptime": 1700000000,
                },
                "stat": {
                    "view": 9,
                    "like": 1,
                    "reply": 0,
                    "share": 0,
                    "favorite": 0,
                },
            },
            {
                "Archive": {
                    "aid": 2,
                    "bvid": "BVnew",
                    "title": "最新",
                    "cover": "http://example.com/new.jpg",
                    "state_desc": "开放浏览",
                    "ptime": 1730000000,
                },
                "stat": {
                    "view": 100,
                    "like": 10,
                    "reply": 2,
                    "share": 1,
                    "favorite": 3,
                },
            },
            {
                "Archive": {
                    "aid": 3,
                    "bvid": "BVmid",
                    "title": "中间",
                    "cover": "http://example.com/mid.jpg",
                    "state_desc": "开放浏览",
                    "ptime": 1720000000,
                },
                "stat": {
                    "view": 50,
                    "like": 5,
                    "reply": 1,
                    "share": 0,
                    "favorite": 1,
                },
            },
        ]
    },
}


class TestBilibiliContentStats(unittest.TestCase):
    def test_parse_item(self):
        item = parse_bilibili_item(SAMPLE["data"]["arc_audits"][1])
        self.assertEqual(item["item_id"], "BVnew")
        self.assertEqual(item["play_count"], 100)
        self.assertEqual(item["like_count"], 10)
        self.assertEqual(item["comment_count"], 2)
        self.assertEqual(item["share_count"], 1)
        self.assertEqual(item["collect_count"], 3)
        self.assertEqual(item["cover_url"], "https://example.com/new.jpg")
        self.assertEqual(item["status"], "开放浏览")

    def test_sort_by_ptime(self):
        items = parse_bilibili_list_payload(SAMPLE, limit=2)
        self.assertEqual([i["item_id"] for i in items], ["BVnew", "BVmid"])

    def test_load_cookies_from_biliup_format(self):
        payload = {
            "cookie_info": {
                "cookies": [
                    {"name": "SESSDATA", "value": "abc"},
                    {"name": "bili_jct", "value": "xyz"},
                ]
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bili.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            cookies = load_bilibili_cookies(path)
            self.assertEqual(cookies["SESSDATA"], "abc")

    def test_load_cookies_missing_sessdata(self):
        payload = {"cookie_info": {"cookies": [{"name": "bili_jct", "value": "xyz"}]}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bili.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(BilibiliStatsSyncError) as ctx:
                load_bilibili_cookies(path)
            self.assertEqual(ctx.exception.code, 401)

    @patch("uploader.bilibili_uploader.content_stats.fetch_archives_payload", return_value=SAMPLE)
    def test_sync_recent_items(self, _mock_fetch):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bili.json"
            path.write_text(
                json.dumps(
                    {
                        "cookie_info": {
                            "cookies": [{"name": "SESSDATA", "value": "abc"}]
                        }
                    }
                ),
                encoding="utf-8",
            )
            items = sync_recent_items(path, limit=2)
            self.assertEqual([i["item_id"] for i in items], ["BVnew", "BVmid"])


if __name__ == "__main__":
    unittest.main()

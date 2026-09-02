# tests/test_xiaohongshu_content_stats.py
import unittest

from uploader.xiaohongshu_uploader.content_stats import (
    is_xiaohongshu_list_api_url,
    merge_intercepted_payloads,
    parse_xiaohongshu_item,
    parse_xiaohongshu_list_payload,
)


SAMPLE = {
    "code": 0,
    "success": True,
    "data": {
        "notes": [
            {
                "id": "old",
                "display_title": "旧置顶",
                "visible_time": 1700000000,
                "sticky": True,
                "view_count": 9,
                "likes": 1,
                "comments_count": 0,
                "shared_count": 0,
                "collected_count": 0,
                "images_list": [{"url": "https://example.com/a.jpg"}],
            },
            {
                "id": "newest",
                "display_title": "最新",
                "visible_time": 1730000000,
                "view_count": 100,
                "likes": 10,
                "comments_count": 2,
                "shared_count": 1,
                "collected_count": 3,
                "images_list": [{"url": "https://example.com/b.jpg"}],
            },
            {
                "id": "mid",
                "display_title": "中间",
                "visible_time": 1720000000,
                "view_count": 50,
                "likes": 5,
                "comments_count": 1,
                "shared_count": 0,
                "collected_count": 1,
                "images_list": [{"url": "https://example.com/c.jpg"}],
            },
        ]
    },
}


class TestXiaohongshuContentStats(unittest.TestCase):
    def test_url_hints(self):
        self.assertTrue(
            is_xiaohongshu_list_api_url(
                "https://creator.xiaohongshu.com/api/galaxy/v2/creator/note/user/posted?tab=0"
            )
        )
        self.assertFalse(
            is_xiaohongshu_list_api_url("https://creator.xiaohongshu.com/new/note-manager")
        )

    def test_parse_item(self):
        item = parse_xiaohongshu_item(SAMPLE["data"]["notes"][1])
        self.assertEqual(item["item_id"], "newest")
        self.assertEqual(item["play_count"], 100)
        self.assertEqual(item["like_count"], 10)
        self.assertEqual(item["collect_count"], 3)
        self.assertEqual(item["cover_url"], "https://example.com/b.jpg")

    def test_sort_by_visible_time(self):
        items = parse_xiaohongshu_list_payload(SAMPLE, limit=2)
        self.assertEqual([i["item_id"] for i in items], ["newest", "mid"])

    def test_merge_prefers_longest(self):
        short = {"success": True, "data": {"notes": SAMPLE["data"]["notes"][:1]}}
        merged = merge_intercepted_payloads([short, SAMPLE])
        self.assertEqual(len(merged["data"]["notes"]), 3)


if __name__ == "__main__":
    unittest.main()

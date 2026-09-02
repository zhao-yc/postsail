# tests/test_kuaishou_content_stats.py
import json
import sqlite3
import unittest

from uploader.ks_uploader.content_stats import (
    is_kuaishou_list_api_url,
    is_kuaishou_login_url,
    is_kuaishou_traffic_api_url,
    is_navigation_context_error,
    merge_intercepted_payloads,
    merge_traffic_into_item,
    normalize_percent,
    parse_boost_info,
    parse_content_diagnose,
    parse_kuaishou_item,
    parse_kuaishou_list_payload,
    parse_metric_trends,
    parse_traffic_metrics,
    parse_traffic_sources,
    traffic_page_url,
)


SAMPLE = {
    "result": 1,
    "data": {
        "list": [
            {
                "workId": "old_pinned",
                "title": "置顶旧",
                "publishCoverUrl": "https://example.com/a.jpg",
                "uploadTime": 1700000000000,
                "photoTop": True,
                "playCount": 9,
                "likeCount": 1,
                "commentCount": 0,
                "judgementTitle": "已发布",
            },
            {
                "workId": "newest",
                "title": "最新",
                "publishCoverUrl": "https://example.com/b.jpg",
                "uploadTime": 1730000000000,
                "playCount": 100,
                "likeCount": 10,
                "commentCount": 2,
            },
            {
                "workId": "mid",
                "title": "中间",
                "publishCoverUrl": "https://example.com/c.jpg",
                "uploadTime": 1720000000000,
                "playCount": 50,
                "likeCount": 5,
                "commentCount": 1,
            },
            {
                "workId": "fourth",
                "title": "第四应截断",
                "uploadTime": 1710000000000,
                "playCount": 1,
            },
        ],
        "total": 4,
    },
}


class TestKuaishouContentStats(unittest.TestCase):
    def test_url_hints(self):
        self.assertTrue(
            is_kuaishou_list_api_url(
                "https://cp.kuaishou.com/rest/cp/works/v2/video/pc/photo/list?__NS_sig3=abc"
            )
        )
        self.assertFalse(is_kuaishou_list_api_url("https://cp.kuaishou.com/article/manage/video"))

    def test_status_extracts_traffic_boost_text(self):
        raw = {
            "workId": "x1",
            "title": "t",
            "uploadTime": 1730000000000,
            "publishStatus": 1,
            "photoStatusTags": [
                {
                    "text": "流量助推",
                    "textColor": "#FF3666",
                    "backgroundColor": "#FFEEF2",
                    "type": 12,
                }
            ],
            "playCount": 1,
        }
        item = parse_kuaishou_item(raw)
        self.assertEqual(item["status"], "已发布 · 流量助推")

    def test_sort_by_upload_time_and_limit(self):
        items = parse_kuaishou_list_payload(SAMPLE, limit=3)
        self.assertEqual([i["item_id"] for i in items], ["newest", "mid", "fourth"])

    def test_merge_prefers_longest(self):
        short = {"result": 1, "data": {"list": SAMPLE["data"]["list"][:1]}}
        merged = merge_intercepted_payloads([short, SAMPLE])
        self.assertEqual(len(merged["data"]["list"]), 4)


class TestKuaishouTrafficParsers(unittest.TestCase):
    def test_normalize_percent_accepts_ratio_and_percent(self):
        self.assertAlmostEqual(normalize_percent(0.2813), 28.13, places=2)
        self.assertAlmostEqual(normalize_percent(28.13), 28.13, places=2)
        self.assertAlmostEqual(normalize_percent("54.55%"), 54.55, places=2)
        self.assertIsNone(normalize_percent(None))
        self.assertIsNone(normalize_percent(""))

    def test_parse_traffic_metrics_from_kuaishou_like_payload(self):
        # Field names are flexible; parser must dig common camelCase / snake_case keys.
        payload = {
            "result": 1,
            "data": {
                "playFinishRate": 0.2813,
                "avgPlayDuration": 8,
                "twoSecondBounceRate": 0.1667,
                "fiveSecondFinishRate": 0.5455,
                "avgPlayProgress": 0.7516,
            },
        }
        m = parse_traffic_metrics(payload)
        self.assertAlmostEqual(m["completion_rate"], 28.13, places=2)
        self.assertEqual(m["avg_play_duration_sec"], 8)
        self.assertAlmostEqual(m["bounce_rate_2s"], 16.67, places=2)
        self.assertAlmostEqual(m["completion_rate_5s"], 54.55, places=2)
        self.assertAlmostEqual(m["avg_play_percent"], 75.16, places=2)

    def test_parse_traffic_sources(self):
        payload = {
            "data": {
                "trafficSources": [
                    {"name": "发现页", "ratio": 0.984},
                    {"name": "关注页", "percent": 1.6},
                ]
            }
        }
        sources = parse_traffic_sources(payload)
        self.assertEqual(sources[0]["name"], "发现页")
        self.assertAlmostEqual(sources[0]["ratio"], 98.4, places=1)
        self.assertEqual(sources[1]["name"], "关注页")
        self.assertAlmostEqual(sources[1]["ratio"], 1.6, places=1)

    def test_merge_traffic_into_item_preserves_list_fields(self):
        item = parse_kuaishou_item(SAMPLE["data"]["list"][1])  # newest
        merged = merge_traffic_into_item(
            item,
            {
                "completion_rate": 28.13,
                "avg_play_duration_sec": 8,
                "bounce_rate_2s": 16.67,
                "completion_rate_5s": 54.55,
                "avg_play_percent": 75.16,
                "traffic_sources": [{"name": "发现页", "ratio": 98.4}],
            },
        )
        self.assertEqual(merged["item_id"], "newest")
        self.assertEqual(merged["like_count"], 10)
        self.assertEqual(merged["completion_rate"], 28.13)
        self.assertEqual(merged["traffic_sources"][0]["name"], "发现页")

    def test_parse_kuaishou_item_defaults_traffic_keys_to_none(self):
        item = parse_kuaishou_item(SAMPLE["data"]["list"][1])
        self.assertIsNone(item["completion_rate"])
        self.assertIsNone(item["avg_play_duration_sec"])
        self.assertIsNone(item["bounce_rate_2s"])
        self.assertIsNone(item["completion_rate_5s"])
        self.assertIsNone(item["avg_play_percent"])
        self.assertIsNone(item["traffic_sources"])

    def test_parse_traffic_metrics_from_single_overview_trend_list(self):
        payload = {
            "result": 1,
            "data": {
                "trendList": [
                    {"enName": "PLAY_CNT", "name": "播放量", "sumCount": 2570.0},
                    {"enName": "AVG_PLAY_DURATION", "name": "平均播放时长", "sumCount": 5834.299},
                    {"enName": "TWO_SECONDS_EXIT", "name": "2秒跳出率", "sumCount": 22.1},
                    {"enName": "FIVE_SECONDS_FPR", "name": "5秒完播率", "sumCount": 38.1},
                    {"enName": "FPR", "name": "完播率", "sumCount": 13.9},
                ]
            },
        }
        m = parse_traffic_metrics(payload)
        self.assertAlmostEqual(m["completion_rate"], 13.9, places=2)
        self.assertAlmostEqual(m["avg_play_duration_sec"], 5.83, places=2)
        self.assertAlmostEqual(m["bounce_rate_2s"], 22.1, places=2)
        self.assertAlmostEqual(m["completion_rate_5s"], 38.1, places=2)
        self.assertIsNone(m["avg_play_percent"])

    def test_parse_traffic_sources_from_play_tab(self):
        payload = {
            "data": {
                "trafficDataList": [
                    {
                        "name": "播放量",
                        "tab": "PLAY",
                        "sumCount": 2515,
                        "trendData": [
                            {"name": "精选页", "count": 1634},
                            {"name": "发现页", "count": 852},
                            {"name": "其他", "count": 29},
                        ],
                    }
                ]
            }
        }
        sources = parse_traffic_sources(payload)
        self.assertEqual(sources[0]["name"], "精选页")
        self.assertAlmostEqual(sources[0]["ratio"], 65.0, places=1)
        self.assertEqual(sources[1]["name"], "发现页")
        self.assertAlmostEqual(sources[1]["ratio"], 33.9, places=1)

    def test_parse_boost_info_from_official_boost_v3(self):
        payload = {
            "result": 1,
            "data": {
                "officialBoostV3": {
                    "splitViewMap": {
                        "20": {
                            "promotion": 184,
                            "reason": "作品在「画质清晰度/标题质量/内容质量」上超过90%作者",
                            "order": 1,
                        }
                    }
                }
            },
        }
        boost = parse_boost_info(payload)
        self.assertEqual(boost["boost_play_count"], 184)
        self.assertIn("画质清晰度", boost["boost_reason"])

    def test_parse_boost_info_from_promotion_desc(self):
        boost = parse_boost_info({"promotionDesc": "184助推播放量"})
        self.assertEqual(boost["boost_play_count"], 184)
        self.assertIsNone(boost["boost_reason"])

    def test_merge_traffic_includes_boost_fields(self):
        item = parse_kuaishou_item(SAMPLE["data"]["list"][1])
        merged = merge_traffic_into_item(
            item,
            {
                "boost_play_count": 184,
                "boost_reason": "作品在「画质清晰度」上超过90%作者",
            },
        )
        self.assertEqual(merged["boost_play_count"], 184)
        self.assertIn("画质清晰度", merged["boost_reason"])

    def test_parse_content_diagnose_from_diagnose_list(self):
        payload = {
            "data": {
                "detail": {
                    "content": {
                        "diagnoseList": [
                            {
                                "contentDimension": "SCREEN",
                                "title": "画面清晰度评估",
                                "score": 89.0,
                                "diagnoseDesc": "作品的画质较为优秀",
                            },
                            {
                                "contentDimension": "TITLE",
                                "title": "标题质量评估",
                                "score": 35,
                                "diagnoseDesc": "标题描述不够明确",
                            },
                            {
                                "contentDimension": "SKIP",
                                "title": "",
                                "score": 10,
                            },
                        ]
                    }
                }
            }
        }
        items = parse_content_diagnose(payload)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["dimension"], "SCREEN")
        self.assertEqual(items[0]["title"], "画面清晰度评估")
        self.assertAlmostEqual(items[0]["score"], 89.0, places=1)
        self.assertEqual(items[1]["title"], "标题质量评估")
        self.assertAlmostEqual(items[1]["score"], 35.0, places=1)

    def test_merge_traffic_includes_content_diagnose(self):
        item = parse_kuaishou_item(SAMPLE["data"]["list"][1])
        merged = merge_traffic_into_item(
            item,
            {
                "content_diagnose": [
                    {"dimension": "SCREEN", "title": "画面清晰度评估", "score": 89.0, "desc": "好"}
                ]
            },
        )
        self.assertEqual(merged["content_diagnose"][0]["score"], 89.0)

    def test_parse_metric_trends_strips_leading_zeros_and_converts_duration(self):
        payload = {
            "data": {
                "trendList": [
                    {
                        "enName": "PLAY_CNT",
                        "name": "播放量",
                        "trendData": [
                            {"date": 1720000000000, "count": 0},
                            {"date": 1720003600000, "count": 100},
                            {"date": 1720007200000, "count": 200},
                        ],
                    },
                    {
                        "enName": "AVG_PLAY_DURATION",
                        "name": "平均播放时长",
                        "trendData": [{"date": 1720003600000, "count": 5834.299}],
                    },
                    {
                        "enName": "OUTSIDE_CTR",
                        "name": "封面点击率",
                        "trendData": [{"date": 1720003600000, "count": 0}],
                    },
                ]
            }
        }
        series = parse_metric_trends(payload)
        keys = [s["key"] for s in series]
        self.assertEqual(keys, ["PLAY_CNT", "AVG_PLAY_DURATION"])
        play = series[0]
        self.assertEqual(play["name"], "播放量")
        self.assertEqual(len(play["points"]), 2)
        self.assertEqual(play["points"][0]["value"], 100)
        self.assertEqual(play["points"][1]["value"], 200)
        self.assertIn(" ", play["points"][0]["date"])
        dur = series[1]
        self.assertAlmostEqual(dur["points"][0]["value"], 5.83, places=2)

    def test_merge_traffic_includes_metric_trends(self):
        item = parse_kuaishou_item(SAMPLE["data"]["list"][1])
        merged = merge_traffic_into_item(
            item,
            {"metric_trends": [{"key": "PLAY_CNT", "name": "播放量", "points": [{"date": "2026-08-16 20:00", "value": 100}]}]},
        )
        self.assertEqual(merged["metric_trends"][0]["key"], "PLAY_CNT")


class TestKuaishouReplaceViaSharedSchema(unittest.TestCase):
    def test_replace_writes_legacy_traffic_and_boost(self):
        from uploader.douyin_uploader.content_stats import (
            ensure_content_stats_table,
            replace_account_stats,
            row_to_stat_item,
        )

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            ensure_content_stats_table(conn)
            replace_account_stats(
                conn,
                platform="kuaishou",
                account_id=7,
                items=[
                    {
                        "item_id": "ks1",
                        "title": "t",
                        "completion_rate": 33.3,
                        "avg_play_duration_sec": 12.5,
                        "bounce_rate_2s": 10.0,
                        "completion_rate_5s": 40.0,
                        "avg_play_percent": None,
                        "traffic_sources": [{"name": "发现页", "ratio": 55.5}],
                        "boost_play_count": 184,
                        "boost_reason": "作品在「画质清晰度」上超过90%作者",
                    }
                ],
                synced_at="2026-08-17T12:00:00",
            )
            row = conn.execute("SELECT * FROM content_stats WHERE item_id='ks1'").fetchone()
            self.assertAlmostEqual(row["completion_rate"], 33.3, places=2)
            self.assertEqual(row["boost_play_count"], 184)
            self.assertIsNone(row["extra_json"])
            item = row_to_stat_item(row)
            self.assertEqual(item["boostPlayCount"], 184)
            self.assertEqual(item["trafficSources"][0]["name"], "发现页")
        finally:
            conn.close()

    def test_replace_writes_content_diagnose_into_extra_json(self):
        from uploader.douyin_uploader.content_stats import (
            ensure_content_stats_table,
            replace_account_stats,
            row_to_stat_item,
        )

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            ensure_content_stats_table(conn)
            replace_account_stats(
                conn,
                platform="kuaishou",
                account_id=7,
                items=[
                    {
                        "item_id": "ks2",
                        "title": "t",
                        "completion_rate": 13.7,
                        "content_diagnose": [
                            {
                                "dimension": "SCREEN",
                                "title": "画面清晰度评估",
                                "score": 89.0,
                                "desc": "作品的画质较为优秀",
                            }
                        ],
                    }
                ],
                synced_at="2026-08-18T12:00:00",
            )
            row = conn.execute("SELECT * FROM content_stats WHERE item_id='ks2'").fetchone()
            extra = json.loads(row["extra_json"])
            self.assertEqual(extra["content_diagnose"][0]["title"], "画面清晰度评估")
            self.assertAlmostEqual(row["completion_rate"], 13.7, places=2)
            item = row_to_stat_item(row)
            self.assertEqual(item["contentDiagnose"][0]["score"], 89.0)
        finally:
            conn.close()

    def test_replace_writes_metric_trends_into_extra_json(self):
        from uploader.douyin_uploader.content_stats import (
            ensure_content_stats_table,
            replace_account_stats,
            row_to_stat_item,
        )

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            ensure_content_stats_table(conn)
            replace_account_stats(
                conn,
                platform="kuaishou",
                account_id=7,
                items=[
                    {
                        "item_id": "ks3",
                        "title": "t",
                        "content_diagnose": [
                            {"dimension": "SCREEN", "title": "画面清晰度评估", "score": 89.0, "desc": None}
                        ],
                        "metric_trends": [
                            {
                                "key": "PLAY_CNT",
                                "name": "播放量",
                                "points": [{"date": "2026-08-16 20:00", "value": 100}],
                            }
                        ],
                    }
                ],
                synced_at="2026-08-18T12:00:00",
            )
            row = conn.execute("SELECT * FROM content_stats WHERE item_id='ks3'").fetchone()
            extra = json.loads(row["extra_json"])
            self.assertEqual(extra["metric_trends"][0]["name"], "播放量")
            self.assertEqual(extra["content_diagnose"][0]["score"], 89.0)
            item = row_to_stat_item(row)
            self.assertEqual(item["metricTrends"][0]["points"][0]["value"], 100)
        finally:
            conn.close()


class TestKuaishouTrafficUrlHelpers(unittest.TestCase):
    def test_traffic_page_url_formats_item_id(self):
        url = traffic_page_url("photo123")
        self.assertIn("photo123", url)
        self.assertTrue(url.startswith("https://cp.kuaishou.com/"))
        self.assertIn("/statistics/article/detail/", url)

    def test_is_kuaishou_traffic_api_url_excludes_list(self):
        self.assertFalse(
            is_kuaishou_traffic_api_url(
                "https://cp.kuaishou.com/rest/cp/works/v2/video/pc/photo/list"
            )
        )
        self.assertTrue(
            is_kuaishou_traffic_api_url(
                "https://cp.kuaishou.com/rest/cp/creator/analysis/pc/photo/single/overview"
            )
        )
        self.assertTrue(
            is_kuaishou_traffic_api_url(
                "https://cp.kuaishou.com/rest/cp/creator/analysis/pc/photo/single/traffic/source"
            )
        )
        self.assertTrue(
            is_kuaishou_traffic_api_url(
                "https://cp.kuaishou.com/rest/cp/creator/analysis/pc/photo/single/diagnose"
            )
        )


class TestKuaishouNavigationSafeHelpers(unittest.TestCase):
    def test_is_navigation_context_error_matches_playwright_message(self):
        exc = Exception(
            "Locator.count: Execution context was destroyed, most likely because of a navigation."
        )
        self.assertTrue(is_navigation_context_error(exc))
        self.assertFalse(is_navigation_context_error(Exception("timeout 30000ms exceeded")))

    def test_is_kuaishou_login_url(self):
        self.assertTrue(
            is_kuaishou_login_url(
                "https://passport.kuaishou.com/pc/account/login/?sid=kuaishou.web.cp.api"
            )
        )
        self.assertTrue(
            is_kuaishou_login_url("https://id.kuaishou.com/pass/kuaishou/login/passToken")
        )
        self.assertFalse(
            is_kuaishou_login_url("https://cp.kuaishou.com/article/manage/video?status=1")
        )
        self.assertFalse(
            is_kuaishou_login_url(
                "https://cp.kuaishou.com/rest/infra/sts?followUrl=https%3A%2F%2Fcp.kuaishou.com"
            )
        )


if __name__ == "__main__":
    unittest.main()

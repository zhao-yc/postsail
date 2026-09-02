# tests/test_douyin_content_stats.py
import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from uploader.douyin_uploader.content_stats import (
    DOUYIN_EXTRA_KEYS,
    _extract_list,
    build_douyin_extra,
    dumps_extra_json,
    ensure_content_stats_table,
    is_douyin_list_api_url,
    is_douyin_traffic_api_url,
    loads_extra_json,
    merge_intercepted_payloads,
    merge_traffic_fields_from_row,
    merge_traffic_into_item,
    normalize_count,
    normalize_percent,
    parse_audience_payload,
    parse_distribution_list,
    parse_douyin_item,
    parse_douyin_list_payload,
    parse_traffic_metrics,
    parse_traffic_sources,
    replace_account_stats,
    traffic_page_url,
    truncate_distribution_top_n,
    row_to_stat_item,
    merge_audience_into_item,
)


SAMPLE_PAYLOAD = {
    "status_code": 0,
    "aweme_list": [
        {
            "aweme_id": "111",
            "desc": "第一条标题",
            "create_time": 1720000000,
            "status": {"is_private": False},
            "video": {"cover": {"url_list": ["https://example.com/a.jpg"]}},
            "statistics": {
                "play_count": 100,
                "digg_count": 10,
                "comment_count": 2,
                "share_count": 1,
                "collect_count": 3,
            },
        },
        {
            "aweme_id": "222",
            "desc": "第二条",
            "create_time": 1710000000,
            "video": {"cover": {"url_list": ["https://example.com/b.jpg"]}},
            "statistics": {
                "play_count": 50,
                "digg_count": 5,
                "comment_count": 1,
                "share_count": 0,
                "collect_count": 0,
            },
        },
        {
            "aweme_id": "333",
            "desc": "第三条",
            "create_time": 1700000000,
            "statistics": {"play_count": 1, "digg_count": 0, "comment_count": 0},
        },
        {
            "aweme_id": "444",
            "desc": "第四条应被截断",
            "create_time": 1690000000,
            "statistics": {"play_count": 9},
        },
    ],
}


class TestParseDouyinContentStats(unittest.TestCase):
    def test_normalize_count(self):
        self.assertEqual(normalize_count(None), 0)
        self.assertEqual(normalize_count(""), 0)
        self.assertEqual(normalize_count("12"), 12)
        self.assertEqual(normalize_count(3.0), 3)

    def test_parse_item_maps_fields(self):
        item = parse_douyin_item(SAMPLE_PAYLOAD["aweme_list"][0])
        self.assertEqual(item["item_id"], "111")
        self.assertEqual(item["title"], "第一条标题")
        self.assertEqual(item["cover_url"], "https://example.com/a.jpg")
        self.assertEqual(item["play_count"], 100)
        self.assertEqual(item["like_count"], 10)
        self.assertEqual(item["comment_count"], 2)
        self.assertEqual(item["share_count"], 1)
        self.assertEqual(item["collect_count"], 3)
        self.assertTrue(item["published_at"])

    def test_parse_list_respects_limit(self):
        items = parse_douyin_list_payload(SAMPLE_PAYLOAD, limit=3)
        self.assertEqual([i["item_id"] for i in items], ["111", "222", "333"])

    def test_parse_list_prefers_recent_over_api_order(self):
        # API often returns pinned/older items first; we sort by create_time.
        payload = {
            "data": {
                "work_list": [
                    {
                        "aweme_id": "old_pinned",
                        "desc": "置顶旧视频",
                        "create_time": 1700000000,
                        "is_pinned": True,
                        "statistics": {"play_count": 9},
                    },
                    {
                        "aweme_id": "newest",
                        "desc": "最新",
                        "create_time": 1730000000,
                        "statistics": {"play_count": 1},
                    },
                    {
                        "aweme_id": "mid",
                        "desc": "中间",
                        "create_time": 1720000000,
                        "statistics": {"play_count": 2},
                    },
                ]
            }
        }
        items = parse_douyin_list_payload(payload, limit=2)
        self.assertEqual([i["item_id"] for i in items], ["newest", "mid"])

    def test_parse_list_nested_data_key(self):
        nested = {"data": {"aweme_list": SAMPLE_PAYLOAD["aweme_list"][:1]}}
        items = parse_douyin_list_payload(nested, limit=3)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["item_id"], "111")

    def test_skip_items_without_id(self):
        payload = {"aweme_list": [{"desc": "no id", "statistics": {}}]}
        self.assertEqual(parse_douyin_list_payload(payload, limit=3), [])

    def test_replace_account_stats_keeps_only_new_rows(self):
        with TemporaryDirectory() as td:
            db = Path(td) / "t.db"
            conn = sqlite3.connect(db)
            ensure_content_stats_table(conn)
            replace_account_stats(
                conn,
                platform="douyin",
                account_id=1,
                items=parse_douyin_list_payload(SAMPLE_PAYLOAD, limit=3),
                synced_at="2026-08-06T12:00:00",
            )
            replace_account_stats(
                conn,
                platform="douyin",
                account_id=1,
                items=parse_douyin_list_payload(
                    {"aweme_list": SAMPLE_PAYLOAD["aweme_list"][:1]}, limit=3
                ),
                synced_at="2026-08-06T13:00:00",
            )
            rows = conn.execute(
                "SELECT item_id FROM content_stats WHERE account_id=1 ORDER BY id"
            ).fetchall()
            self.assertEqual(rows, [("111",)])
            conn.close()


class TestInterceptHelpers(unittest.TestCase):
    def test_url_hints(self):
        self.assertTrue(
            is_douyin_list_api_url(
                "https://creator.douyin.com/janus/douyin/creator/pc/work_list?page_num=1"
            )
        )
        self.assertTrue(
            is_douyin_list_api_url(
                "https://creator.douyin.com/aweme/v1/creator/item/list?cursor=0"
            )
        )
        self.assertFalse(
            is_douyin_list_api_url(
                "https://creator.douyin.com/creator-micro/content/manage"
            )
        )

    def test_parse_work_list_nested_data(self):
        payload = {
            "data": {
                "work_list": SAMPLE_PAYLOAD["aweme_list"][:2],
            }
        }
        items = parse_douyin_list_payload(payload, limit=3)
        self.assertEqual([i["item_id"] for i in items], ["111", "222"])

    def test_merge_prefers_longest_list(self):
        short = {"aweme_list": SAMPLE_PAYLOAD["aweme_list"][:1]}
        long = SAMPLE_PAYLOAD
        merged = merge_intercepted_payloads([short, long])
        self.assertEqual(len(merged["aweme_list"]), 4)

    def test_merge_empty_extract_detects_schema_drift(self):
        payloads = [
            {"status_code": 0, "data": {"cursor": 0, "has_more": False}},
            {"status_code": 0, "extra": {"logid": "abc"}},
        ]
        merged = merge_intercepted_payloads(payloads)
        self.assertEqual(_extract_list(merged), [])


class TestTrafficParsers(unittest.TestCase):
    def test_normalize_percent_accepts_ratio_and_percent(self):
        self.assertAlmostEqual(normalize_percent(0.2813), 28.13, places=2)
        self.assertAlmostEqual(normalize_percent(28.13), 28.13, places=2)
        self.assertAlmostEqual(normalize_percent("54.55%"), 54.55, places=2)
        self.assertIsNone(normalize_percent(None))
        self.assertIsNone(normalize_percent(""))

    def test_parse_traffic_metrics_from_attractiveness_payload(self):
        payload = {
            "data": {
                "finish_rate": 0.2813,
                "avg_play_duration": 8,
                "bounce_rate_2s": 0.1667,
                "finish_rate_5s": 0.5455,
                "avg_play_progress": 0.7516,
            }
        }
        m = parse_traffic_metrics(payload)
        self.assertAlmostEqual(m["completion_rate"], 28.13, places=2)
        self.assertEqual(m["avg_play_duration_sec"], 8)
        self.assertAlmostEqual(m["bounce_rate_2s"], 16.67, places=2)
        self.assertAlmostEqual(m["completion_rate_5s"], 54.55, places=2)
        self.assertAlmostEqual(m["avg_play_percent"], 75.16, places=2)

    def test_parse_traffic_metrics_from_item_mget(self):
        from uploader.douyin_uploader.content_stats import parse_mget_items_metrics

        payload = {
            "status_code": 0,
            "items": [
                {
                    "id": "7582190958578617634",
                    "metrics": {
                        "avg_view_proportion": "0.226337",
                        "avg_view_second": "1.629630",
                        "bounce_rate_2s": "0.740741",
                        "completion_rate": "0.281300",
                        "completion_rate_5s": "0.545500",
                    },
                }
            ],
        }
        m = parse_traffic_metrics(payload)
        self.assertAlmostEqual(m["completion_rate"], 28.13, places=2)
        self.assertAlmostEqual(m["avg_play_duration_sec"], 1.63, places=2)
        self.assertAlmostEqual(m["bounce_rate_2s"], 74.07, places=2)
        self.assertAlmostEqual(m["completion_rate_5s"], 54.55, places=2)
        self.assertAlmostEqual(m["avg_play_percent"], 22.63, places=2)
        by_id = parse_mget_items_metrics(payload)
        self.assertIn("7582190958578617634", by_id)
        self.assertAlmostEqual(by_id["7582190958578617634"]["bounce_rate_2s"], 74.07, places=2)

    def test_parse_traffic_sources(self):
        payload = {
            "data": {
                "traffic_source": [
                    {"name": "推荐页", "ratio": 0.984},
                    {"name": "朋友页", "percent": 1.6},
                ]
            }
        }
        sources = parse_traffic_sources(payload)
        self.assertEqual(sources[0]["name"], "推荐页")
        self.assertAlmostEqual(sources[0]["ratio"], 98.4, places=1)
        self.assertEqual(sources[1]["name"], "朋友页")
        self.assertAlmostEqual(sources[1]["ratio"], 1.6, places=1)

    def test_parse_traffic_sources_play_source_keys(self):
        payload = {
            "status_code": 0,
            "play_source": [
                {"key": "familiar", "value": 0.000864},
                {"key": "search", "value": 0.000864},
                {"key": "other", "value": 0.003457},
                {"key": "homepage_hot", "value": 0.99395},
                {"key": "homepage", "value": 0.000864},
            ],
        }
        sources = parse_traffic_sources(payload)
        self.assertEqual(sources[0]["name"], "推荐页")
        self.assertAlmostEqual(sources[0]["ratio"], 99.4, places=1)
        names = {s["name"] for s in sources}
        self.assertIn("朋友", names)
        self.assertIn("搜索", names)
        self.assertIn("个人主页", names)
        self.assertIn("其他", names)

    def test_merge_traffic_into_item_preserves_list_fields(self):
        item = parse_douyin_item(SAMPLE_PAYLOAD["aweme_list"][0])
        merged = merge_traffic_into_item(
            item,
            {
                "completion_rate": 28.13,
                "avg_play_duration_sec": 8,
                "bounce_rate_2s": 16.67,
                "completion_rate_5s": 54.55,
                "avg_play_percent": 75.16,
                "traffic_sources": [{"name": "推荐页", "ratio": 98.4}],
            },
        )
        self.assertEqual(merged["item_id"], "111")
        self.assertEqual(merged["like_count"], 10)
        self.assertEqual(merged["completion_rate"], 28.13)
        self.assertEqual(merged["traffic_sources"][0]["name"], "推荐页")


class TestTrafficSchema(unittest.TestCase):
    def test_ensure_adds_traffic_columns_and_replace_writes_them(self):
        with TemporaryDirectory() as td:
            db = Path(td) / "t.db"
            conn = sqlite3.connect(db)
            try:
                # Simulate old schema without traffic columns
                conn.execute(
                    """
                    CREATE TABLE content_stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        platform TEXT NOT NULL,
                        account_id INTEGER NOT NULL,
                        item_id TEXT NOT NULL,
                        title TEXT,
                        cover_url TEXT,
                        status TEXT,
                        published_at TEXT,
                        play_count INTEGER DEFAULT 0,
                        like_count INTEGER DEFAULT 0,
                        comment_count INTEGER DEFAULT 0,
                        share_count INTEGER DEFAULT 0,
                        collect_count INTEGER DEFAULT 0,
                        synced_at TEXT NOT NULL,
                        raw_json TEXT,
                        UNIQUE(platform, account_id, item_id)
                    )
                    """
                )
                conn.commit()
                ensure_content_stats_table(conn)
                cols = {r[1] for r in conn.execute("PRAGMA table_info(content_stats)").fetchall()}
                for name in (
                    "completion_rate",
                    "avg_play_duration_sec",
                    "bounce_rate_2s",
                    "completion_rate_5s",
                    "avg_play_percent",
                    "traffic_sources_json",
                    "extra_json",
                ):
                    self.assertIn(name, cols)

                item = parse_douyin_item(SAMPLE_PAYLOAD["aweme_list"][0])
                item = merge_traffic_into_item(
                    item,
                    {
                        "completion_rate": 28.13,
                        "avg_play_duration_sec": 8,
                        "bounce_rate_2s": 16.67,
                        "completion_rate_5s": 54.55,
                        "avg_play_percent": 75.16,
                        "traffic_sources": [{"name": "推荐页", "ratio": 98.4}],
                    },
                )
                replace_account_stats(
                    conn,
                    platform="douyin",
                    account_id=1,
                    items=[item],
                    synced_at="2026-08-14T12:00:00",
                )
                row = conn.execute(
                    """
                    SELECT extra_json, completion_rate, avg_play_duration_sec, traffic_sources_json
                    FROM content_stats WHERE item_id='111'
                    """
                ).fetchone()
                extra = json.loads(row[0])
                self.assertAlmostEqual(extra["completion_rate"], 28.13, places=2)
                self.assertEqual(extra["traffic_sources"][0]["name"], "推荐页")
                self.assertIsNone(row[1])
                self.assertIsNone(row[2])
                self.assertIsNone(row[3])
            finally:
                conn.close()


class TestReplaceAccountStatsExtraJson(unittest.TestCase):
    def test_replace_writes_extra_json_and_nulls_legacy_traffic(self):
        conn = sqlite3.connect(":memory:")
        try:
            ensure_content_stats_table(conn)
            item = parse_douyin_item(SAMPLE_PAYLOAD["aweme_list"][0])
            item = merge_traffic_into_item(
                item,
                {
                    "completion_rate": 28.13,
                    "avg_play_duration_sec": 8,
                    "bounce_rate_2s": 16.67,
                    "completion_rate_5s": 54.55,
                    "avg_play_percent": 75.16,
                    "traffic_sources": [{"name": "推荐页", "ratio": 98.4}],
                },
            )
            replace_account_stats(
                conn,
                platform="douyin",
                account_id=1,
                items=[item],
                synced_at="2026-08-14T12:00:00",
            )
            row = conn.execute(
                """
                SELECT extra_json, completion_rate, avg_play_duration_sec, bounce_rate_2s,
                       completion_rate_5s, avg_play_percent, traffic_sources_json
                FROM content_stats WHERE item_id='111'
                """
            ).fetchone()
            extra = json.loads(row[0])
            self.assertAlmostEqual(extra["completion_rate"], 28.13, places=2)
            self.assertEqual(extra["traffic_sources"][0]["name"], "推荐页")
            self.assertIsNone(row[1])
            self.assertIsNone(row[2])
            self.assertIsNone(row[3])
            self.assertIsNone(row[4])
            self.assertIsNone(row[5])
            self.assertIsNone(row[6])
        finally:
            conn.close()


class TestTrafficInterceptHelpers(unittest.TestCase):
    def test_traffic_page_url(self):
        url = traffic_page_url("123456")
        self.assertIn("123456", url)
        self.assertIn("work-management/work-detail", url)
        self.assertTrue(url.startswith("https://creator.douyin.com/"))

    def test_traffic_api_url_hints(self):
        self.assertTrue(
            is_douyin_traffic_api_url(
                "https://creator.douyin.com/web/api/creator/item/mget?ids=1&fields=metrics"
            )
        )
        self.assertFalse(
            is_douyin_traffic_api_url(
                "https://creator.douyin.com/janus/douyin/creator/pc/work_list?page_num=1"
            )
        )


class TestExtraJsonHelpers(unittest.TestCase):
    def test_build_and_dumps_roundtrip(self):
        extra = build_douyin_extra(
            {
                "completion_rate": 28.13,
                "avg_play_duration_sec": 8,
                "bounce_rate_2s": 16.67,
                "completion_rate_5s": 54.55,
                "avg_play_percent": 75.16,
                "traffic_sources": [{"name": "推荐页", "ratio": 98.4}],
                "audience_gender": [{"name": "男", "ratio": 60}],
                "audience_age": [{"name": "18-23", "ratio": 50}],
                "audience_region": [{"name": "广东", "ratio": 12}],
            }
        )
        raw = dumps_extra_json(extra)
        self.assertIsInstance(raw, str)
        loaded = loads_extra_json(raw)
        self.assertAlmostEqual(loaded["completion_rate"], 28.13, places=2)
        self.assertEqual(loaded["traffic_sources"][0]["name"], "推荐页")
        for key in DOUYIN_EXTRA_KEYS:
            self.assertIn(key, loaded)

    def test_loads_extra_json_bad_payload_returns_empty(self):
        self.assertEqual(loads_extra_json(None), {})
        self.assertEqual(loads_extra_json(""), {})
        self.assertEqual(loads_extra_json("{not-json"), {})
        self.assertEqual(loads_extra_json("[1,2]"), {})

    def test_merge_prefers_extra_json_over_legacy_columns(self):
        row = {
            "extra_json": json.dumps(
                {
                    "completion_rate": 11.1,
                    "avg_play_duration_sec": 9,
                    "traffic_sources": [{"name": "JSON来源", "ratio": 50}],
                },
                ensure_ascii=False,
            ),
            "completion_rate": 99.9,
            "avg_play_duration_sec": 1,
            "bounce_rate_2s": 2.0,
            "completion_rate_5s": 3.0,
            "avg_play_percent": 4.0,
            "traffic_sources_json": json.dumps([{"name": "旧来源", "ratio": 1}], ensure_ascii=False),
        }
        merged = merge_traffic_fields_from_row(row)
        self.assertAlmostEqual(merged["completion_rate"], 11.1, places=2)
        self.assertEqual(merged["avg_play_duration_sec"], 9)
        self.assertEqual(merged["bounce_rate_2s"], 2.0)  # missing in JSON -> legacy
        self.assertEqual(merged["traffic_sources"][0]["name"], "JSON来源")

    def test_merge_falls_back_to_legacy_when_extra_empty(self):
        row = {
            "extra_json": None,
            "completion_rate": 28.13,
            "avg_play_duration_sec": 8,
            "bounce_rate_2s": 16.67,
            "completion_rate_5s": 54.55,
            "avg_play_percent": 75.16,
            "traffic_sources_json": json.dumps([{"name": "推荐页", "ratio": 98.4}], ensure_ascii=False),
        }
        merged = merge_traffic_fields_from_row(row)
        self.assertAlmostEqual(merged["completion_rate"], 28.13, places=2)
        self.assertEqual(merged["traffic_sources"][0]["name"], "推荐页")


class TestRowToStatItemExtraJson(unittest.TestCase):
    def test_prefers_extra_json(self):
        from uploader.douyin_uploader.content_stats import row_to_stat_item

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                """
                CREATE TABLE content_stats (
                    item_id TEXT, title TEXT, cover_url TEXT, status TEXT, published_at TEXT,
                    play_count INT, like_count INT, comment_count INT, share_count INT, collect_count INT,
                    completion_rate REAL, avg_play_duration_sec REAL, bounce_rate_2s REAL,
                    completion_rate_5s REAL, avg_play_percent REAL, traffic_sources_json TEXT,
                    extra_json TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO content_stats VALUES (
                    '1','t','','','',1,2,3,4,5,
                    99,1,2,3,4,'[]',
                    ?
                )
                """,
                (
                    json.dumps(
                        {
                            "completion_rate": 28.13,
                            "avg_play_duration_sec": 8,
                            "bounce_rate_2s": 16.67,
                            "completion_rate_5s": 54.55,
                            "avg_play_percent": 75.16,
                            "traffic_sources": [{"name": "推荐页", "ratio": 98.4}],
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            row = conn.execute("SELECT * FROM content_stats").fetchone()
            item = row_to_stat_item(row)
            self.assertEqual(item["completionRate"], 28.13)
            self.assertEqual(item["avgPlayDurationSec"], 8)
            self.assertEqual(item["trafficSources"][0]["name"], "推荐页")
            self.assertNotEqual(item["completionRate"], 99)
        finally:
            conn.close()

    def test_bad_extra_json_falls_back_or_nulls_safely(self):
        from uploader.douyin_uploader.content_stats import row_to_stat_item

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                """
                CREATE TABLE content_stats (
                    item_id TEXT, title TEXT, cover_url TEXT, status TEXT, published_at TEXT,
                    play_count INT, like_count INT, comment_count INT, share_count INT, collect_count INT,
                    completion_rate REAL, avg_play_duration_sec REAL, bounce_rate_2s REAL,
                    completion_rate_5s REAL, avg_play_percent REAL, traffic_sources_json TEXT,
                    extra_json TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO content_stats VALUES (
                    '1','t','','','',0,0,0,0,0,
                    28.13,8,NULL,NULL,NULL,NULL,
                    '{bad'
                )
                """
            )
            row = conn.execute("SELECT * FROM content_stats").fetchone()
            item = row_to_stat_item(row)
            self.assertEqual(item["itemId"], "1")
            self.assertEqual(item["completionRate"], 28.13)
            self.assertEqual(item["avgPlayDurationSec"], 8)
        finally:
            conn.close()


class TestExtraJsonMigration(unittest.TestCase):
    def test_ensure_adds_extra_json_and_migrates_legacy(self):
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(
                """
                CREATE TABLE content_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    account_id INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    title TEXT,
                    cover_url TEXT,
                    status TEXT,
                    published_at TEXT,
                    play_count INTEGER DEFAULT 0,
                    like_count INTEGER DEFAULT 0,
                    comment_count INTEGER DEFAULT 0,
                    share_count INTEGER DEFAULT 0,
                    collect_count INTEGER DEFAULT 0,
                    completion_rate REAL,
                    avg_play_duration_sec REAL,
                    bounce_rate_2s REAL,
                    completion_rate_5s REAL,
                    avg_play_percent REAL,
                    traffic_sources_json TEXT,
                    synced_at TEXT NOT NULL,
                    raw_json TEXT,
                    UNIQUE(platform, account_id, item_id)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO content_stats (
                    platform, account_id, item_id, title, cover_url, status, published_at,
                    play_count, like_count, comment_count, share_count, collect_count,
                    completion_rate, avg_play_duration_sec, bounce_rate_2s, completion_rate_5s,
                    avg_play_percent, traffic_sources_json, synced_at, raw_json
                ) VALUES (?, ?, ?, '', '', '', '', 0, 0, 0, 0, 0, ?, ?, ?, ?, ?, ?, ?, '')
                """,
                (
                    "douyin",
                    1,
                    "legacy-1",
                    28.13,
                    8,
                    16.67,
                    54.55,
                    75.16,
                    json.dumps([{"name": "推荐页", "ratio": 98.4}], ensure_ascii=False),
                    "2026-08-14T12:00:00",
                ),
            )
            conn.commit()
            ensure_content_stats_table(conn)
            cols = {r[1] for r in conn.execute("PRAGMA table_info(content_stats)").fetchall()}
            self.assertIn("extra_json", cols)
            row = conn.execute(
                "SELECT extra_json, completion_rate FROM content_stats WHERE item_id='legacy-1'"
            ).fetchone()
            extra = json.loads(row[0])
            self.assertAlmostEqual(extra["completion_rate"], 28.13, places=2)
            self.assertEqual(extra["traffic_sources"][0]["name"], "推荐页")
            self.assertAlmostEqual(row[1], 28.13, places=2)
        finally:
            conn.close()


class TestAudienceDistributionParsers(unittest.TestCase):
    def test_parse_distribution_list_normalizes_ratios(self):
        raw = [
            {"name": "男", "ratio": 0.625},
            {"label": "女", "percent": 37.5},
        ]
        out = parse_distribution_list(raw)
        self.assertEqual(out[0]["name"], "男")
        self.assertAlmostEqual(out[0]["ratio"], 62.5, places=2)
        self.assertEqual(out[1]["name"], "女")
        self.assertAlmostEqual(out[1]["ratio"], 37.5, places=2)

    def test_truncate_distribution_top_n(self):
        items = [{"name": str(i), "ratio": float(i)} for i in range(15)]
        top = truncate_distribution_top_n(items, 10)
        self.assertEqual(len(top), 10)
        self.assertEqual(top[0]["name"], "14")
        self.assertEqual(top[-1]["name"], "5")

    def test_parse_audience_payload_maps_blocks(self):
        payload = {
            "data": {
                "gender": [{"name": "男", "ratio": 0.6}, {"name": "女", "ratio": 0.4}],
                "age": [{"name": "18-23", "ratio": 0.5}],
                "province": [{"name": "广东", "ratio": 0.12}],
                "traffic_source": [{"name": "推荐页", "ratio": 0.9}],
            }
        }
        parsed = parse_audience_payload(payload)
        self.assertAlmostEqual(parsed["audience_gender"][0]["ratio"], 60.0, places=2)
        self.assertEqual(parsed["audience_age"][0]["name"], "18-23")
        self.assertEqual(parsed["audience_region"][0]["name"], "广东")
        self.assertEqual(parsed["traffic_sources"][0]["name"], "推荐页")

    def test_parse_audience_payload_missing_blocks_are_empty_list(self):
        parsed = parse_audience_payload({"data": {}})
        self.assertEqual(parsed["audience_gender"], [])
        self.assertEqual(parsed["audience_age"], [])
        self.assertEqual(parsed["audience_region"], [])
        self.assertEqual(parsed["traffic_sources"], [])

    def test_parse_audience_payload_portrait_ratio_list(self):
        """Real fans/item/portrait shape: gender/age/province.ratio_list[{key,value}]."""
        payload = {
            "status_code": 0,
            "gender": {
                "ratio_list": [
                    {"key": "female", "value": 0.72},
                    {"key": "male", "value": 0.27},
                ]
            },
            "age": {
                "ratio_list": [
                    {"key": "18-23", "value": 0.04},
                    {"key": "24-30", "value": 0.41},
                ]
            },
            "province": {
                "ratio_list": [{"key": f"省{i}", "value": 0.01 * (i + 1)} for i in range(12)]
            },
        }
        parsed = parse_audience_payload(payload)
        self.assertEqual(parsed["audience_gender"][0]["name"], "女")
        self.assertAlmostEqual(parsed["audience_gender"][0]["ratio"], 72.0, places=2)
        self.assertEqual(parsed["audience_gender"][1]["name"], "男")
        self.assertEqual(parsed["audience_age"][0]["name"], "18-23")
        self.assertEqual(len(parsed["audience_region"]), 10)
        self.assertEqual(parsed["audience_region"][0]["name"], "省11")


class TestAudienceExtraJsonFlatten(unittest.TestCase):
    def test_build_douyin_extra_includes_audience_keys(self):
        extra = build_douyin_extra(
            {
                "audience_gender": [{"name": "男", "ratio": 60}],
                "audience_age": [{"name": "18-23", "ratio": 50}],
                "audience_region": [{"name": "广东", "ratio": 12}],
                "traffic_sources": [{"name": "推荐页", "ratio": 90}],
            }
        )
        self.assertIn("audience_gender", extra)
        self.assertIn("audience_age", extra)
        self.assertIn("audience_region", extra)
        self.assertIn("traffic_sources", extra)

    def test_row_to_stat_item_flattens_audience(self):
        row = {
            "item_id": "1",
            "title": "t",
            "cover_url": "",
            "status": "",
            "published_at": "",
            "play_count": 0,
            "like_count": 0,
            "comment_count": 0,
            "share_count": 0,
            "collect_count": 0,
            "extra_json": json.dumps(
                {
                    "audience_gender": [{"name": "男", "ratio": 60}],
                    "audience_age": [{"name": "18-23", "ratio": 50}],
                    "audience_region": [{"name": "广东", "ratio": 12}],
                    "traffic_sources": [{"name": "推荐页", "ratio": 90}],
                },
                ensure_ascii=False,
            ),
        }
        item = row_to_stat_item(row)
        self.assertEqual(item["audienceGender"][0]["name"], "男")
        self.assertEqual(item["audienceAge"][0]["name"], "18-23")
        self.assertEqual(item["audienceRegion"][0]["name"], "广东")
        self.assertEqual(item["trafficSources"][0]["name"], "推荐页")


class TestMergeAudienceIntoItem(unittest.TestCase):
    def test_merge_audience_preserves_scalars(self):
        item = {
            "item_id": "1",
            "like_count": 3,
            "completion_rate": 28.13,
            "traffic_sources": None,
        }
        merged = merge_audience_into_item(
            item,
            {
                "audience_gender": [{"name": "男", "ratio": 60}],
                "audience_age": [],
                "audience_region": [{"name": "广东", "ratio": 12}],
                "traffic_sources": [{"name": "推荐页", "ratio": 90}],
            },
        )
        self.assertEqual(merged["like_count"], 3)
        self.assertEqual(merged["completion_rate"], 28.13)
        self.assertEqual(merged["audience_gender"][0]["name"], "男")
        self.assertEqual(merged["traffic_sources"][0]["name"], "推荐页")
        self.assertEqual(merged["audience_age"], [])

    def test_merge_audience_does_not_wipe_existing_traffic_sources(self):
        item = {
            "item_id": "1",
            "traffic_sources": [{"name": "推荐页", "ratio": 99.4}],
        }
        merged = merge_audience_into_item(
            item,
            {
                "audience_gender": [{"name": "女", "ratio": 72}],
                "audience_age": [],
                "audience_region": [],
                "traffic_sources": [],
            },
        )
        self.assertEqual(merged["traffic_sources"][0]["name"], "推荐页")
        self.assertEqual(merged["audience_gender"][0]["name"], "女")


if __name__ == "__main__":
    unittest.main()

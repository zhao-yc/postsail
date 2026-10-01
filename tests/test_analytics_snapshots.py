"""现有统计缓存与新历史表联合验证，避免更新后丢作品或误计默认零。"""
import json
import sqlite3
import unittest
from unittest.mock import patch

from uploader.douyin_uploader.content_stats import ensure_content_stats_table, replace_account_stats
from utils.analytics.store import bootstrap_legacy_stats, business_now, observed_metric, record_content_snapshot, timestamp


class AnalyticsSnapshotTests(unittest.TestCase):
    def test_legacy_cache_is_imported_only_once_with_original_timestamp(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        ensure_content_stats_table(conn)
        conn.execute("""INSERT INTO content_stats(platform,account_id,item_id,play_count,synced_at)
            VALUES('douyin',1,'原作品',100,'2026-09-30T12:00:00')""")
        bootstrap_legacy_stats(conn)
        bootstrap_legacy_stats(conn)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM analytics_work_snapshots").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT observed_at,play_count FROM analytics_work_snapshots").fetchone(),
                         ("2026-09-30 12:00:00.000000", 100))
        self.assertEqual(conn.execute("SELECT source FROM analytics_sync_runs").fetchone()[0], "legacy_baseline")

    def test_existing_replace_preserves_all_observations_as_cache_narrows(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        replace_account_stats(conn, platform="douyin", account_id=1,
            items=[{"item_id": "旧作品", "play_count": 100}, {"item_id": "新作品", "play_count": 20}],
            synced_at="2026-10-01 10:00:00")
        replace_account_stats(conn, platform="douyin", account_id=1,
            items=[{"item_id": "新作品", "play_count": 30}], synced_at="2026-10-02 10:00:00")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM content_stats").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM analytics_work_snapshots").fetchone()[0], 3)
        self.assertEqual(conn.execute("SELECT COUNT(DISTINCT item_id) FROM analytics_work_snapshots").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT scope FROM analytics_sync_runs LIMIT 1").fetchone()[0], "partial")

    def test_missing_raw_fields_are_unknown_even_if_legacy_parser_padded_zero(self):
        cases = [("douyin", {"statistics": {"play_count": 0}}, "play_count"),
                 ("kuaishou", {"playCount": 0}, "play_count"),
                 ("xiaohongshu", {"view_count": 0}, "play_count"),
                 ("bilibili", {"stat": {"view": 0}}, "play_count")]
        for platform, raw, present_column in cases:
            item = {"raw_json": json.dumps(raw), "play_count": 0, "like_count": 0}
            self.assertEqual(observed_metric(item, platform, present_column), 0)
            self.assertIsNone(observed_metric(item, platform, "like_count"))

    def test_same_second_observations_are_not_deduplicated_by_timestamp(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        for count in (100, 120):
            record_content_snapshot(conn, platform="douyin", account_id=1,
                items=[{"item_id": "作品", "play_count": count}], synced_at="2026-10-01 10:00:00")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM analytics_sync_runs").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT play_count FROM analytics_work_snapshots ORDER BY run_id").fetchall(), [(100,), (120,)])

    def test_aware_timestamps_use_business_timezone_not_machine_timezone(self):
        with patch.dict("os.environ", {"OMNIPOST_ANALYTICS_TIMEZONE": "Asia/Shanghai"}):
            self.assertEqual(timestamp("2026-09-30T20:00:00Z"), "2026-10-01 04:00:00.000000")
            self.assertEqual(int(business_now().utcoffset().total_seconds() / 60), 480)
        with patch.dict("os.environ", {"OMNIPOST_ANALYTICS_TIMEZONE": "UTC"}):
            self.assertEqual(timestamp("2026-10-01T04:00:00+08:00"), "2026-09-30 20:00:00.000000")

    def test_failed_replacement_rolls_back_new_snapshots_and_keeps_old_cache(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        replace_account_stats(conn, platform="douyin", account_id=1,
            items=[{"item_id": "旧作品", "play_count": 100}], synced_at="2026-10-01 10:00:00")
        with self.assertRaises(ValueError):
            with conn:
                replace_account_stats(conn, platform="douyin", account_id=1,
                    items=[{"play_count": 999}], synced_at="2026-10-02 10:00:00")
        self.assertEqual(conn.execute("SELECT item_id FROM content_stats").fetchone()[0], "旧作品")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM analytics_sync_runs").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()

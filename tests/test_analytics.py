"""验证观测增长、样本范围、负责人筛选和安全导出的真实数据库行为。"""
from __future__ import annotations

import csv
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path

from utils.analytics.service import AnalyticsError, AnalyticsService, Filters
from utils.analytics.store import record_account_snapshot, record_content_snapshot


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "data.db"
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE user_info(id INTEGER PRIMARY KEY,type INTEGER,userName TEXT,status INTEGER,filePath TEXT)")
            conn.executemany("INSERT INTO user_info VALUES(?,?,?,?,?)", [
                (1, 3, "抖音甲", 1, "机密会话.json"), (2, 1, "小红书乙", 0, "机密乙.json"),
                (3, 2, "视频号丙", 1, "机密丙.json")])
        self.service = AnalyticsService(self.path)
        self.filters = Filters.from_params({"startDate": "2026-10-01", "endDate": "2026-10-03"})

    def tearDown(self):
        self.directory.cleanup()

    def snapshot(self, day, play=100, account=1, item_id="w1", published="2026-10-01 08:00:00", **kwargs):
        item = {"item_id": item_id, "title": "作品甲", "published_at": published,
                "status": "已发布", "play_count": play, "like_count": play // 10,
                "comment_count": 2, "collect_count": 3, "share_count": 1, **kwargs}
        with sqlite3.connect(self.path) as conn:
            record_content_snapshot(conn, platform="douyin" if account == 1 else "xiaohongshu",
                                    account_id=account, items=[item], synced_at=f"2026-10-{day:02d} 12:00:00")

    def followers(self, day, count, account=1):
        with sqlite3.connect(self.path) as conn:
            record_account_snapshot(conn, platform="douyin" if account == 1 else "xiaohongshu",
                                    account_id=account, synced_at=f"2026-10-{day:02d} 12:00:00", follower_count=count,
                                    evidence=[{"kind": "测试真实响应夹具", "value": count}])

    def test_first_observation_is_baseline_and_missing_fans_are_null(self):
        self.snapshot(1, play=1200)
        result = self.service.overview(self.filters)
        self.assertIsNone(result["summary"]["playCount"])
        self.assertIsNone(result["summary"]["followerCount"])
        self.assertIsNone(result["summary"]["newFollowers"])
        self.assertEqual(result["summary"]["publishedCount"], 1)
        self.assertEqual(result["coverage"]["baselineCount"], 1)
        self.assertEqual(result["coverage"]["scope"], "partial")
        account = self.service.accounts(self.filters)["items"][0]
        self.assertEqual(account["playCount"], 1200)
        self.assertIsNone(account["growth"]["playCount"])
        self.assertIsNone(result["trends"][0]["playCount"])

    def test_real_growth_and_negative_platform_correction(self):
        self.snapshot(1, play=100)
        self.snapshot(2, play=160)
        self.snapshot(3, play=150)
        self.followers(1, 20)
        self.followers(2, 25)
        self.followers(3, None)
        result = self.service.overview(self.filters)
        self.assertEqual(result["summary"]["playCount"], 50)
        self.assertEqual(result["summary"]["followerCount"], 25)
        self.assertEqual(result["summary"]["newFollowers"], 5)
        self.assertEqual([item["playCount"] for item in result["trends"]], [None, 60, -10])
        self.assertEqual(result["coverage"]["comparableCount"], 1)

    def test_interval_crossing_start_uses_real_baseline_and_declares_span(self):
        self.snapshot(1, play=100)
        self.snapshot(2, play=200)
        self.snapshot(3, play=220)
        filters = Filters.from_params({"startDate": "2026-10-02", "endDate": "2026-10-03"})
        result = self.service.overview(filters)
        self.assertEqual(result["summary"]["playCount"], 120)
        self.assertEqual(result["trends"][0]["playCount"], 100)
        self.assertEqual(result["coverage"]["intervalStart"], "2026-10-01 12:00:00.000000")
        self.assertTrue(result["coverage"]["crossesRangeStart"])
        self.assertIn("包含查询开始前时间", result["coverage"]["boundaryMessage"])
        self.assertTrue(result["trends"][0]["crossesRangeStart"])

    def test_daily_follower_delta_uses_previous_day_real_baseline(self):
        self.followers(1, 20)
        self.followers(2, 25)
        filters = Filters.from_params({"startDate": "2026-10-02", "endDate": "2026-10-02"})
        result = self.service.overview(filters)
        self.assertEqual(result["summary"]["newFollowers"], 5)
        self.assertTrue(result["coverage"]["crossesRangeStart"])
        self.assertEqual(result["trends"][0]["intervalStart"], "2026-10-01 12:00:00.000000")

    def test_narrowing_sample_keeps_historical_works_without_inventing_growth(self):
        self.snapshot(1, play=100)
        self.snapshot(1, play=900, item_id="w2")
        # 即使时间精度相同，独立采集仍作为两个不可变批次保存。
        self.snapshot(2, play=130)
        result = self.service.overview(self.filters)
        self.assertEqual(result["summary"]["workCount"], 2)
        self.assertEqual(result["summary"]["playCount"], 30)
        account = next(item for item in self.service.accounts(self.filters)["items"] if item["accountId"] == 1)
        self.assertEqual(account["playCount"], 1030)
        self.assertEqual(account["coverage"]["baselineCount"], 1)

    def test_owner_tags_platform_and_status_filter_and_pagination(self):
        self.snapshot(1, account=1)
        self.snapshot(1, account=2, item_id="小红书作品")
        settings = self.service.update_account_settings(1, "负责人甲", ["视频", "视频", "重点"])
        self.assertEqual(settings["tags"], ["视频", "重点"])
        filters = Filters.from_params({"startDate": "2026-10-01", "endDate": "2026-10-03",
                                       "owner": "负责人甲", "platform": "douyin", "group": "视频", "status": "1"})
        result = self.service.accounts(filters)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["accountId"], 1)
        owners = self.service.owners(filters)["items"]
        self.assertEqual(owners[0]["owner"], "负责人甲")
        self.assertEqual(owners[0]["accountCount"], 1)
        page = self.service.accounts(Filters.from_params({"page": 2, "pageSize": 1}))
        self.assertEqual(page["total"], 3)
        self.assertEqual(len(page["items"]), 1)
        self.assertNotIn("filePath", result["items"][0])

    def test_rankings_use_account_growth_and_missing_values_rank_last(self):
        self.snapshot(1, play=100)
        self.snapshot(2, play=150)
        self.snapshot(1, play=9000, account=2)
        payload = self.service.rankings(self.filters, entity="accounts", metric="playCount")
        self.assertEqual(payload["items"][0]["accountId"], 1)
        self.assertEqual(payload["items"][0]["metricValue"], 50)
        self.assertEqual(payload["items"][0]["rank"], 1)
        self.assertIsNone(payload["items"][1]["rank"])
        fans = self.service.rankings(self.filters, metric="newFollowers")
        self.assertTrue(all(item["metricValue"] is None for item in fans["items"]))

    def test_nested_growth_sort_uses_increment_and_keeps_missing_last(self):
        self.snapshot(1, play=100)
        self.snapshot(2, play=150)
        self.snapshot(1, play=9000, account=2)
        self.snapshot(2, play=9020, account=2)
        filters = Filters.from_params({"startDate": "2026-10-01", "endDate": "2026-10-03", "sortBy": "growth.playCount"})
        rows = self.service.accounts(filters)["items"]
        self.assertEqual([row["accountId"] for row in rows], [1, 2, 3])
        ascending = Filters.from_params({"startDate": "2026-10-01", "endDate": "2026-10-03",
                                         "sortBy": "growth.playCount", "sortOrder": "asc"})
        self.assertEqual([row["accountId"] for row in self.service.accounts(ascending)["items"]], [2, 1, 3])

    def test_works_filter_publish_dates_but_old_works_still_contribute_growth(self):
        self.snapshot(1, play=100, published="2026-09-20 08:00:00")
        self.snapshot(2, play=180, published="2026-09-20 08:00:00")
        self.assertEqual(self.service.works(self.filters)["total"], 0)
        self.assertEqual(self.service.overview(self.filters)["summary"]["playCount"], 80)
        self.assertEqual(self.service.overview(self.filters)["summary"]["publishedCount"], 0)

    def test_csv_exports_all_pages_and_defends_formula_injection(self):
        self.snapshot(1, title=" \t=HYPERLINK(危险)")
        self.snapshot(2, play=90, title=" \t=HYPERLINK(危险)")
        self.service.update_account_settings(1, "+负责人", ["@标签"])
        content = self.service.export_csv(self.filters, "works")
        self.assertTrue(content.startswith("\ufeff"))
        rows = list(csv.reader(io.StringIO(content.lstrip("\ufeff"))))
        self.assertIn("' \t=HYPERLINK(危险)", rows[1])
        self.assertIn("'+负责人", rows[1])
        self.assertIn("'@标签", rows[1])
        self.assertIn("-10", rows[1])
        self.assertNotIn("机密", content)
        page_filters = Filters.from_params({"startDate": "2026-10-01", "endDate": "2026-10-03", "pageSize": 1})
        self.assertEqual(len(list(csv.reader(io.StringIO(self.service.export_csv(page_filters, "accounts"))))), 4)

    def test_invalid_filters_settings_and_sort_are_rejected(self):
        for params in ({"startDate": "坏日期"}, {"startDate": "2024-01-01", "endDate": "2026-01-01"},
                       {"pageSize": 201}, {"platform": "sql"}, {"status": "9"}):
            with self.assertRaises(AnalyticsError):
                Filters.from_params(params)
        with self.assertRaises(AnalyticsError):
            self.service.update_account_settings(9, "负责人", [])
        with self.assertRaises(AnalyticsError):
            self.service.update_account_settings(1, "负责人", [None])
        with self.assertRaises(AnalyticsError):
            self.service.accounts(Filters.from_params({"sortBy": "filePath"}))

    def test_prior_period_comparison_has_equal_range_and_real_delta(self):
        with sqlite3.connect(self.path) as conn:
            for stamp, play in [("2026-09-28 12:00:00", 10), ("2026-09-30 12:00:00", 30)]:
                record_content_snapshot(conn, platform="douyin", account_id=1,
                    items=[{"item_id": "w1", "play_count": play}], synced_at=stamp)
        self.snapshot(1, play=40)
        self.snapshot(3, play=80)
        result = self.service.overview(self.filters)
        self.assertEqual(result["range"]["previousStartDate"], "2026-09-28")
        self.assertEqual(result["range"]["previousEndDate"], "2026-09-30")
        self.assertEqual(result["comparison"]["playCount"], {"current": 50, "previous": 20, "change": 30, "changePercent": 150.0})


if __name__ == "__main__":
    unittest.main()

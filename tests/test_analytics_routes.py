"""独立 Flask 集成验证，采集替身只替代浏览器并真实写入 SQLite。"""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from flask import Flask

from utils.analytics.routes import register_analytics_routes
from utils.analytics.service import AnalyticsError


class AnalyticsRouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "test.db"
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE user_info(id INTEGER PRIMARY KEY,type INTEGER,userName TEXT,status INTEGER)")
            conn.execute("INSERT INTO user_info VALUES(1,3,'账号甲',1)")
        self.calls = []
        self.app = Flask(__name__)
        self.app.testing = True
        register_analytics_routes(self.app, lambda: self.path, self.refresh)
        self.client = self.app.test_client()

    def tearDown(self):
        self.directory.cleanup()

    def refresh(self, account_id, platform, limit):
        self.calls.append((account_id, platform, limit))
        return {"items": [{"item_id": "真实作品夹具", "title": "作品甲", "play_count": 100,
                           "published_at": "2026-10-01 00:00:00"}],
                "followerCount": 123, "evidence": [{"kind": "profile_response"}], "scope": "partial"}

    def test_all_routes_without_main_application_dependency(self):
        for route in ("capabilities", "overview", "accounts", "works", "owners", "rankings", "account-settings"):
            response = self.client.get("/api/analytics/" + route)
            self.assertEqual(response.status_code, 200, route)
            self.assertEqual(response.json["code"], 200)
        self.assertTrue(self.client.get("/api/analytics/capabilities").json["data"]["refreshAvailable"])

    def test_refresh_persists_fan_and_work_snapshots_as_baseline(self):
        response = self.client.post("/api/analytics/accounts/1/refresh", json={"limit": 8})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.calls, [(1, "douyin", 8)])
        account = self.client.get("/api/analytics/accounts").json["data"]["items"][0]
        self.assertEqual(account["followerCount"], 123)
        self.assertIsNone(account["newFollowers"])
        self.assertEqual(account["playCount"], 100)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM analytics_work_snapshots").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM analytics_account_snapshots").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM analytics_sync_runs").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT play_count FROM content_stats").fetchone()[0], 100)

    def test_refresh_checks_account_and_bounds_before_collecting(self):
        self.assertEqual(self.client.post("/api/analytics/accounts/999/refresh", json={}).status_code, 404)
        self.assertEqual(self.client.post("/api/analytics/accounts/1/refresh", json={"limit": 99}).status_code, 400)
        self.assertEqual(self.client.post("/api/analytics/accounts/1/refresh", json=[1]).status_code, 400)
        self.assertEqual(self.calls, [])

    def test_failed_collector_does_not_record_fictitious_zeroes(self):
        other = Flask("failed")
        def failed(*args):
            raise AnalyticsError("登录已失效", 401)
        register_analytics_routes(other, lambda: self.path, failed)
        response = other.test_client().post("/api/analytics/accounts/1/refresh", json={})
        self.assertEqual(response.status_code, 401)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM analytics_work_snapshots").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM analytics_account_snapshots").fetchone()[0], 0)

    def test_settings_and_authenticated_attachment_export_contract(self):
        updated = self.client.put("/api/analytics/account-settings", json={"accountId": 1, "owner": "负责人甲", "tags": ["运营"]})
        self.assertEqual(updated.json["data"]["owner"], "负责人甲")
        self.client.patch("/api/analytics/account-settings", json={"accountId": 1, "owner": "负责人乙"})
        self.assertEqual(self.client.get("/api/analytics/account-settings").json["data"]["items"][0]["tags"], ["运营"])
        response = self.client.get("/api/analytics/export?entity=accounts&owner=负责人乙")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertIn("负责人乙", response.data.decode("utf-8-sig"))
        self.assertEqual(self.client.get("/api/analytics/export?entity=unknown").status_code, 400)


if __name__ == "__main__":
    unittest.main()

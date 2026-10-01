"""分析机器人推送验证；所有外部请求均使用替身，不联系任何真实群聊。"""
from __future__ import annotations

import concurrent.futures
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from flask import Flask

from utils.analytics.push import (
    AnalyticsPushService, deliver_report, register_analytics_push_routes,
    report_range, validate_webhook,
)
from utils.analytics.service import AnalyticsError
from utils.analytics.store import record_content_snapshot

WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=测试占位令牌"
UTC = timezone.utc
CHINA = timezone(timedelta(hours=8))


class RecordingSender:
    """线程安全的机器人替身，记录请求参数以验证只发送一次与脱敏边界。"""
    def __init__(self, status="sent", error=None):
        self.status, self.error = status, error
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, *args):
        with self.lock:
            self.calls.append(args)
        return self.status, self.error


class AnalyticsPushTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "reports.db"
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE user_info(id INTEGER PRIMARY KEY,type INTEGER,userName TEXT,status INTEGER)")
            conn.executemany("INSERT INTO user_info VALUES(?,?,?,?)", [(1, 3, "测试抖音", 1), (2, 1, "测试小红书", 1)])
        self.sender = RecordingSender()
        self.configuration = SimpleNamespace(DINGTALK_WEBHOOK_URL="", DINGTALK_SECRET="")
        self.service = AnalyticsPushService(lambda: self.path, self.configuration, self.sender)
        # 边界用固定有时区日期，完全不依赖宿主机当前时间。
        self.at = datetime(2026, 10, 5, 9, 0, tzinfo=CHINA)

    def tearDown(self):
        self.service.stop()
        self.directory.cleanup()

    def configure(self, **extra):
        return self.service.update_settings({"webhookUrl": WEBHOOK, "secret": "测试签名占位符",
            "accountIds": [1], "frequencies": ["daily"], "sendTime": "09:00", **extra})

    def test_only_official_https_robot_origins_are_accepted(self):
        cases = [("dingtalk", WEBHOOK), ("feishu", "https://open.feishu.cn/open-apis/bot/v2/hook/fixture-token"),
                 ("wecom", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=fixture-key")]
        for channel, url in cases:
            self.assertEqual(validate_webhook(channel, url), url)
        invalid = ["http://oapi.dingtalk.com/robot/send?access_token=x",
                   "https://oapi.dingtalk.com.example.com/robot/send?access_token=x",
                   "https://oapi.dingtalk.com@127.0.0.1/robot/send?access_token=x",
                   "https://user:password@oapi.dingtalk.com/robot/send?access_token=x",
                   "https://oapi.dingtalk.com:8443/robot/send?access_token=x",
                   "https://oapi.dingtalk.com/elsewhere?access_token=x",
                   "https://oapi.dingtalk.com/robot/send", WEBHOOK + "#ignored"]
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(AnalyticsError):
                validate_webhook("dingtalk", url)
        with self.assertRaises(AnalyticsError):
            validate_webhook("feishu", "https://open.feishu.cn/open-apis/bot/v2/hook/../../elsewhere")

    def test_malformed_webhook_is_a_business_error_not_unhandled_exception(self):
        with self.assertRaises(AnalyticsError):
            validate_webhook("dingtalk", "https://[")

    def test_default_disabled_read_and_tick_do_not_contact_network(self):
        with patch("utils.analytics.push.requests.post") as post:
            settings = self.service.settings()
            self.assertFalse(settings["enabled"])
            self.assertEqual(settings["frequencies"], [])
            self.assertEqual(self.service.tick(self.at), [])
            self.assertEqual(self.service.records()["items"], [])
            post.assert_not_called()
        self.assertEqual(self.sender.calls, [])

    def test_saving_and_enabling_settings_do_not_send_and_hide_credentials(self):
        with patch("utils.analytics.push.requests.post") as post:
            result = self.configure(enabled=True)
            post.assert_not_called()
        self.assertTrue(result["enabled"])
        self.assertTrue(result["hasWebhook"])
        self.assertTrue(result["hasSecret"])
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("测试占位令牌", serialized)
        self.assertNotIn("测试签名占位符", serialized)
        self.assertNotIn("webhookUrl", result)
        self.assertNotIn("secret", result)
        self.assertEqual(self.sender.calls, [])

    def test_switching_channel_does_not_forward_previous_channel_secret(self):
        self.configure()
        self.service.update_settings({"channel": "feishu", "webhookUrl": "https://open.feishu.cn/open-apis/bot/v2/hook/fixture"})
        private = self.service.settings(public=False)
        self.assertEqual(private["secret"], "")
        self.assertNotIn("测试占位令牌", private["webhookUrl"])

    def test_invalid_enable_time_frequency_timezone_and_account_are_rejected(self):
        for data in ({"enabled": True}, {"sendTime": "24:00"}, {"frequencies": ["hourly"]},
                     {"utcOffsetMinutes": True}, {"utcOffsetMinutes": 841}, {"accountIds": [True]},
                     {"accountIds": [99]}, {"secret": []}, {"unknown": True}):
            with self.subTest(data=data), self.assertRaises(AnalyticsError):
                self.service.update_settings(data)
        self.assertEqual(self.sender.calls, [])

    def test_previous_period_ranges_include_year_and_leap_month_boundaries(self):
        self.assertEqual(report_range("daily", date(2026, 1, 1)), (date(2025, 12, 31), date(2025, 12, 31)))
        self.assertEqual(report_range("weekly", date(2026, 10, 5)), (date(2026, 9, 28), date(2026, 10, 4)))
        self.assertEqual(report_range("monthly", date(2024, 3, 1)), (date(2024, 2, 1), date(2024, 2, 29)))
        self.assertEqual(report_range("monthly", date(2026, 1, 1)), (date(2025, 12, 1), date(2025, 12, 31)))

    def test_daily_boundary_uses_configured_offset_and_sends_once_per_period(self):
        self.configure(enabled=True)
        self.assertEqual(self.service.tick(datetime(2026, 10, 5, 0, 59, tzinfo=UTC)), [])
        first = self.service.tick(datetime(2026, 10, 5, 1, 0, tzinfo=UTC))
        again = self.service.tick(datetime(2026, 10, 5, 2, 0, tzinfo=UTC))
        self.assertEqual(first[0]["id"], again[0]["id"])
        self.assertEqual(first[0]["status"], "sent")
        self.assertEqual(len(self.sender.calls), 1)
        self.assertIn("统计区间：2026-10-04 至 2026-10-04", self.sender.calls[0][3])
        self.service.tick(datetime(2026, 10, 6, 1, 0, tzinfo=UTC))
        self.assertEqual(len(self.sender.calls), 2)

    def test_weekly_runs_on_monday_and_monthly_only_on_first_day(self):
        self.configure(enabled=True, frequencies=["weekly", "monthly"])
        self.assertEqual(self.service.tick(datetime(2026, 9, 29, 9, 0, tzinfo=CHINA)), [])
        month = self.service.tick(datetime(2026, 10, 1, 9, 0, tzinfo=CHINA))
        self.assertEqual([row["period"] for row in month], ["monthly"])
        self.assertIn("2026-09-01 至 2026-09-30", self.sender.calls[-1][3])
        week = self.service.tick(self.at)
        self.assertEqual([row["period"] for row in week], ["weekly"])
        self.assertIn("2026-09-28 至 2026-10-04", self.sender.calls[-1][3])

    def test_first_day_monday_runs_each_enabled_frequency_once(self):
        self.configure(enabled=True, frequencies=["daily", "weekly", "monthly"])
        at = datetime(2026, 6, 1, 9, 0, tzinfo=CHINA)
        first = self.service.tick(at)
        repeated = self.service.tick(at + timedelta(minutes=30))
        self.assertEqual([row["period"] for row in first], ["daily", "weekly", "monthly"])
        self.assertEqual([row["id"] for row in first], [row["id"] for row in repeated])
        self.assertEqual(len(self.sender.calls), 3)

    def test_same_key_concurrent_instances_send_exactly_once(self):
        self.configure()
        other = AnalyticsPushService(lambda: self.path, self.configuration, self.sender)
        data = {"period": "daily", "idempotencyKey": "同一报表幂等键"}
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda service: service.send(data, at=self.at), [self.service, other]))
        self.assertEqual(responses[0]["id"], responses[1]["id"])
        self.assertEqual(len(self.sender.calls), 1)

    def test_different_payload_with_same_key_is_rejected(self):
        self.configure(accountIds=[1, 2])
        self.service.send({"period": "daily", "accountIds": [1], "idempotencyKey": "不可复用"}, at=self.at)
        with self.assertRaises(AnalyticsError) as conflict:
            self.service.send({"period": "daily", "accountIds": [2], "idempotencyKey": "不可复用"}, at=self.at)
        self.assertEqual(conflict.exception.code, 409)
        self.assertEqual(len(self.sender.calls), 1)

    def test_unknown_blocks_new_key_until_manual_resolution_without_resending(self):
        self.configure()
        self.sender.status, self.sender.error = "unknown", "结果待核查"
        first = self.service.send({"idempotencyKey": "未知一"}, at=self.at)
        duplicate = self.service.send({"idempotencyKey": "未知一"}, at=self.at)
        self.assertEqual(first["id"], duplicate["id"])
        with self.assertRaises(AnalyticsError) as pending:
            self.service.send({"idempotencyKey": "未知二"}, at=self.at)
        self.assertEqual(pending.exception.code, 409)
        resolved = self.service.resolve(first["id"], "not_sent")
        self.assertEqual(resolved["status"], "failed")
        self.assertEqual(len(self.sender.calls), 1)
        self.sender.status, self.sender.error = "sent", None
        sent = self.service.send({"idempotencyKey": "核查后显式新发送"}, at=self.at)
        self.assertEqual(sent["status"], "sent")
        self.assertEqual(len(self.sender.calls), 2)

    def test_same_robot_query_variation_cannot_bypass_unknown_block(self):
        self.configure()
        self.sender.status = "unknown"
        self.service.send({"idempotencyKey": "原机器人未知报表"}, at=self.at)
        try:
            self.service.update_settings({"webhookUrl": WEBHOOK + "&ignored=1"})
            self.service.send({"idempotencyKey": "改写地址不能重发"}, at=self.at)
        except AnalyticsError:
            # 拒绝无关参数，或识别为同一个目的地并阻止发送，都是安全处理。
            pass
        self.assertEqual(len(self.sender.calls), 1)

    def test_scheduled_send_does_not_send_after_configuration_is_disabled(self):
        self.configure(enabled=True)
        self.service.update_settings({"enabled": False})
        try:
            self.service.send({"period": "daily"}, scheduled=True, at=self.at)
        except AnalyticsError:
            pass
        self.assertEqual(self.sender.calls, [])

    def test_scheduled_send_rechecks_due_time_after_time_configuration_changes(self):
        self.configure(enabled=True)
        # tick 读到原 09:00 的计划后，用户将时间推迟至 10:00。
        self.service.update_settings({"sendTime": "10:00"})
        try:
            self.service.send({"period": "daily"}, scheduled=True, at=self.at)
        except AnalyticsError:
            pass
        self.assertEqual(self.sender.calls, [])

    def test_runtime_audit_merge_preserves_latest_user_configuration(self):
        self.configure(enabled=True)
        self.service.update_settings({"enabled": False, "frequencies": ["monthly"],
                                      "sendTime": "12:30", "accountIds": [2]})
        self.service.merge_runtime_state("2026-10-05T01:00:00+00:00", "测试运行状态")
        latest = self.service.settings()
        self.assertFalse(latest["enabled"])
        self.assertEqual(latest["frequencies"], ["monthly"])
        self.assertEqual(latest["sendTime"], "12:30")
        self.assertEqual(latest["accountIds"], [2])
        self.assertEqual(latest["error"], "测试运行状态")

    def test_sender_exception_is_unknown_and_secret_is_never_reported(self):
        self.configure()
        self.service.sender = Mock(side_effect=RuntimeError(WEBHOOK + " 测试签名占位符"))
        record = self.service.send({"idempotencyKey": "异常结果"}, at=self.at)
        self.assertEqual(record["status"], "unknown")
        response = json.dumps(self.service.records(), ensure_ascii=False)
        self.assertNotIn("测试占位令牌", response)
        self.assertNotIn("测试签名占位符", response)

    def test_baseline_report_does_not_forge_growth_or_missing_fans(self):
        self.configure()
        with sqlite3.connect(self.path) as conn:
            record_content_snapshot(conn, platform="douyin", account_id=1,
                items=[{"item_id": "首个观测", "play_count": 900,
                        "published_at": "2026-10-04 10:00:00", "status": "已发布"}],
                synced_at="2026-10-04 11:00:00")
        self.service.send({"idempotencyKey": "基线报表"}, at=self.at)
        text = self.sender.calls[0][3]
        self.assertIn("播放/阅读：—（缺少可计算的观测数据）", text)
        self.assertIn("新增粉丝：—（缺少可计算的观测数据）", text)
        self.assertIn("发布数：1", text)
        self.assertIn("首次采集是基线", text)

    def test_partial_account_growth_is_marked_in_report(self):
        self.configure(accountIds=[1, 2])
        with sqlite3.connect(self.path) as conn:
            for hour, count in ((1, 100), (12, 130)):
                record_content_snapshot(conn, platform="douyin", account_id=1,
                    items=[{"item_id": "作品", "play_count": count}],
                    synced_at=f"2026-10-04 {hour:02d}:00:00")
        self.service.send({"idempotencyKey": "部分账号报表"}, at=self.at)
        self.assertIn("播放/阅读：30（部分账号缺少数据）", self.sender.calls[0][3])

    def test_daily_report_can_compare_real_previous_day_baseline(self):
        self.configure()
        with sqlite3.connect(self.path) as conn:
            for stamp, count in (("2026-10-03 12:00:00", 100), ("2026-10-04 12:00:00", 130)):
                record_content_snapshot(conn, platform="douyin", account_id=1,
                    items=[{"item_id": "按日采样作品", "play_count": count}], synced_at=stamp)
        self.service.send({"idempotencyKey": "日报使用区间前基线"}, at=self.at)
        self.assertIn("播放/阅读：30", self.sender.calls[0][3])
        self.assertIn("首次采集是基线", self.sender.calls[0][3])

    def test_http_read_and_save_do_not_start_worker_when_disabled(self):
        app = Flask("推送测试")
        app.testing = True
        app.config.update(ANALYTICS_PUSH_SENDER=self.sender, ANALYTICS_PUSH_WORKER_ENABLED=False)
        register_analytics_push_routes(app, lambda: self.path, self.configuration)
        client = app.test_client()
        self.assertFalse(client.get("/api/analytics/push-settings").json["data"]["enabled"])
        saved = client.patch("/api/analytics/push-settings", json={"webhookUrl": WEBHOOK, "accountIds": [1]})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.sender.calls, [])
        self.assertEqual(client.get("/api/analytics/push-records").json["data"]["items"], [])
        self.assertEqual(client.post("/api/analytics/push", json=[]).status_code, 400)
        self.assertIsNone(app.extensions["analytics_push_service"]()._worker)


class RobotDeliveryTests(unittest.TestCase):
    def test_confirmations_all_three_channels_and_no_redirects(self):
        cases = [("dingtalk", WEBHOOK, {"errcode": 0}),
                 ("wecom", "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=fixture", {"errcode": 0}),
                 ("feishu", "https://open.feishu.cn/open-apis/bot/v2/hook/fixture", {"code": 0})]
        for channel, url, payload in cases:
            response = Mock(status_code=200)
            response.json.return_value = payload
            with self.subTest(channel=channel), patch("utils.analytics.push.requests.post", return_value=response) as post:
                self.assertEqual(deliver_report(channel, url, "报表", "测试文本", ""), ("sent", None))
                self.assertFalse(post.call_args.kwargs["allow_redirects"])
                self.assertEqual(post.call_args.kwargs["timeout"], 30)

    def test_timeout_missing_ack_and_invalid_response_are_unknown(self):
        response = Mock(status_code=200)
        for payload in ({}, [], {"success": True}):
            response.json.return_value = payload
            with patch("utils.analytics.push.requests.post", return_value=response):
                self.assertEqual(deliver_report("dingtalk", WEBHOOK, "报表", "测试", "")[0], "unknown")
        with patch("utils.analytics.push.requests.post", side_effect=requests.Timeout(WEBHOOK)):
            result = deliver_report("dingtalk", WEBHOOK, "报表", "测试", "")
            self.assertEqual(result[0], "unknown")
            self.assertNotIn("测试占位令牌", result[1])

    def test_explicit_rejection_is_failed_and_boolean_zero_is_not_success(self):
        response = Mock(status_code=200)
        for code, expected in ((310000, "failed"), (False, "unknown"), ("0", "unknown")):
            response.json.return_value = {"errcode": code}
            with patch("utils.analytics.push.requests.post", return_value=response):
                self.assertEqual(deliver_report("dingtalk", WEBHOOK, "报表", "测试", "")[0], expected)


if __name__ == "__main__":
    unittest.main()

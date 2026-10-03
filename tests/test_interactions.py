"""互动工作台的去重、历史隔离、失败语义与配置约束测试。"""
import concurrent.futures
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from utils.interactions.routes import register_interaction_routes
from utils.interactions.service import InteractionError, InteractionService


def caps():
    """测试适配器仅承诺已经实现的评论和私信。"""
    return [{"platform": "douyin", "label": "抖音", "kinds": ["comment", "private"],
             "operations": ["fetch", "reply"], "status": "available", "reason": "测试适配器"}]


class FakeAdapter:
    """隔离平台请求，支持模拟提交后连接中断。"""
    def __init__(self):
        self.items, self.sent, self.unknown = [], [], False

    def fetch(self, account, cursor=None, kind="comment", limit=50):
        return {"items": [m for m in self.items if m["kind"] == kind], "cursor": None, "hasMore": False}

    def send_reply(self, account, message, text, reply_key):
        self.sent.append((message["platformMessageId"], text))
        if self.unknown:
            raise ConnectionError("模拟平台接收后连接中断")
        return {"confirmed": True, "platformReplyId": "reply-1"}


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.adapter = FakeAdapter()
        self.service = InteractionService(self.root / "database.db", self.root / "cookies", lambda _: self.adapter, caps)
        with self.service.store.connect() as conn:
            conn.execute("CREATE TABLE user_info(id INTEGER PRIMARY KEY,type INTEGER,userName TEXT,filePath TEXT,status INTEGER)")
            conn.executemany("INSERT INTO user_info VALUES(?,?,?,?,?)", [(1, 3, "隔离抖音账号", "test.json", 1), (2, 3, "第二账号", "other.json", 1)])

    def tearDown(self):
        self.service.stop()
        self.directory.cleanup()

    def item(self, identifier="comment-1", **extra):
        return {"platformMessageId": identifier, "kind": "comment", "text": "请问价格多少", "authorName": "测试用户",
                "createdAt": (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(), **extra}

    def ingest(self, **extra):
        return self.service.ingest(self.service._account(1), "comment", [self.item(**extra)])[0]

    def rule(self, **extra):
        return self.service.save_rule({"name": "价格回复", "platform": "douyin", "accountIds": [1], "type": "comment",
                                       "trigger": "keyword", "keywords": ["价格"], "text": "请查看作品说明", **extra})

    def test_ingest_preserves_local_state_and_deduplicates(self):
        identifier = self.ingest()
        self.service.mark(identifier, {"read": True, "handled": True})
        fresh = self.service.ingest(self.service._account(1), "comment", [self.item(text="已修改的留言")])
        self.assertEqual(fresh, [])
        result = self.service.message(identifier)["message"]
        self.assertTrue(result["read"])
        self.assertTrue(result["handled"])
        self.assertEqual(result["text"], "已修改的留言")

    def test_new_article_accounts_do_not_break_or_gain_interaction_capabilities(self):
        """新增文章账号不能使既有互动列表失败，也不能自动获得采集权限。"""
        with self.service.store.connect() as conn:
            conn.executemany("INSERT INTO user_info VALUES(?,?,?,?,?)", [
                (3, 10, "微博文章账号", "weibo.json", 1),
                (4, 11, "企鹅号文章账号", "qiehao.json", 1),
                (5, 12, "微信公众号文章账号", "wechat.json", 1),
                (6, 13, "京东图文账号", "jd.json", 1),
                (7, 14, "小红书商家号", "merchant.json", 1),
                (8, 15, "懂车号账号", "dongchedi.json", 1),
                (9, 16, "淘宝光合账号", "taobao.json", 1)])
        items = self.service.accounts()["items"]
        self.assertEqual([item["id"] for item in items], [1, 2])
        self.assertTrue(all(item["platform"] == "douyin" for item in items))
        for account_id in range(3, 10):
            with self.subTest(account_id=account_id), self.assertRaisesRegex(InteractionError, "不支持的账号平台"):
                self.service.sync_account(account_id)
            with self.subTest(account_id=account_id), self.assertRaisesRegex(InteractionError, "不支持的账号平台"):
                self.service.update_settings({"accountIds": [account_id], "enabled": True})
        from utils.interactions.adapters import list_capabilities
        self.assertNotIn("weibo", {item["platform"] for item in list_capabilities()})
        self.assertNotIn("qiehao", {item["platform"] for item in list_capabilities()})
        self.assertNotIn("wechat", {item["platform"] for item in list_capabilities()})
        for platform in ("jd", "xiaohongshu_merchant", "dongchedi", "taobao"):
            self.assertNotIn(platform, {item["platform"] for item in list_capabilities()})

    def test_manual_reply_idempotency_and_payload_conflict(self):
        identifier = self.ingest()
        first = self.service.reply(identifier, {"text": "谢谢", "idempotencyKey": "reply-test"})
        duplicate = self.service.reply(identifier, {"text": "谢谢", "idempotencyKey": "reply-test"})
        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual(first["status"], "sent")
        self.assertEqual(len(self.adapter.sent), 1)
        with self.assertRaises(InteractionError):
            self.service.reply(identifier, {"text": "不同回复", "idempotencyKey": "reply-test"})

    def test_concurrent_instances_only_send_once(self):
        identifier = self.ingest()
        second = InteractionService(self.root / "database.db", self.root / "cookies", lambda _: self.adapter, caps)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda s: s.reply(identifier, {"text": "谢谢", "idempotencyKey": "concurrent-key"}), [self.service, second]))
        self.assertEqual(results[0]["id"], results[1]["id"])
        self.assertEqual(len(self.adapter.sent), 1)

    def test_unknown_reply_blocks_retry_until_resolution(self):
        identifier = self.ingest()
        self.adapter.unknown = True
        result = self.service.reply(identifier, {"text": "谢谢", "idempotencyKey": "unknown-key"})
        self.assertEqual(result["status"], "unknown")
        self.assertNotIn("模拟", result["error"])
        self.assertFalse(self.service.message(identifier)["message"]["handled"])
        with self.assertRaises(InteractionError):
            self.service.reply(identifier, {"text": "谢谢", "idempotencyKey": "different-key"})
        self.service.resolve(result["id"], {"outcome": "sent"})
        self.assertTrue(self.service.message(identifier)["message"]["handled"])
        self.assertEqual(len(self.adapter.sent), 1)

    def test_new_rules_are_disabled_even_if_payload_says_enabled(self):
        rule = self.rule(enabled=True)
        self.assertFalse(rule["enabled"])
        self.assertIsNone(rule["enabledAt"])

    def test_disabling_rule_after_selection_prevents_external_submission(self):
        rule = self.rule()
        self.service.save_rule({"enabled": True}, rule["id"])
        identifier = self.ingest()
        original = self.service.reply

        def disable_before_claim(*args, **kwargs):
            self.service.save_rule({"enabled": False}, rule["id"])
            return original(*args, **kwargs)

        with patch.object(self.service, "reply", side_effect=disable_before_claim):
            self.assertIsNone(self.service.apply_rules(identifier))
        self.assertEqual(self.adapter.sent, [])
        self.assertEqual(self.service.message(identifier)["replies"], [])

    def test_runtime_update_preserves_newly_disabled_user_configuration(self):
        self.service.update_settings({"enabled": True, "accountIds": [1]})
        self.service.update_settings({"enabled": False, "intervalSeconds": 600,
                                      "notifications": {"enabled": False, "browser": False}})
        self.service.store.merge_runtime_state("2026-10-01T00:00:00+00:00", "采集失败")
        latest = self.service.store.settings()
        self.assertFalse(latest["enabled"])
        self.assertFalse(latest["notifications"]["enabled"])
        self.assertEqual(latest["intervalSeconds"], 600)

    def test_welcome_event_has_separate_strategy_and_cannot_be_manually_replied(self):
        def welcome_caps():
            return [{"platform": "douyin", "kinds": ["private", "welcome"],
                     "operations": {"welcome": {"reply": "unverified"}}}]

        self.service.capability_provider = welcome_caps
        rule = self.service.save_rule({"name": "会话欢迎语", "platform": "douyin", "accountIds": [1],
            "type": "welcome", "trigger": "immediate", "text": "欢迎咨询"})
        self.service.save_rule({"enabled": True}, rule["id"])
        identifier = self.service.ingest(self.service._account(1), "welcome", [self.item(kind="welcome", text="进入会话")])[0]
        with self.assertRaises(InteractionError):
            self.service.reply(identifier, {"text": "欢迎咨询", "idempotencyKey": "manual-welcome"})
        self.assertEqual(self.service.apply_rules(identifier)["status"], "sent")
        self.service.apply_rules(identifier)
        self.assertEqual(len(self.adapter.sent), 1)

    def test_baseline_and_old_messages_never_auto_reply(self):
        rule = self.rule()
        self.service.save_rule({"enabled": True}, rule["id"])
        self.adapter.items = [self.item()]
        self.service.sync_account(1, "comment")
        self.assertEqual(self.adapter.sent, [])
        self.adapter.items.append(self.item("historical", createdAt="2020-01-01T00:00:00Z"))
        self.service.sync_account(1, "comment")
        self.assertEqual(self.adapter.sent, [])
        self.adapter.items.append(self.item("fresh"))
        self.service.sync_account(1, "comment")
        self.assertEqual(len(self.adapter.sent), 1)
        self.service.sync_account(1, "comment")
        self.assertEqual(len(self.adapter.sent), 1)

    def test_missing_time_and_outbound_do_not_trigger(self):
        rule = self.rule()
        self.service.save_rule({"enabled": True}, rule["id"])
        for index, extra in enumerate(({"createdAt": None}, {"direction": "outbound"})):
            message_id = self.ingest(identifier=f"skip-{index}", **extra)
            self.assertIsNone(self.service.apply_rules(message_id))
        self.assertEqual(self.adapter.sent, [])

    def test_hourly_limit_checked_transactionally(self):
        self.service.update_settings({"rateLimitPerHour": 1})
        rule = self.rule()
        self.service.save_rule({"enabled": True}, rule["id"])
        first = self.ingest()
        self.service.apply_rules(first)
        second = self.service.ingest(self.service._account(1), "comment", [self.item("second")])[0]
        with self.assertRaises(InteractionError) as context:
            self.service.apply_rules(second)
        self.assertEqual(context.exception.status, 429)
        self.assertEqual(len(self.adapter.sent), 1)

    def test_no_cross_account_key_collision(self):
        first = self.ingest()
        second = self.service.ingest(self.service._account(2), "comment", [self.item()])[0]
        self.assertNotEqual(first, second)
        self.assertEqual(self.service.messages({})["total"], 2)

    def test_query_and_state_filters(self):
        identifier = self.ingest(text="带有100%与_字符")
        self.assertEqual(self.service.messages({"q": "%"})["total"], 1)
        self.assertEqual(self.service.messages({"q": "不存在"})["total"], 0)
        self.service.mark(identifier, {"read": True})
        self.assertEqual(self.service.messages({"state": "unread"})["total"], 0)
        with self.assertRaises(InteractionError):
            self.service.messages({"pageSize": 1001})

    def test_path_escape_is_rejected(self):
        with self.service.store.connect() as conn:
            conn.execute("UPDATE user_info SET filePath='../outside.json' WHERE id=1")
        with self.assertRaises(InteractionError):
            self.service._account(1)

    def test_config_validation_and_phrase_crud(self):
        with self.assertRaises(InteractionError):
            self.service.update_settings({"enabled": "true"})
        with self.assertRaises(InteractionError):
            self.service.update_settings({"enabled": True, "accountIds": []})
        with self.assertRaises(InteractionError):
            self.rule(type="welcome", enabled=True)
        phrase = self.service.save_phrase({"name": "感谢", "text": "谢谢关注"})
        self.assertEqual(self.service.store.records("interaction_phrases")[0]["id"], phrase["id"])
        self.service.delete_record("interaction_phrases", phrase["id"])
        self.assertEqual(self.service.store.records("interaction_phrases"), [])

    def test_job_reports_per_account_failures(self):
        job = self.service.create_sync_job({"accountIds": [1], "kind": "comment"}, background=False)
        self.assertEqual(job["status"], "completed")
        self.assertTrue(job["results"][0]["baseline"])
        self.assertEqual(self.service.sync_job(job["id"])["results"], job["results"])

    def test_stale_sending_is_recovered_as_unknown(self):
        identifier = self.ingest()
        result = self.service.reply(identifier, {"text": "谢谢", "idempotencyKey": "recovery"})
        with self.service.store.connect() as conn:
            conn.execute("UPDATE interaction_replies SET status='sending',updated_at='2020-01-01T00:00:00+00:00' WHERE id=?", (result["id"],))
        self.service.recover_interrupted()
        self.assertEqual(self.service.message(identifier)["replies"][0]["status"], "unknown")
        self.assertEqual(len(self.adapter.sent), 1)

    def test_http_routes_isolated_and_no_worker_on_read(self):
        app = Flask(__name__)
        app.config.update(INTERACTION_BASE_DIR=self.root, INTERACTION_DB_PATH=self.root / "database.db",
                          INTERACTION_ADAPTER_FACTORY=lambda _: self.adapter, INTERACTION_CAPABILITIES=caps,
                          INTERACTION_WORKER_ENABLED=False, INTERACTION_ASYNC_JOBS=False)
        register_interaction_routes(app, SimpleNamespace(BASE_DIR=self.root))
        client = app.test_client()
        self.assertEqual(client.get("/api/interactions/capabilities").status_code, 200)
        self.assertEqual(client.get("/api/interactions/accounts").json["data"]["items"][0]["name"], "隔离抖音账号")
        self.assertEqual(client.post("/api/interactions/sync", json=[]).status_code, 400)
        self.assertEqual(client.post("/api/interactions/sync", json={"accountIds": [1], "kind": "comment"}).json["data"]["status"], "completed")
        self.assertIsNone(app.extensions["interaction_service"]()._worker)


if __name__ == "__main__":
    unittest.main()

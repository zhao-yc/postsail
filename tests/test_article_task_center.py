"""全局任务查询与持久化提醒的 SQLite/API 验证，不连接真实平台。"""
from __future__ import annotations

import json
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from flask import Flask

from tests.test_article_scheduling import SchedulingFixture, schedule
from utils.articles.model import ArticleError
from utils.articles.routes import register_article_routes
from utils.articles.store import ArticleStore, SCHEMA


class ArticleTaskCenterTests(SchedulingFixture, unittest.TestCase):
    def add_task(self, title="任务中心独立文章", platform="zhihu", mode="publish", **kwargs):
        article = self.service.create_article({"title": title, "format": "text", "content": "冻结的正文内容",
                                               "cover_asset_id": self.cover["id"]})
        target = {"platform": platform, "account_id": 3 if platform == "zhihu" else 1, **kwargs}
        batch = self.service.publish(article["id"], {"revision": 1, "mode": mode,
                                    "idempotency_key": article["id"], "targets": [target]})
        return batch["tasks"][0]

    def set_status(self, task, status, **values):
        fields = {"status": status, "stage": "finished", "message": "账号登录失效，需要重新登录", "updated_at": self.now, **values}
        with self.service.store.connect(write=True) as conn:
            conn.execute("UPDATE article_publish_tasks SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?",
                         [*fields.values(), task["id"]])

    def client(self):
        app = Flask(__name__)
        app.config.update(ARTICLE_BASE_DIR=self.base, ARTICLE_DB_PATH=self.base / "db.sqlite",
                          ARTICLE_ASSET_DIR=self.base / "assets", ARTICLE_COOKIE_DIR=self.cookies,
                          ARTICLE_EVIDENCE_DIR=self.base / "evidence", ARTICLE_WORKER_ENABLED=False)
        register_article_routes(app, SimpleNamespace(BASE_DIR=self.base))
        return app.test_client()

    def test_global_filters_frozen_title_modes_and_pagination(self):
        scheduled = self.add_task("标题含100%_原文", schedule=schedule())
        self.now = "2030-01-02T00:00:00.000000+00:00"
        failed = self.add_task("另一篇需要处理的文章", platform="douyin")
        self.set_status(failed, "failed")
        self.now = "2030-01-03T00:00:00.000000+00:00"
        preview = self.add_task("预览稿件标题", mode="preview")
        self.set_status(preview, "previewed")
        self.service.update_article(scheduled["article_id"], {"expected_revision": 1, "title": "编辑后的新标题"})
        self.assertEqual(self.service.all_tasks({})["total"], 3)
        results = self.service.all_tasks({"q": "100%_", "page_size": "1"})
        self.assertEqual(results["items"][0]["id"], scheduled["id"])
        self.assertEqual(results["items"][0]["title"], "标题含100%_原文")
        self.assertEqual(self.service.all_tasks({"q": "编辑后的新标题"})["total"], 0)
        self.assertEqual(self.service.all_tasks({"q": "冻结的正文内容"})["total"], 0)
        self.assertEqual(self.service.all_tasks({"platform": "douyin", "account_id": "1", "status": "attention"})["total"], 1)
        self.assertEqual(self.service.all_tasks({"status": "pending", "mode": "publish"})["items"][0]["id"], scheduled["id"])
        self.assertEqual(self.service.all_tasks({"mode": "preview"})["items"][0]["id"], preview["id"])
        # 状态计数覆盖同一组其他筛选条件，点击不同状态卡片不会丢失总数。
        self.assertEqual(self.service.all_tasks({"status": "attention"})["summary"]["total"], 3)
        pages = [self.service.all_tasks({"page": n, "page_size": 1})["items"][0]["id"] for n in (1, 2, 3)]
        self.assertEqual(pages, [preview["id"], failed["id"], scheduled["id"]])
        self.assertEqual(self.service.all_tasks({"page": 4, "page_size": 1})["items"], [])

    def test_creation_time_offset_and_exclusive_end(self):
        task = self.add_task()
        # 旧时间没有微秒也必须落在区间内。
        with self.service.store.connect(write=True) as conn:
            conn.execute("UPDATE article_publish_tasks SET created_at='2030-01-01T00:00:00+00:00' WHERE id=?", (task["id"],))
        self.assertEqual(self.service.all_tasks({"created_from": "2030-01-01T08:00:00+08:00", "created_before": "2030-01-01T00:00:01Z"})["total"], 1)
        self.assertEqual(self.service.all_tasks({"created_before": "2030-01-01T00:00:00Z"})["total"], 0)

    def test_invalid_queries_return_actionable_errors(self):
        cases = [{"page": True}, {"page": "1.5"}, {"page": "9" * 5000}, {"page_size": 101},
                 {"account_id": "0"}, {"status": "bogus"}, {"platform": "bogus"}, {"mode": "bogus"},
                 {"q": "a" * 201}, {"unread": "true"}, {"created_from": "2030-01-01T00:00:00"},
                 {"created_before": "not-a-date"}, {"created_from": "2030-02-01T00:00:00Z", "created_before": "2030-01-01T00:00:00Z"}]
        for query in cases:
            with self.subTest(query=str(query)[:100]), self.assertRaises(ArticleError):
                self.service.all_tasks(query)

    def test_details_use_snapshot_and_handle_deleted_accounts_without_internal_content(self):
        task = self.add_task()
        with self.service.store.connect(write=True) as conn:
            conn.execute("UPDATE article_publish_tasks SET prepared_html='<p>internal-body</p>' WHERE id=?", (task["id"],))
            conn.execute("DELETE FROM user_info WHERE id=3")
        result = self.service.get_task(task["id"])
        self.assertFalse(result["account_exists"])
        self.assertIn("已移除账号", result["account_name"])
        self.assertNotIn("snapshot_json", result)
        self.assertNotIn("prepared_html", result)
        self.assertNotIn("filePath", result)
        with self.assertRaises(ArticleError) as error:
            self.service.get_task("missing")
        self.assertEqual(error.exception.status, 404)

    def test_validation_failure_alert_and_transaction_rollback(self):
        task = self.add_task(overrides={"title": "a" * 301})
        self.assertEqual(task["status"], "failed")
        self.assertEqual(self.service.task_notifications()["unread"], 1)
        self.assertFalse(self.service.get_task(task["id"])["retry_allowed"])
        article = self.service.create_article({"title": "回滚整个批次", "content": "正文", "format": "text"})
        with self.assertRaises(ArticleError):
            self.service.publish(article["id"], {"revision": 1, "idempotency_key": "rollback", "targets": [
                {"platform": "zhihu", "account_id": 3, "overrides": {"title": "a" * 301}},
                {"platform": "zhihu", "account_id": 3}]})
        self.assertEqual(self.service.task_notifications()["unread"], 1)

    def test_real_worker_failure_read_restart_and_new_attempt(self):
        task = self.add_task()
        self.service.runner = lambda *args: {"status": "failed", "message": "登录失效"}
        self.assertTrue(self.service.acquire())
        self.assertTrue(self.service.run_next())
        first = self.service.task_notifications()["items"][0]
        self.assertEqual(first["attempts"], 1)
        self.service.read_task_notification(first["notification_id"])
        self.service.read_task_notification(first["notification_id"])
        self.assertEqual(self.new_service().task_notifications()["unread"], 0)
        self.assertEqual(self.service.get_task(task["id"])["status"], "failed")
        self.service.retry(task["id"])
        self.assertTrue(self.service.run_next())
        second = self.service.task_notifications()["items"][0]
        self.assertGreater(second["notification_id"], first["notification_id"])
        self.assertEqual(second["attempts"], 2)
        self.assertEqual(self.service.all_tasks({"unread": "1"})["total"], 1)
        self.service.retry(task["id"])
        self.assertEqual(self.service.task_notifications()["unread"], 0)

    def test_unknown_is_not_retryable_read_does_not_resolve_and_manual_resolution_ends_alert(self):
        task = self.add_task()
        def runner(snapshot, cookie, assets, on_submit, directory):
            on_submit()
            raise TimeoutError("平台提交后断线")
        self.service.runner = runner
        self.service.acquire()
        self.service.run_next()
        notice = self.service.task_notifications()["items"][0]
        self.assertEqual(notice["status"], "unknown")
        self.service.read_task_notification(notice["notification_id"])
        with self.assertRaises(ArticleError) as error:
            self.service.retry(task["id"])
        self.assertEqual(error.exception.status, 409)
        latest = self.service.task_notifications()["latest_id"]
        self.service.resolve(task["id"], {"resolution": "not_published", "note": "已在平台核对，没有内容"})
        self.assertTrue(self.service.get_task(task["id"])["retry_allowed"])
        self.assertEqual(self.service.task_notifications()["latest_id"], latest)
        self.assertEqual(self.service.task_notifications()["unread"], 0)

    def test_read_all_boundary_does_not_consume_concurrent_new_alert(self):
        first = self.add_task("第一条异常文章")
        self.set_status(first, "failed")
        observed = self.service.task_notifications()["latest_id"]
        second = self.add_task("并发新产生的文章")
        self.set_status(second, "needs_action")
        self.assertEqual(self.service.read_task_notifications({"through_id": observed})["read"], 1)
        remaining = self.service.task_notifications()
        self.assertEqual(remaining["unread"], 1)
        self.assertEqual(remaining["items"][0]["id"], second["id"])
        self.assertEqual(self.service.read_task_notifications({"through_id": observed})["read"], 0)
        self.assertEqual(self.service.get_task(first["id"])["status"], "failed")

    def test_notifications_pagination_and_concurrent_acknowledgement(self):
        for n in range(3):
            self.set_status(self.add_task(f"异常文章测试{n}"), "failed")
        data = self.service.task_notifications(page=2, page_size=1)
        self.assertEqual(data["unread"], 3)
        self.assertEqual(len(data["items"]), 1)
        identifier = data["items"][0]["notification_id"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(self.service.read_task_notification, [identifier, identifier]))
        self.assertEqual(self.service.task_notifications()["unread"], 2)

    def test_restart_recovery_generates_both_before_and_after_submit_alerts(self):
        before, after = self.add_task("提交前被中断"), self.add_task("提交后被中断")
        self.set_status(before, "running", stage="preparing")
        self.set_status(after, "running", stage="submitting", submit_started=1)
        self.service.acquire()
        results = {item["id"]: item for item in self.service.task_notifications()["items"]}
        self.assertEqual(results[before["id"]]["status"], "failed")
        self.assertTrue(results[before["id"]]["retry_allowed"])
        self.assertEqual(results[after["id"]]["status"], "unknown")
        self.assertFalse(results[after["id"]]["retry_allowed"])
        self.service.acquire()
        self.assertEqual(self.service.task_notifications()["unread"], 2)

    def test_api_legacy_pending_global_details_and_reminders_do_not_submit(self):
        pending = self.add_task(schedule=schedule())
        failed = self.add_task("失败任务标题")
        self.set_status(failed, "failed")
        client = self.client()
        self.assertEqual(client.get("/api/article-publish-tasks").json["data"]["total"], 1)
        result = client.get("/api/article-publish-tasks?scope=all&status=attention&page_size=1")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["data"]["items"][0]["id"], failed["id"])
        detail = client.get(f"/api/article-publish-tasks/{pending['id']}").json["data"]
        self.assertTrue(detail["reschedule_allowed"])
        notice = client.get("/api/article-task-notifications").json["data"]["items"][0]
        self.assertEqual(client.post(f"/api/article-task-notifications/{notice['notification_id']}/read", json={}).status_code, 200)
        self.assertEqual(client.get("/api/article-task-notifications").json["data"]["unread"], 0)
        self.assertEqual(client.get("/api/article-publish-tasks?scope=bogus").status_code, 400)
        self.assertEqual(client.get("/api/article-publish-tasks/missing").status_code, 404)
        self.assertEqual(client.post("/api/article-task-notifications/999/read", json={}).status_code, 404)
        self.assertEqual(client.post("/api/article-task-notifications/read", json={"through_id": True}).status_code, 400)
        self.assertEqual(client.post("/api/article-task-notifications/read", json={"through_id": notice["notification_id"] + 1}).status_code, 400)
        self.assertEqual(self.calls, [])

    def test_upgrade_backfills_titles_and_only_once_alerts_without_rewriting_tasks(self):
        path = self.base / "legacy.sqlite"
        with sqlite3.connect(path) as conn:
            conn.executescript(SCHEMA.split("CREATE TABLE IF NOT EXISTS article_task_notifications")[0])
            for n, status in enumerate(("failed", "unknown", "submitted", "failed")):
                conn.execute("""INSERT INTO article_publish_tasks
                    (id,batch_id,article_id,revision,platform,account_id,mode,snapshot_json,status,stage,message,created_at,updated_at)
                    VALUES(?,?,?,1,'zhihu',3,'publish',?,?,?,?,?,?)""",
                    (str(n), "batch", "draft", json.dumps({"title": f"旧任务{n}"}), status,
                     "resolved" if n == 3 else "finished", "old-message", self.now, self.now))
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: ArticleStore(path), range(2)))
        store = ArticleStore(path)
        with store.connect(write=True) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM article_task_notifications").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT snapshot_title FROM article_publish_tasks WHERE id='0'").fetchone()[0], "旧任务0")
            self.assertEqual(conn.execute("SELECT message FROM article_publish_tasks WHERE id='0'").fetchone()[0], "old-message")
            conn.execute("UPDATE article_task_notifications SET read_at=?", (self.now,))
        ArticleStore(path)
        with store.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM article_task_notifications WHERE read_at IS NULL").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()

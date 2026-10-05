"""真实 SQLite/API 与受控时钟验证排期，所有平台提交均用替身。"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from tests.test_articles import image_bytes
from utils.articles.model import ArticleError
from utils.articles.model import capabilities
from utils.articles.platforms import PLATFORMS, NOTE_PLATFORMS
from utils.account_bindings import bind_account
from utils.articles.routes import register_article_routes
from utils.articles.scheduling import normalize_schedule
from utils.articles.service import ArticleService
from utils.articles.store import ArticleStore, SCHEMA


def schedule(at="2030-01-02T10:00:00", zone="Asia/Shanghai"):
    return {"publish_at": at, "timezone": zone}


class ScheduleTimeTests(unittest.TestCase):
    def test_timezone_conversion_and_explicit_offset(self):
        for value in (schedule(), schedule("2030-01-02T10:00:00+08:00"), schedule("2030-01-02T02:00:00Z", "UTC")):
            with self.subTest(value=value):
                self.assertEqual(normalize_schedule(value)[0], "2030-01-02T02:00:00.000000+00:00")

    def test_malformed_dates_zones_and_dst_are_rejected(self):
        cases = [False, True, "2030-01-01", {}, {"publish_at": "2030-01-01"},
                 schedule("2030-01-02"), schedule("2030-02-30T12:00:00"), schedule(zone="Not/AZone"),
                 schedule(zone="/etc/passwd"), schedule("2030-01-02T10:00:00Z"),
                 schedule("2030-03-10T02:30:00", "America/New_York"),
                 schedule("2030-11-03T01:30:00", "America/New_York")]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ArticleError):
                normalize_schedule(value)
        first = normalize_schedule(schedule("2030-11-03T01:30:00-04:00", "America/New_York"))[0]
        second = normalize_schedule(schedule("2030-11-03T01:30:00-05:00", "America/New_York"))[0]
        self.assertEqual(first, "2030-11-03T05:30:00.000000+00:00")
        self.assertEqual(second, "2030-11-03T06:30:00.000000+00:00")

    def test_windows_fallback_uses_declared_tzdata(self):
        # 没有系统 zoneinfo 文件时仍可从公开依赖读取时区，模拟 Windows 安装。
        import zoneinfo
        previous = zoneinfo.TZPATH
        try:
            zoneinfo.reset_tzpath(())
            with patch("utils.articles.scheduling.ZoneInfo", side_effect=zoneinfo.ZoneInfo.no_cache):
                self.assertEqual(normalize_schedule(schedule())[0], "2030-01-02T02:00:00.000000+00:00")
        finally:
            zoneinfo.reset_tzpath(previous)


class SchedulingFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.cookies = self.base / "cookies"
        self.cookies.mkdir()
        for identifier in (1, 2, 3):
            (self.cookies / f"{identifier}.json").write_text('{"cookies":[],"origins":[]}', encoding="utf-8")
        self.now = "2030-01-01T00:00:00.000000+00:00"
        self.clock = patch("utils.articles.service.utc_now", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.calls = []

        def runner(snapshot, cookie, assets, on_submit, directory):
            self.calls.append((snapshot, cookie, assets))
            on_submit()
            return {"status": "submitted", "platform_id": "mock-content-id"}

        self.runner = runner
        self.service = self.new_service()
        with self.service.store.connect(write=True) as conn:
            conn.execute("CREATE TABLE user_info(id INTEGER PRIMARY KEY,type INTEGER,filePath TEXT,userName TEXT,status INTEGER)")
            conn.executemany("INSERT INTO user_info VALUES (?,?,?,?,?)", [
                (1, 3, "1.json", "抖音甲", 1), (2, 3, "2.json", "抖音乙", 1), (3, 9, "3.json", "知乎", 1)])
        self.cover = self.service.assets.save(image_bytes((640, 640)), "封面.png")
        self.article = self.service.create_article({"title": "定时发布测试文章", "format": "text",
                                                    "content": "排期时的正文", "cover_asset_id": self.cover["id"]})

    def new_service(self):
        return ArticleService(self.base / "db.sqlite", self.base / "assets", self.cookies,
                              self.base / "evidence", runner=self.runner)

    def publish(self, targets=None, key="schedule-key", **kwargs):
        return self.service.publish(self.article["id"], {
            "revision": self.article["revision"], "idempotency_key": key,
            "targets": targets or [{"platform": "douyin", "account_id": 1, "schedule": schedule()}], **kwargs})

    def task(self, batch):
        return self.service.get_batch(batch["id"])["tasks"][0]


class ArticleSchedulingTests(SchedulingFixture, unittest.TestCase):
    def test_per_account_due_time_no_early_run_and_no_head_of_line_block(self):
        batch = self.publish([
            {"platform": "douyin", "account_id": 1, "schedule": schedule()},
            {"platform": "douyin", "account_id": 2, "schedule": schedule("2030-01-03T10:00:00")},
            {"platform": "zhihu", "account_id": 3}])
        self.assertEqual({t["account_id"]: t["status"] for t in batch["tasks"]}, {1: "scheduled", 2: "scheduled", 3: "queued"})
        self.assertTrue(self.service.acquire())
        self.assertTrue(self.service.run_next())
        self.assertEqual(self.calls[0][1].name, "3.json")
        self.assertFalse(self.service.run_next())
        self.now = "2030-01-02T02:00:00.000000+00:00"
        self.assertTrue(self.service.run_next())
        self.assertEqual(self.calls[1][1].name, "1.json")
        self.assertFalse(self.service.run_next())
        self.now = "2030-01-03T02:00:00.000000+00:00"
        self.assertTrue(self.service.run_next())
        self.assertEqual(self.calls[2][1].name, "2.json")
        self.assertFalse(self.service.run_next())
        self.assertTrue(all(t["attempts"] == 1 for t in self.service.get_batch(batch["id"])["tasks"]))

    def test_shared_schedule_can_be_overridden_by_immediate_target(self):
        batch = self.publish([{"platform": "douyin", "account_id": 1},
                              {"platform": "douyin", "account_id": 2, "schedule": None}], schedule=schedule())
        tasks = {t["account_id"]: t for t in batch["tasks"]}
        self.assertEqual(tasks[1]["status"], "scheduled")
        self.assertEqual(tasks[2]["status"], "queued")
        self.assertIsNone(tasks[2]["scheduled_at"])

    def test_reject_invalid_schedule_preview_and_unsupported_platform_without_enqueuing(self):
        for targets, extra in [
            ([{"platform": "douyin", "account_id": 1, "schedule": schedule("2029-12-31T12:00:00")}], {}),
            ([{"platform": "douyin", "account_id": 1, "schedule": {}}], {}),
            ([{"platform": "douyin", "account_id": 1, "schedule": False}], {}),
            ([{"platform": "douyin", "account_id": 1, "schedule": schedule()}], {"mode": "preview"}),
            ([{"platform": "unknown", "account_id": 3, "schedule": schedule()}, {"platform": "douyin", "account_id": 1}], {}),
            ([{"platform": ["zhihu"], "account_id": 3, "schedule": schedule()}], {}),
            ([{"platform": "douyin", "account_id": 1}], {"enableTimer": True}),
            ([{"platform": "douyin", "account_id": 1, "schedule": None}], {"schedule": False}),
            ([{"platform": "douyin", "account_id": 1, "schedule": None}], {"schedule": {}}),
            ([{"platform": "douyin", "account_id": 1, "schedule": None}], {"mode": "preview", "schedule": schedule()}),
        ]:
            with self.subTest(targets=targets, extra=extra), self.assertRaises(ArticleError):
                self.publish(targets, **extra)
        self.assertEqual(self.service.batches(), [])
        self.assertEqual(self.service.pending_tasks()["total"], 0)

    def test_unavailable_platform_rejects_scheduling_but_pending_task_can_be_cancelled(self):
        batch = self.publish([{"platform": "zhihu", "account_id": 3, "schedule": schedule()}])
        task = self.task(batch)
        with patch.dict(PLATFORMS["zhihu"], {"available": False, "reason": "平台暂时停用"}):
            capability = next(item for item in capabilities() if item["platform"] == "zhihu")
            self.assertFalse(capability["scheduled"])
            self.assertIsNone(capability["schedule_mode"])
            with self.assertRaises(ArticleError):
                self.publish([{"platform": "zhihu", "account_id": 3, "schedule": schedule()},
                              {"platform": "douyin", "account_id": 1}], key="unavailable")
            with self.assertRaises(ArticleError):
                self.service.change_schedule(task["id"], {"schedule": schedule("2030-01-03T10:00:00"),
                                                          "expected_schedule_revision": 0})
            cancelled = self.service.change_schedule(task["id"], {"expected_schedule_revision": 0}, cancel=True)
            self.assertEqual(cancelled["tasks"][0]["status"], "cancelled")
        self.assertEqual(len(self.service.batches()), 1)

    def test_idempotent_replay_after_due_and_reschedule_preserves_original_identity(self):
        batch = self.publish()
        task = self.task(batch)
        changed = self.service.change_schedule(task["id"], {"schedule": schedule("2030-01-03T10:00:00"),
                                                            "expected_schedule_revision": 0})
        self.assertEqual(changed["tasks"][0]["schedule_revision"], 1)
        self.now = "2030-01-02T12:00:00.000000+00:00"
        replay = self.publish()
        self.assertEqual(replay["id"], batch["id"])
        self.assertEqual(replay["tasks"][0]["scheduled_at"], "2030-01-03T02:00:00.000000+00:00")
        self.assertTrue(self.service.acquire())
        self.assertFalse(self.service.run_next())
        with self.assertRaises(ArticleError) as conflict:
            self.publish(key="new-key", schedule=schedule("2030-01-04T10:00:00"))
        self.assertEqual(conflict.exception.status, 400)  # target 的原排期已过期，禁止新请求立即执行。
        with self.assertRaises(ArticleError) as conflict:
            self.publish([{ "platform": "douyin", "account_id": 1, "schedule": schedule("2030-01-04T10:00:00") }])
        self.assertEqual(conflict.exception.status, 409)

    def test_scheduled_tasks_block_duplicate_immediate_publication(self):
        self.publish()
        with self.assertRaises(ArticleError) as conflict:
            self.publish([{"platform": "douyin", "account_id": 1}], key="different-key")
        self.assertEqual(conflict.exception.status, 409)

    def test_exact_current_time_without_fraction_is_not_future(self):
        self.now = "2030-01-02T02:00:00+00:00"
        with self.assertRaises(ArticleError):
            self.publish()
        self.assertEqual(self.service.pending_tasks()["total"], 0)

    def test_restart_and_edited_draft_keep_snapshot_and_submit_once(self):
        batch = self.publish()
        self.service.update_article(self.article["id"], {"expected_revision": 1, "title": "后续修订", "content": "后续正文"})
        with self.assertRaises(ArticleError):
            self.service.assets.delete(self.cover["id"])
        restarted = self.new_service()
        self.assertTrue(restarted.acquire())
        self.assertFalse(restarted.run_next())
        self.now = "2030-01-04T00:00:00.000000+00:00"  # 停机错过发布时间，恢复后仍按原排期执行。
        self.assertTrue(restarted.run_next())
        self.assertFalse(restarted.run_next())
        self.assertEqual(len(self.calls), 1)
        snapshot = self.calls[0][0]
        self.assertEqual(snapshot["title"], "定时发布测试文章")
        self.assertIn("排期时的正文", snapshot["content_html"])
        self.assertNotIn("schedule", snapshot)
        self.assertEqual(self.task(batch)["status"], "submitted")

    def test_reschedule_cancel_versions_and_cancelled_republish(self):
        batch = self.publish()
        task = self.task(batch)
        with self.assertRaises(ArticleError):
            self.service.change_schedule(task["id"], {"schedule": schedule("2029-12-31T10:00:00"), "expected_schedule_revision": 0})
        self.service.change_schedule(task["id"], {"schedule": schedule("2030-01-04T10:00:00"), "expected_schedule_revision": 0})
        with self.assertRaises(ArticleError) as stale:
            self.service.change_schedule(task["id"], {"expected_schedule_revision": 0}, cancel=True)
        self.assertEqual(stale.exception.status, 409)
        cancelled = self.service.change_schedule(task["id"], {"expected_schedule_revision": 1}, cancel=True)["tasks"][0]
        self.assertEqual((cancelled["status"], cancelled["attempts"], cancelled["schedule_revision"]), ("cancelled", 0, 2))
        self.assertFalse(cancelled["cancel_allowed"] or cancelled["reschedule_allowed"] or cancelled["retry_allowed"])
        self.assertEqual(self.service.pending_tasks()["total"], 0)
        self.now = "2030-01-05T00:00:00.000000+00:00"
        self.assertTrue(self.service.acquire())
        self.assertFalse(self.service.run_next())
        fresh = self.publish([{"platform": "douyin", "account_id": 1}], key="new-explicit-publication")
        self.assertEqual(fresh["tasks"][0]["status"], "queued")

    def test_missing_session_at_due_fails_before_submission_and_allows_safe_retry(self):
        batch = self.publish()
        (self.cookies / "1.json").unlink()
        self.now = "2030-01-02T02:00:00.000000+00:00"
        self.assertTrue(self.service.acquire())
        self.assertTrue(self.service.run_next())
        task = self.task(batch)
        self.assertEqual(task["status"], "failed")
        self.assertTrue(task["retry_allowed"])
        self.assertEqual(self.calls, [])
        (self.cookies / "1.json").write_text('{"cookies":[],"origins":[]}', encoding="utf-8")
        self.service.retry(task["id"])
        self.assertTrue(self.service.run_next())
        self.assertEqual(self.task(batch)["status"], "submitted")

    def test_unknown_submission_never_retries_or_reschedules(self):
        batch = self.publish()
        def uncertain(snapshot, cookie, assets, on_submit, directory):
            on_submit()
            raise RuntimeError("提交之后断线")
        self.service.runner = uncertain
        self.now = "2030-01-02T02:00:00.000000+00:00"
        self.assertTrue(self.service.acquire())
        self.assertTrue(self.service.run_next())
        task = self.task(batch)
        self.assertEqual(task["status"], "unknown")
        self.assertFalse(task["retry_allowed"] or task["cancel_allowed"] or task["reschedule_allowed"])
        with self.assertRaises(ArticleError):
            self.service.retry(task["id"])
        for cancel in (True, False):
            with self.assertRaises(ArticleError):
                self.service.change_schedule(task["id"], {"schedule": schedule("2030-01-04T10:00:00"),
                                                            "expected_schedule_revision": 0}, cancel=cancel)
        self.assertFalse(self.service.run_next())

    def test_worker_claim_wins_over_cancel_and_reschedule(self):
        batch = self.publish()
        task = self.task(batch)
        claimed, release = threading.Event(), threading.Event()
        def blocking(snapshot, cookie, assets, on_submit, directory):
            claimed.set()
            if not release.wait(5):
                raise RuntimeError("测试未释放执行器")
            return self.runner(snapshot, cookie, assets, on_submit, directory)
        self.service.runner = blocking
        self.now = "2030-01-02T02:00:00.000000+00:00"
        self.assertTrue(self.service.acquire())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.service.run_next)
            try:
                self.assertTrue(claimed.wait(5))
                for cancel in (True, False):
                    with self.assertRaises(ArticleError) as conflict:
                        self.service.change_schedule(task["id"], {"expected_schedule_revision": 0,
                                                                 "schedule": schedule("2030-01-04T10:00:00")}, cancel=cancel)
                    self.assertEqual(conflict.exception.status, 409)
            finally:
                release.set()
            self.assertTrue(future.result(timeout=5))
        self.assertEqual(len(self.calls), 1)

    def test_cancel_first_prevents_worker_and_second_worker_cannot_submit(self):
        batch = self.publish()
        self.service.change_schedule(self.task(batch)["id"], {"expected_schedule_revision": 0}, cancel=True)
        self.now = "2030-01-02T02:00:00.000000+00:00"
        self.assertTrue(self.service.acquire())
        other = self.new_service()
        self.assertFalse(other.acquire())
        self.assertFalse(other.run_next())
        self.assertFalse(self.service.run_next())
        self.assertEqual(self.calls, [])

    def test_pending_pagination_and_no_session_or_snapshot_exposure(self):
        batch = self.publish([{ "platform": "douyin", "account_id": 1, "schedule": schedule("2030-01-03T10:00:00") },
                              { "platform": "douyin", "account_id": 2, "schedule": schedule() },
                              { "platform": "zhihu", "account_id": 3 }])
        pages = [self.service.pending_tasks(i, 1) for i in range(1, 4)]
        self.assertEqual([p["items"][0]["account_id"] for p in pages], [3, 2, 1])
        self.assertTrue(all(p["total"] == 3 for p in pages))
        for task in pages[0]["items"]:
            self.assertNotIn("snapshot_json", task)
            self.assertNotIn("cookie", json.dumps(task))
            self.assertEqual(task["title"], "定时发布测试文章")
        self.assertEqual(self.service.pending_tasks(4, 1)["items"], [])

    def test_schedule_api_routes_and_errors(self):
        app = Flask(__name__)
        app.config.update(ARTICLE_WORKER_ENABLED=False, ARTICLE_DB_PATH=self.base / "db.sqlite",
                          ARTICLE_ASSET_DIR=self.base / "assets", ARTICLE_COOKIE_DIR=self.cookies)
        register_article_routes(app, SimpleNamespace(BASE_DIR=self.base))
        client = app.test_client()
        response = client.post(f'/api/articles/{self.article["id"]}/publish', json={
            "revision": 1, "idempotency_key": "api-schedule", "schedule": schedule(),
            "targets": [{"platform": "zhihu", "account_id": 3}]})
        self.assertEqual(response.status_code, 200)
        task = response.json["data"]["tasks"][0]
        pending = client.get('/api/article-publish-tasks?page_size=1')
        self.assertEqual(pending.json["data"]["total"], 1)
        self.assertEqual(pending.json["data"]["items"][0]["id"], task["id"])
        changed = client.patch(f'/api/article-publish-tasks/{task["id"]}/schedule', json={
            "schedule": schedule("2030-01-03T18:00:00", "Asia/Tokyo"), "expected_schedule_revision": 0})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json["data"]["tasks"][0]["scheduled_at"], "2030-01-03T09:00:00.000000+00:00")
        url = f'/api/article-publish-tasks/{task["id"]}/cancel'
        self.assertEqual(client.post(url, json={}).status_code, 400)
        self.assertEqual(client.post(url, json={"expected_schedule_revision": False}).status_code, 400)
        self.assertEqual(client.post(url, json={"expected_schedule_revision": 0}).status_code, 409)
        self.assertEqual(client.post(url, json={"expected_schedule_revision": 1}).status_code, 200)
        self.assertEqual(client.get('/api/article-publish-tasks').json["data"]["total"], 0)
        for params in ('page=no', 'page=0', 'page_size=101', 'page=999999999999999999999999999'):
            self.assertEqual(client.get('/api/article-publish-tasks?' + params).status_code, 400)


class MultiPlatformSchedulingTests(SchedulingFixture, unittest.TestCase):
    """每个平台使用独立账号、真实素材校验和真实执行器工厂，仅替换浏览器提交。"""

    def setUp(self):
        super().setUp()
        self.square = self.service.assets.save(image_bytes((800, 800), "white"), "正文首图.png")
        self.second = self.service.assets.save(image_bytes((800, 800), "yellow"), "正文第二图.png")
        self.horizontal = self.service.assets.save(image_bytes((800, 600), "red"), "横版封面.png")
        self.vertical = self.service.assets.save(image_bytes((600, 800), "green"), "竖版封面.png")
        self.jingdong_cover = self.service.assets.save(image_bytes((700, 490), "blue"), "京东独立封面.png")
        self.yiche_cover = self.service.assets.save(image_bytes((720, 480), "purple"), "易车封面.png")
        self.article = self.service.create_article({
            "title": "跨平台文章定时发布功能验证标题", "format": "html", "cover_asset_id": self.square["id"],
            "content": f'<p>排期时冻结的完整正文需要保留文字和两张有序图片。</p><img src="{self.square["url"]}"><img src="{self.second["url"]}">',
        })
        self.targets = []
        with self.service.store.connect(write=True) as conn:
            for index, (platform, rules) in enumerate(PLATFORMS.items()):
                account_id = 100 + rules["account_type"]
                filename = f"{platform}.json"
                (self.cookies / filename).write_text('{"cookies":[],"origins":[]}', encoding="utf-8")
                conn.execute("INSERT INTO user_info VALUES (?,?,?,?,?)", (account_id, rules["account_type"], filename, platform, 1))
                bind_account(conn, account_id, platform, source="test-fixture")
                options = {"flatten_content": True} if platform in NOTE_PLATFORMS else {}
                if platform == "acfun":
                    options.update(category="生活", summary="排期测试摘要", original=True)
                elif platform == "csdn":
                    options.update(summary="排期测试摘要", create_type="原创")
                elif platform == "jd":
                    options["product_links"] = "https://item.jd.com/12345678.html"
                elif platform == "xiaohongshu_merchant":
                    options.update(shop_name="隔离测试店铺", product_id="12345678")
                elif platform == "taobao":
                    options["statement"] = "内容无需标注"
                elif platform == "wechat":
                    options.update(author="测试作者", summary="公众号排期摘要")
                if platform in {"chejiahao", "yiche", "dongchedi"}:
                    options["vertical_cover_asset_id"] = self.vertical["id"]
                if platform == "chejiahao":
                    options.update(original=False, first_publish=False, agree_upload_terms=True)
                elif platform == "yiche":
                    options.update(declaration="内容无需标注", allow_forward=False, allow_abstract=False)
                overrides = {"options": options, "tags": ["测试"] if platform == "csdn" else []}
                if platform == "jingdong":
                    overrides["cover_asset_id"] = self.jingdong_cover["id"]
                elif platform in {"chejiahao", "dongchedi"}:
                    overrides["cover_asset_id"] = self.horizontal["id"]
                elif platform == "yiche":
                    overrides["cover_asset_id"] = self.yiche_cover["id"]
                self.targets.append({"platform": platform, "account_id": account_id, "overrides": overrides,
                                     "schedule": schedule() if index % 2 == 0 else schedule("2030-01-02T13:00:00", "Asia/Tokyo")})

    def frozen_snapshots(self, batch):
        with self.service.store.connect() as conn:
            return {row["platform"]: row["snapshot_json"] for row in conn.execute(
                "SELECT platform,snapshot_json FROM article_publish_tasks WHERE batch_id=?", (batch["id"],))}

    def test_all_twenty_eight_platforms_freeze_content_and_dispatch_only_when_due(self):
        from utils.articles.adapter import create_adapter, validate_task
        from utils.articles.notes import prepare_note_document

        batch = self.publish(self.targets)
        self.assertEqual(len(batch["tasks"]), 28)
        expected = {target["platform"]: target for target in self.targets}
        for task in batch["tasks"]:
            self.assertEqual((task["status"], task["attempts"]), ("scheduled", 0), task)
            self.assertTrue(task["reschedule_allowed"] and task["cancel_allowed"], task)
        snapshots = self.frozen_snapshots(batch)
        self.service.update_article(self.article["id"], {"expected_revision": 1, "title": "后续修订", "content": "此正文不应用到原排期"})

        def dispatched(snapshot, cookie, assets, on_submit, directory):
            platform = snapshot["platform"]
            self.assertEqual(snapshot, json.loads(snapshots[platform]))
            self.assertEqual(snapshot["options"], expected[platform]["overrides"]["options"])
            self.assertEqual(snapshot["tags"], expected[platform]["overrides"]["tags"])
            self.assertEqual(cookie.name, platform + ".json")
            self.assertNotIn("schedule", snapshot)
            self.assertNotIn("publish_date", snapshot)
            self.assertEqual(snapshot["mode"], "publish")
            cover = validate_task(snapshot, assets)
            self.assertEqual(create_adapter(snapshot, cookie, cover).platform, platform)
            if platform in NOTE_PLATFORMS:
                document = prepare_note_document(snapshot, assets)
                self.assertEqual(document.image_paths, [Path(assets[self.square["id"]]["path"]),
                                                        Path(assets[self.second["id"]]["path"])])
            if platform in {"chejiahao", "yiche", "dongchedi"}:
                self.assertIn(self.vertical["id"], assets)
            return self.runner(snapshot, cookie, assets, on_submit, directory)

        self.service.runner = dispatched
        self.assertTrue(self.service.acquire())
        self.assertFalse(self.service.run_next())
        self.now = "2030-01-02T02:00:00.000000+00:00"
        while self.service.run_next():
            pass
        self.assertEqual({call[0]["platform"] for call in self.calls},
                         {target["platform"] for target in self.targets[::2]})
        self.now = "2030-01-02T04:00:00.000000+00:00"
        while self.service.run_next():
            pass
        tasks = self.service.get_batch(batch["id"])["tasks"]
        self.assertEqual({call[0]["platform"] for call in self.calls}, set(PLATFORMS))
        self.assertEqual(len(self.calls), 28)
        for task in tasks:
            self.assertEqual((task["status"], task["attempts"], task["submit_started"]), ("submitted", 1, 1), task)
        self.assertEqual(self.publish(self.targets)["id"], batch["id"])
        self.assertFalse(self.service.run_next())

    def test_all_platforms_reschedule_and_cancel_without_changing_frozen_content(self):
        batch = self.publish(self.targets)
        snapshots = self.frozen_snapshots(batch)
        for task in batch["tasks"]:
            with self.subTest(platform=task["platform"]):
                changed = self.service.change_schedule(task["id"], {
                    "expected_schedule_revision": 0, "schedule": schedule("2030-01-03T12:00:00", "UTC")})
                current = next(item for item in changed["tasks"] if item["id"] == task["id"])
                self.assertEqual(current["scheduled_at"], "2030-01-03T12:00:00.000000+00:00")
                self.assertEqual(current["schedule_timezone"], "UTC")
                with self.assertRaises(ArticleError) as stale:
                    self.service.change_schedule(task["id"], {"expected_schedule_revision": 0}, cancel=True)
                self.assertEqual(stale.exception.status, 409)
                self.service.change_schedule(task["id"], {"expected_schedule_revision": 1}, cancel=True)
        self.assertEqual(self.frozen_snapshots(batch), snapshots)
        tasks = self.service.get_batch(batch["id"])["tasks"]
        self.assertTrue(all(task["status"] == "cancelled" and task["attempts"] == 0 for task in tasks))
        self.assertEqual(self.service.pending_tasks()["total"], 0)
        self.now = "2030-01-04T00:00:00.000000+00:00"
        self.assertTrue(self.service.acquire())
        self.assertFalse(self.service.run_next())
        self.assertEqual(self.calls, [])

    def test_multi_platform_failure_and_unknown_result_do_not_block_other_accounts_or_repeat(self):
        batch = self.publish(self.targets)
        def mixed_results(snapshot, cookie, assets, on_submit, directory):
            platform = snapshot["platform"]
            if platform == "xiaohongshu":
                return {"status": "failed", "message": "模拟提交前失败"}
            if platform == "wechat":
                return {"status": "needs_action", "message": "模拟需要管理员确认"}
            if platform == "weibo":
                on_submit()
                raise RuntimeError("模拟提交后连接中断")
            return self.runner(snapshot, cookie, assets, on_submit, directory)
        self.service.runner = mixed_results
        self.now = "2030-01-02T04:00:00.000000+00:00"
        self.assertTrue(self.service.acquire())
        while self.service.run_next():
            pass
        tasks = {task["platform"]: task for task in self.service.get_batch(batch["id"])["tasks"]}
        self.assertEqual(tasks["xiaohongshu"]["status"], "failed")
        self.assertEqual(tasks["wechat"]["status"], "needs_action")
        self.assertEqual(tasks["weibo"]["status"], "unknown")
        self.assertEqual(sum(task["status"] == "submitted" for task in tasks.values()), 25)
        unknown = tasks["weibo"]
        self.assertFalse(unknown["retry_allowed"] or unknown["cancel_allowed"] or unknown["reschedule_allowed"])
        with self.assertRaises(ArticleError):
            self.service.retry(unknown["id"])
        with self.assertRaises(ArticleError):
            self.service.change_schedule(unknown["id"], {"expected_schedule_revision": 0,
                                                         "schedule": schedule("2030-01-03T10:00:00")})
        self.service.retry(tasks["xiaohongshu"]["id"])
        self.service.runner = self.runner
        self.assertTrue(self.service.run_next())
        self.assertFalse(self.service.run_next())
        tasks = {task["platform"]: task for task in self.service.get_batch(batch["id"])["tasks"]}
        self.assertEqual((tasks["xiaohongshu"]["status"], tasks["xiaohongshu"]["attempts"]), ("submitted", 2))
        self.assertTrue(all(task["attempts"] == 1 for platform, task in tasks.items() if platform != "xiaohongshu"))


class ScheduleMigrationTests(unittest.TestCase):
    def test_existing_database_and_repeated_initialization_preserve_old_tasks(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "old.sqlite"
            with sqlite3.connect(db) as conn:
                conn.executescript(SCHEMA)
                conn.execute("""INSERT INTO article_publish_tasks
                    (id,batch_id,article_id,revision,platform,account_id,mode,snapshot_json,status,created_at,updated_at)
                    VALUES ('old','batch','article',1,'douyin',1,'publish','{}','queued','2029-01-01','2029-01-01')""")
            ArticleStore(db)
            store = ArticleStore(db)
            with store.connect() as conn:
                row = conn.execute("SELECT * FROM article_publish_tasks WHERE id='old'").fetchone()
            self.assertEqual(row["status"], "queued")
            self.assertEqual(row["snapshot_json"], "{}")
            self.assertIsNone(row["scheduled_at"])
            self.assertEqual(row["schedule_timezone"], "")
            self.assertEqual(row["schedule_revision"], 0)


if __name__ == '__main__':
    unittest.main()

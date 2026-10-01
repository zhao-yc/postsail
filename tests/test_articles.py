"""文章 API、快照、重复保护和服务恢复的隔离验收。"""
from __future__ import annotations

import io
import json
import shutil
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from flask import Flask
from PIL import Image

from utils.articles.assets import ArticleAssets, download_image, public_url
from utils.articles.model import ArticleError, clean_content
from utils.articles.routes import register_article_routes
from utils.articles.service import ArticleService


def image_bytes():
    """生成本地测试图片，不使用真实账号或官网素材。"""
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), "white").save(buffer, "PNG")
    return buffer.getvalue()


class ArticlesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.cookies = self.base / "cookiesFile"
        self.cookies.mkdir()
        for name in ("a.json", "b.json"):
            (self.cookies / name).write_text('{"cookies":[],"origins":[]}', encoding="utf-8")
        self.service = ArticleService(self.base / "db.sqlite", self.base / "assets", self.cookies, self.base / "evidence")
        with self.service.store.connect(write=True) as conn:
            conn.execute("CREATE TABLE user_info(id INTEGER PRIMARY KEY,type INTEGER,filePath TEXT,userName TEXT,status INTEGER)")
            conn.executemany("INSERT INTO user_info VALUES (?,?,?,?,?)",
                             [(1, 9, "a.json", "知乎测试账号", 1), (2, 7, "b.json", "头条测试账号", 1)])
        self.article = self.service.create_article({"title": "多平台测试文章", "format": "markdown",
                                                   "content": "## 二级标题\n\n包含 **加粗** 的正文。"})

    def tearDown(self):
        self.service.stop_event.set()
        self.tmp.cleanup()

    def publish(self, key="测试请求", targets=None, mode="publish"):
        return self.service.publish(self.article["id"], {"revision": self.article["revision"], "mode": mode,
                                    "idempotency_key": key, "targets": targets or [{"platform": "zhihu", "account_id": 1}]})

    def test_normalize_and_revision_conflict(self):
        """脚本清理、Markdown 语义和修订锁共同保护原稿。"""
        content = clean_content('<p onclick="x()">正文<script>alert(1)</script><a href="javascript:evil()">链接</a></p>', "html")
        self.assertNotIn("script", content)
        self.assertNotIn("onclick", content)
        self.assertNotIn("javascript", content)
        self.assertIn("<h2>", self.article["content_html"])
        updated = self.service.update_article(self.article["id"], {"expected_revision": 1, "title": "新的文章标题"})
        self.assertEqual(updated["revision"], 2)
        with self.assertRaises(ArticleError) as ctx:
            self.service.update_article(self.article["id"], {"expected_revision": 1, "title": "过期修改"})
        self.assertEqual(ctx.exception.status, 409)

    def test_assets_snapshot_protection_and_paths(self):
        """修订后的原稿解除引用也不能删除旧发布快照中的图片。"""
        asset = self.service.assets.save(image_bytes(), "测试.png")
        self.article = self.service.update_article(self.article["id"], {"expected_revision": 1,
            "content": f'<p>带图片的正文<img src="{asset["url"]}"></p>', "format": "html"})
        self.assertIn('data-asset-id=', self.article["content_html"])
        batch = self.publish()
        self.service.update_article(self.article["id"], {"expected_revision": 2, "content": "移除图片的原稿", "format": "text"})
        with self.assertRaises(ArticleError):
            self.service.assets.delete(asset["id"])
        with self.service.store.connect() as conn:
            snapshot = json.loads(conn.execute("SELECT snapshot_json FROM article_publish_tasks WHERE batch_id=?", (batch["id"],)).fetchone()[0])
        self.assertIn(asset["id"], snapshot["content_html"])
        with self.assertRaises(ArticleError):
            self.service.create_article({"title": "本地路径", "content": '<img src="file:///etc/passwd">'})

    def test_idempotency_concurrent_and_duplicate(self):
        """并发调用相同请求只生成一个批次；不同请求不能重复发布。"""
        with ThreadPoolExecutor(max_workers=2) as pool:
            batches = list(pool.map(lambda _: self.publish(), range(2)))
        self.assertEqual(batches[0]["id"], batches[1]["id"])
        with self.assertRaises(ArticleError):
            self.publish(key="不同请求")
        with self.assertRaises(ArticleError):
            self.publish(targets=[{"platform": "toutiao", "account_id": 2}])

    def test_platform_failure_isolated_and_no_truncation(self):
        """标题约束按目标记录失败，其他有效目标仍进入队列。"""
        batch = self.publish(targets=[{"platform": "zhihu", "account_id": 1},
                                      {"platform": "toutiao", "account_id": 2,
                                       "overrides": {"title": "长" * 31}}])
        by_platform = {t["platform"]: t for t in batch["tasks"]}
        self.assertEqual(by_platform["zhihu"]["status"], "queued")
        self.assertEqual(by_platform["toutiao"]["status"], "failed")
        self.assertIn("标题", by_platform["toutiao"]["message"])
        self.assertFalse(by_platform["toutiao"]["retry_allowed"])

    def test_submit_exception_unknown_and_manual_resolve(self):
        """提交后网络失败不能重发；人工确认未发表后才允许重试。"""
        def fail_after_submit(snapshot, cookie, assets, on_submit, directory):
            on_submit()
            raise RuntimeError("提交后断线")
        self.service.runner = fail_after_submit
        batch = self.publish()
        self.service.acquire()
        self.service.run_next()
        task = self.service.get_batch(batch["id"])["tasks"][0]
        self.assertEqual(task["status"], "unknown")
        with self.assertRaises(ArticleError):
            self.service.retry(task["id"])
        batch = self.service.resolve(task["id"], {"resolution": "not_published", "note": "已核查平台内容列表，没有该文章"})
        self.assertTrue(batch["tasks"][0]["retry_allowed"])
        self.assertEqual(self.service.retry(task["id"])["tasks"][0]["status"], "queued")

    def test_preview_and_one_failed_account_do_not_stop_other(self):
        """模拟适配器验证串行隔离，并区分预览与平台受理。"""
        def run(snapshot, cookie, assets, on_submit, directory):
            if snapshot["platform"] == "zhihu":
                raise RuntimeError("提交前图片上传失败")
            if snapshot["mode"] == "preview":
                return {"status": "previewed", "message": "仅预览"}
            on_submit()
            return {"status": "submitted", "message": "平台已接收", "platform_status": "审核中"}
        self.service.runner = run
        batch = self.publish(targets=[{"platform": "zhihu", "account_id": 1}, {"platform": "toutiao", "account_id": 2}])
        self.service.acquire()
        while self.service.run_next():
            pass
        tasks = {t["platform"]: t for t in self.service.get_batch(batch["id"])["tasks"]}
        self.assertEqual(tasks["zhihu"]["status"], "failed")
        self.assertEqual(tasks["toutiao"]["status"], "submitted")
        preview = self.publish(key="预览请求", targets=[{"platform": "toutiao", "account_id": 2}], mode="preview")
        self.service.run_next()
        task = self.service.get_batch(preview["id"])["tasks"][0]
        self.assertEqual(task["status"], "previewed")
        self.assertFalse(task["submit_started"])

    def test_recovery_lease_and_database_upgrade(self):
        """新实例只接管过期租约，恢复按提交阶段分流，旧账号不变。"""
        with self.service.store.connect(write=True) as conn:
            conn.execute("CREATE TABLE file_info(id INTEGER PRIMARY KEY,filename TEXT)")
            conn.execute("INSERT INTO file_info VALUES (7,'旧视频素材.mp4')")
        batch = self.publish(targets=[{"platform": "zhihu", "account_id": 1}, {"platform": "toutiao", "account_id": 2}])
        ids = [t["id"] for t in batch["tasks"]]
        self.service.acquire()
        with self.service.store.connect(write=True) as conn:
            conn.execute("UPDATE article_publish_tasks SET status='running' WHERE batch_id=?", (batch["id"],))
            conn.execute("UPDATE article_publish_tasks SET submit_started=1 WHERE id=?", (ids[0],))
        other = ArticleService(self.base / "db.sqlite", self.base / "assets", self.cookies, self.base / "evidence")
        self.assertFalse(other.acquire())
        with self.service.store.connect(write=True) as conn:
            conn.execute("UPDATE article_worker_lease SET expires_at=?", (time.time()-1,))
        self.assertTrue(other.acquire())
        statuses = {t["id"]: t["status"] for t in other.get_batch(batch["id"])["tasks"]}
        self.assertEqual(statuses[ids[0]], "unknown")
        self.assertEqual(statuses[ids[1]], "failed")
        self.assertEqual(len(other.accounts()), 2)
        with other.store.connect() as conn:
            self.assertEqual(tuple(conn.execute("SELECT * FROM file_info").fetchone()), (7, "旧视频素材.mp4"))

    def test_acceptance_fixture_all_four_platforms(self):
        """真实测试稿走四平台模拟任务，验证正文图片、封面和快照，而非实际外部发布。"""
        root = Path(__file__).parent / "fixtures" / "article-acceptance"
        content = (root / "原稿.md").read_text(encoding="utf-8")
        assets = []
        for number in range(1, 4):
            asset = self.service.assets.save((root / f"image-{number}.png").read_bytes(), f"图片{number}.png")
            assets.append(asset)
            content = content.replace(f"image-{number}.png", asset["url"])
        self.article = self.service.create_article({"title": "PostSail 图文发布测试，请忽略", "content": content,
            "format": "markdown", "cover_asset_id": assets[0]["id"]})
        self.assertEqual(self.article["content_html"].count("<img"), 3)
        self.assertIn("<table", self.article["content_html"])
        self.assertIn("<pre><code", self.article["content_html"])
        with self.service.store.connect(write=True) as conn:
            conn.executemany("INSERT INTO user_info VALUES (?,?,?,?,?)", [
                (3, 5, "a.json", "百家号测试账号", 1), (4, 8, "b.json", "搜狐测试账号", 1)])
        targets = [{"platform": platform, "account_id": account} for platform, account in
                   [("zhihu", 1), ("toutiao", 2), ("baijiahao", 3), ("sohu", 4)]]
        observed = []
        def runner(snapshot, cookie, managed_assets, on_submit, directory):
            observed.append((snapshot["platform"], snapshot["mode"]))
            self.assertEqual(len(managed_assets), 3)
            self.assertEqual(snapshot["content_html"], self.article["content_html"])
            if snapshot["mode"] == "preview":
                return {"status": "previewed", "message": "模拟平台预览"}
            on_submit()
            return {"status": "submitted", "platform_status": "模拟审核中"}
        self.service.runner = runner
        self.service.acquire()
        for mode in ("preview", "publish"):
            batch = self.publish(key=f"四平台验收-{mode}", mode=mode, targets=targets)
            while self.service.run_next():
                pass
            tasks = self.service.get_batch(batch["id"])["tasks"]
            expected = "previewed" if mode == "preview" else "submitted"
            self.assertEqual([task["status"] for task in tasks], [expected] * 4)
        self.assertEqual(len(observed), 8)

    def test_schedule_explicitly_rejected(self):
        with self.assertRaises(ArticleError):
            self.service.publish(self.article["id"], {"schedule": "2030-01-01", "targets": [], "idempotency_key": "x"})
        batch = self.publish(targets=[{"platform": "zhihu", "account_id": 1,
                                      "overrides": {"publish_date": "2030-01-01"}}])
        self.assertEqual(batch["tasks"][0]["status"], "failed")
        self.assertIn("不支持定时", batch["tasks"][0]["message"])

    def test_preview_cannot_enter_submission_stage(self):
        """执行器回调在服务层限制模式，错误适配器也不能将预览变为正式提交。"""
        def broken_runner(snapshot, cookie, assets, on_submit, directory):
            on_submit()
            return {"status": "submitted"}
        self.service.runner = broken_runner
        batch = self.publish(mode="preview")
        self.service.acquire()
        self.service.run_next()
        task = self.service.get_batch(batch["id"])["tasks"][0]
        self.assertEqual(task["status"], "failed")
        self.assertFalse(task["submit_started"])
        self.assertIn("预览", task["message"])

    def test_asset_directory_migration(self):
        """数据库与素材目录整体备份后可在另一目录读取，不依赖原绝对路径。"""
        asset = self.service.assets.save(image_bytes(), "迁移.png")
        relocated = self.base / "迁移后的素材"
        shutil.copytree(self.base / "assets", relocated)
        shutil.rmtree(self.base / "assets")
        assets = ArticleAssets(self.service.store, relocated)
        self.assertEqual(Path(assets.get(asset["id"])["path"]).parent, relocated.resolve())
        self.assertEqual(Path(assets.get(asset["id"])["path"]).read_bytes(), image_bytes())
        assets.delete(asset["id"])
        self.assertEqual(list(relocated.iterdir()), [])

    def test_invalid_types_do_not_create_batches(self):
        """错误参数给出业务错误，布尔值不能冒充修订号或账号 ID。"""
        base = {"revision": 1, "targets": [{"platform": "zhihu", "account_id": 1}], "idempotency_key": "invalid"}
        for changes in ({"mode": {}}, {"revision": True}, {"targets": [{"platform": {}, "account_id": 1}]},
                        {"targets": [{"platform": "zhihu", "account_id": 0}]}):
            with self.subTest(changes=changes), self.assertRaises(ArticleError):
                self.service.publish(self.article["id"], {**base, **changes})
        self.assertEqual(self.service.batches(), [])

    def test_platform_defaults_empty_inherit_and_empty_body_rejected(self):
        """网页留空覆盖项要沿用原稿，而不是生成无封面或无话题的失败任务。"""
        asset = self.service.assets.save(image_bytes())
        self.article = self.service.update_article(self.article["id"], {
            "expected_revision": 1, "cover_asset_id": asset["id"], "tags": ["教程"],
            "platform_options": {"zhihu": {"title": None, "cover_asset_id": None, "tags": None, "options": {}}}})
        snapshot = self.service.snapshot(self.article, {"platform": "zhihu", "account_id": 1}, "publish")
        self.assertEqual(snapshot["cover_asset_id"], asset["id"])
        self.assertEqual(snapshot["tags"], ["教程"])
        with self.assertRaises(ArticleError):
            self.service.create_article({"title": "只有空段落", "content": "<p> </p>"})

    def test_retry_cannot_repeat_a_later_success(self):
        """旧失败任务不能在同修订已有新成功任务后被重新发布。"""
        first = self.publish()
        first_id = first["tasks"][0]["id"]
        with self.service.store.connect(write=True) as conn:
            conn.execute("UPDATE article_publish_tasks SET status='failed',stage='finished' WHERE id=?", (first_id,))
        second = self.publish(key="替代请求")
        with self.service.store.connect(write=True) as conn:
            conn.execute("UPDATE article_publish_tasks SET status='submitted',submit_started=1 WHERE id=?", (second["tasks"][0]["id"],))
        with self.assertRaises(ArticleError):
            self.service.retry(first_id)

    def test_legacy_article_interface_and_schedule(self):
        """旧文章入口复用网页账号，并保持响应结构和新批次关联。"""
        import sau_backend
        app = Flask(__name__)
        app.config.update(ARTICLE_WORKER_ENABLED=False, ARTICLE_DB_PATH=self.base / "db.sqlite", ARTICLE_BASE_DIR=self.base)
        register_article_routes(app, SimpleNamespace(BASE_DIR=self.base))
        app.add_url_rule('/postVideo', view_func=sau_backend.postVideo, methods=['POST'])
        app.add_url_rule('/postVideoBatch', view_func=sau_backend.postVideoBatch, methods=['POST'])
        client = app.test_client()
        with patch.object(sau_backend, 'app', app):
            request_data = {"type": 9, "title": "旧入口测试文章", "articleBody": "这是旧入口的完整纯文本正文。", "accountList": ["a.json"]}
            response = client.post('/postVideo', json=request_data)
            self.assertEqual(response.status_code, 200)
            self.assertIn('batchId', response.json['data'])
            self.assertEqual(response.json['data']['tasks'][0]['status'], 'queued')
            self.assertEqual(client.post('/postVideo', json={**request_data, 'enableTimer': True}).status_code, 400)
            instance = app.extensions['article_service']()
            legacy_id = response.json['data']['article_id']
            instance.update_article(legacy_id, {"expected_revision": 1, "content": "网页修改后的不同正文", "format": "text"})
            repeated = client.post('/postVideo', json=request_data)
            self.assertEqual(repeated.status_code, 409)
            self.assertIn("原稿已被修改", repeated.json['msg'])
            self.assertEqual(len(instance.batches(legacy_id)), 1)
            invalid = client.post('/postVideoBatch', json=[{**request_data, 'idempotency_key': 123}])
            self.assertEqual(invalid.status_code, 400)

    def test_public_url_blocks_private_and_mixed_dns(self):
        for addresses in (["127.0.0.1"], ["10.0.0.2"], ["8.8.8.8", "::1"]):
            with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", (ip, 443)) for ip in addresses]):
                with self.assertRaises(ArticleError):
                    public_url("https://example.test/a.png")
        with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]):
            self.assertEqual(public_url("https://example.test/a.png")[2], "8.8.8.8")

    def test_download_redirect_revalidates_and_stream_limit(self):
        """公网图片重定向到内网被拒绝，无长度声明的流同样有大小上限。"""
        response = MagicMock()
        response.status = 302
        response.getheader.return_value = "http://127.0.0.1/secret.png"
        conn = MagicMock()
        conn.getresponse.return_value = response
        with patch("utils.articles.assets.public_url", side_effect=[
                (SimpleNamespace(hostname="public.test", scheme="https", path="/配图.png", query=""), 443, "8.8.8.8"),
                ArticleError("图片链接不能指向内网")]) as validated, \
                patch("utils.articles.assets.PinnedHTTPSConnection", return_value=conn):
            with self.assertRaisesRegex(ArticleError, "内网"):
                download_image("https://public.test/配图.png", 10)
            self.assertEqual(validated.call_count, 2)
            self.assertIn("%E9%85%8D", conn.request.call_args.args[1])
            conn.close.assert_called_once()
        response.status = 200
        response.getheader.side_effect = lambda name: "image/png" if name == "Content-Type" else None
        response.read.side_effect = [b"12345", b"678901"]
        with patch("utils.articles.assets.public_url", return_value=(
                SimpleNamespace(hostname="public.test", scheme="https", path="/a.png", query=""), 443, "8.8.8.8")), \
                patch("utils.articles.assets.PinnedHTTPSConnection", return_value=conn):
            with self.assertRaisesRegex(ArticleError, "大小"):
                download_image("https://public.test/a.png", 10)

    def test_routes_and_asset_content(self):
        """API 的公共字段不泄漏文件路径；刷新可恢复文章和任务。"""
        app = Flask(__name__)
        app.config.update(ARTICLE_WORKER_ENABLED=False, ARTICLE_DB_PATH=self.base / "db.sqlite",
                          ARTICLE_BASE_DIR=self.base, ARTICLE_ASSET_DIR=self.base / "assets")
        register_article_routes(app, SimpleNamespace(BASE_DIR=self.base))
        client = app.test_client()
        uploaded = client.post("/api/article-assets", data={"file": (io.BytesIO(image_bytes()), "配图.png")}).json["data"]
        self.assertNotIn("path", uploaded)
        with client.get(uploaded["url"]) as asset_response:
            self.assertEqual(asset_response.status_code, 200)
        self.assertEqual(client.get("/api/articles").json["data"][0]["id"], self.article["id"])
        self.assertEqual(client.patch(f'/api/articles/{self.article["id"]}', json={"expected_revision": 0}).status_code, 409)
        caps = client.get("/api/article-capabilities").json["data"]["platforms"]
        self.assertEqual(len(caps), 4)
        self.assertTrue(all(not item["scheduled"] for item in caps))


if __name__ == "__main__":
    unittest.main()

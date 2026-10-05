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

from utils.account_bindings import bind_account
from utils.articles.assets import ArticleAssets, download_image, public_url
from utils.articles.model import ArticleError, clean_content
from utils.articles.platforms import PLATFORMS
from utils.articles.routes import register_article_routes
from utils.articles.service import ArticleService


NEW_PLATFORM_TYPES = {"yidian": 12, "dayu": 13, "netease": 14, "acfun": 15, "kuaichuan": 16,
                      "xueqiu": 17, "jingdong": 18, "douban": 19, "csdn": 20, "jianshu": 21,
                      "chejiahao": 22, "yiche": 23, "dongchedi": 24}
AUTOMOTIVE_PLATFORMS = ("chejiahao", "yiche", "dongchedi")
NEW_PLATFORM_OPTIONS = {
    "yidian": {"statement": "原创内容"}, "dayu": {"statement": "原创内容"},
    "netease": {"original": True}, "acfun": {"category": "生活", "summary": "文章摘要", "original": True},
    "kuaichuan": {"original": True}, "xueqiu": {"visibility": "公开"},
    "douban": {"original": True, "visibility": "公开"},
    "csdn": {"summary": "文章摘要", "create_type": "原创"},
    "chejiahao": {"original": False, "first_publish": False, "agree_upload_terms": True},
    "yiche": {"declaration": "内容无需标注", "allow_forward": False, "allow_abstract": False},
}


def image_bytes(size=(640, 480), color="white"):
    """生成本地测试图片，不使用真实账号或官网素材。"""
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
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

    def add_new_platform_accounts(self):
        """每个平台分配独立临时会话，不共享旧账号或真实凭据。"""
        rows, targets = [], []
        for platform, kind in NEW_PLATFORM_TYPES.items():
            filename = f"{platform}.json"
            (self.cookies / filename).write_text('{"cookies":[],"origins":[]}', encoding="utf-8")
            rows.append((kind, kind, filename, f"{platform}测试账号", 1))
            targets.append({"platform": platform, "account_id": kind})
        with self.service.store.connect(write=True) as conn:
            conn.executemany("INSERT INTO user_info VALUES (?,?,?,?,?)", rows)
            for platform, kind in NEW_PLATFORM_TYPES.items():
                bind_account(conn, kind, platform, source="test-fixture")
        return targets

    def prepare_new_platform_article(self):
        """建立符合各平台必填项的原稿，用真实素材存储与校验链路。"""
        asset = self.service.assets.save(image_bytes(), "新平台配图.png")
        jingdong_cover = self.service.assets.save(image_bytes((700, 490), "blue"), "京东独立封面.png")
        vertical_cover = self.service.assets.save(image_bytes((600, 800), "green"), "汽车平台竖版封面.png")
        yiche_cover = self.service.assets.save(image_bytes((720, 480), "red"), "易车横版封面.png")
        defaults = {platform: {"options": dict(options)} for platform, options in NEW_PLATFORM_OPTIONS.items()}
        defaults["jingdong"] = {"title": "京东独立文章发布自动化测试标题", "cover_asset_id": jingdong_cover["id"], "options": {}}
        for platform in AUTOMOTIVE_PLATFORMS:
            defaults.setdefault(platform, {}).setdefault("options", {})["vertical_cover_asset_id"] = vertical_cover["id"]
        defaults["yiche"]["cover_asset_id"] = yiche_cover["id"]
        self.article = self.service.create_article({
            "title": "新平台独立文章测试标题", "format": "html",
            "content": f'<p>需要保留的原始正文<img src="{asset["url"]}"></p>',
            "cover_asset_id": asset["id"], "tags": ["技术"],
            "platform_options": defaults,
        })
        return asset

    def test_new_platform_snapshots_and_preview_are_immutable_and_idempotent(self):
        """编辑原稿或重放幂等请求后，各平台仍执行首次冻结的独立预览。"""
        targets = self.add_new_platform_accounts()
        asset = self.prepare_new_platform_article()
        for target in targets:
            target["overrides"] = {"title": f'{PLATFORMS[target["platform"]]["label"]}独立平台文章发布快照测试标题'}
        next(target for target in targets if target["platform"] == "csdn")["overrides"]["options"] = {"summary": "单账号独立摘要"}
        request = {"revision": self.article["revision"], "mode": "preview",
                   "idempotency_key": "新平台冻结预览", "targets": targets}
        batch = self.service.publish(self.article["id"], request)
        self.assertEqual(self.service.publish(self.article["id"], request)["id"], batch["id"])
        with self.service.store.connect() as conn:
            before = {row["platform"]: row["snapshot_json"] for row in conn.execute(
                "SELECT platform,snapshot_json FROM article_publish_tasks WHERE batch_id=?", (batch["id"],))}
        self.service.update_article(self.article["id"], {
            "expected_revision": 1, "title": "编辑后的另一版本标题", "content": "已经移除图片的新正文",
            "format": "text", "cover_asset_id": None, "platform_options": {}, "tags": [],
        })
        self.assertEqual(self.service.publish(self.article["id"], request)["id"], batch["id"])
        with self.assertRaises(ArticleError):
            self.service.assets.delete(asset["id"])

        observed = set()
        def preview(snapshot, cookie, assets, on_submit, directory):
            platform = snapshot["platform"]
            observed.add(platform)
            self.assertEqual(snapshot, json.loads(before[platform]))
            self.assertEqual(cookie, self.cookies / f"{platform}.json")
            self.assertIn(asset["id"], assets)
            self.assertEqual(snapshot["title"], f'{PLATFORMS[platform]["label"]}独立平台文章发布快照测试标题')
            self.assertEqual(snapshot["content_html"], self.article["content_html"])
            expected_tags = [] if platform in {"yidian", "dayu", "netease", "xueqiu", "jingdong", "jianshu", *AUTOMOTIVE_PLATFORMS} else ["技术"]
            self.assertEqual(snapshot["tags"], expected_tags)
            expected_cover = None if platform in {"douban", "jianshu"} else asset["id"]
            if platform in {"jingdong", "yiche"}:
                expected_cover = self.article["platform_options"][platform]["cover_asset_id"]
            self.assertEqual(snapshot["cover_asset_id"], expected_cover)
            expected_options = dict(NEW_PLATFORM_OPTIONS.get(platform, {}))
            if platform in AUTOMOTIVE_PLATFORMS:
                vertical_id = self.article["platform_options"][platform]["options"]["vertical_cover_asset_id"]
                expected_options["vertical_cover_asset_id"] = vertical_id
                self.assertIn(vertical_id, assets)
                self.assertEqual((assets[vertical_id]["width"], assets[vertical_id]["height"]), (600, 800))
            if platform == "csdn":
                expected_options["summary"] = "单账号独立摘要"
            self.assertEqual(snapshot["options"], expected_options)
            return {"status": "previewed", "message": "隔离预览完成"}

        self.service.runner = preview
        self.assertTrue(self.service.acquire())
        while self.service.run_next():
            pass
        complete = self.service.get_batch(batch["id"])
        self.assertEqual(observed, set(NEW_PLATFORM_TYPES))
        for task in complete["tasks"]:
            self.assertFalse(task["submit_started"])
            self.assertEqual(task["status"], "previewed", task)
        with self.service.store.connect() as conn:
            after = {row["platform"]: row["snapshot_json"] for row in conn.execute(
                "SELECT platform,snapshot_json FROM article_publish_tasks WHERE batch_id=?", (batch["id"],))}
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM article_publish_batches").fetchone()[0], 1)
        self.assertEqual(after, before)

    def test_new_platform_wrong_account_leaves_valid_target_queued(self):
        """错误账号不跨平台复用，也不会阻断同批次已有平台。"""
        targets = self.add_new_platform_accounts()
        self.prepare_new_platform_article()
        targets = [{**target, "account_id": 1} for target in targets]
        targets.append({"platform": "toutiao", "account_id": 2})
        batch = self.publish(targets=targets, mode="preview")
        tasks = {task["platform"]: task for task in batch["tasks"]}
        self.assertEqual(tasks["toutiao"]["status"], "queued")
        for platform in NEW_PLATFORM_TYPES:
            task = tasks[platform]
            with self.subTest(platform=platform):
                self.assertEqual(task["status"], "failed")
                self.assertEqual(task["stage"], "validation")
                self.assertFalse(task["retry_allowed"])
                self.assertFalse(task["submit_started"])
                self.assertIn("不匹配", task["message"])

    def test_temporarily_unavailable_platform_does_not_block_other_targets(self):
        """维护开关阻止适配器构造与新任务，其余平台仍可正常排队。"""
        from utils.articles.adapter import create_adapter
        self.add_new_platform_accounts()
        self.prepare_new_platform_article()
        reason = "平台临时维护，请稍后重试"
        with patch.dict(PLATFORMS["chejiahao"], {"available": False, "reason": reason}):
            with self.assertRaisesRegex(ValueError, reason):
                create_adapter({"platform": "chejiahao", "mode": "preview"}, Path("隔离账号.json"), None)
            batch = self.publish(mode="preview", targets=[
                {"platform": "chejiahao", "account_id": 22}, {"platform": "toutiao", "account_id": 2}])
        tasks = {task["platform"]: task for task in batch["tasks"]}
        self.assertEqual(tasks["toutiao"]["status"], "queued", tasks["toutiao"])
        self.assertEqual(tasks["chejiahao"]["status"], "failed", tasks["chejiahao"])
        self.assertEqual(tasks["chejiahao"]["message"], reason)
        self.assertEqual(tasks["chejiahao"]["stage"], "validation")
        self.assertFalse(tasks["chejiahao"]["submit_started"])
        self.assertFalse(tasks["chejiahao"]["retry_allowed"])

    def test_new_platform_preview_cannot_submit_even_with_incorrect_runner(self):
        """新增平台同样受服务层预览保护，错误执行器不能触发正式提交。"""
        targets = self.add_new_platform_accounts()
        self.prepare_new_platform_article()
        def broken_runner(snapshot, cookie, assets, on_submit, directory):
            on_submit()
            self.fail("预览提交回调必须被服务拒绝")
        self.service.runner = broken_runner
        batch = self.publish(mode="preview", targets=targets)
        self.assertTrue(self.service.acquire())
        while self.service.run_next():
            pass
        for task in self.service.get_batch(batch["id"])["tasks"]:
            with self.subTest(platform=task["platform"]):
                self.assertEqual(task["status"], "failed")
                self.assertFalse(task["submit_started"])
                self.assertIn("预览", task["message"])

    def test_new_platform_explicit_unsupported_cover_or_tags_are_not_silently_dropped(self):
        """通用字段可按能力继承，显式指定的不支持字段必须返回可修正错误。"""
        self.add_new_platform_accounts()
        asset = self.prepare_new_platform_article()
        overrides = [(platform, {"cover_asset_id": asset["id"]}, "封面") for platform in ("douban", "jianshu")]
        overrides.extend((platform, {"tags": ["显式话题"]}, "话题")
                         for platform in ("yidian", "dayu", "netease", "xueqiu", "jingdong", "jianshu"))
        overrides.extend((platform, {"tags": ["显式话题"]}, "话题") for platform in AUTOMOTIVE_PLATFORMS)
        for index, (platform, changes, field) in enumerate(overrides):
            with self.subTest(platform=platform, field=field):
                batch = self.publish(key=f"显式覆盖-{index}", mode="preview", targets=[
                    {"platform": platform, "account_id": NEW_PLATFORM_TYPES[platform], "overrides": changes}])
                task = batch["tasks"][0]
                self.assertEqual(task["status"], "failed")
                self.assertEqual(task["stage"], "validation")
                self.assertIn(field, task["message"])
                self.assertFalse(task["retry_allowed"])

    def test_missing_new_platform_requirements_fail_only_affected_targets(self):
        """清空分类或标签后应指明对应平台必填项，已有平台仍可执行。"""
        self.add_new_platform_accounts()
        self.prepare_new_platform_article()
        batch = self.publish(mode="preview", targets=[
            {"platform": "acfun", "account_id": 15, "overrides": {"options": {"category": ""}}},
            {"platform": "csdn", "account_id": 20, "overrides": {"tags": []}},
            {"platform": "toutiao", "account_id": 2},
        ])
        tasks = {task["platform"]: task for task in batch["tasks"]}
        self.assertEqual(tasks["toutiao"]["status"], "queued")
        for platform, message in (("acfun", "分类"), ("csdn", "标签")):
            self.assertEqual(tasks[platform]["status"], "failed")
            self.assertIn(message, tasks[platform]["message"])
            self.assertFalse(tasks[platform]["submit_started"])

    def test_automotive_option_assets_are_frozen_referenced_and_loaded_for_runner(self):
        """竖图独立于正文/横图，原稿或任务仍引用时不可删除，改稿不改变已有任务。"""
        self.add_new_platform_accounts()
        horizontal = self.prepare_new_platform_article()
        original_vertical = self.article["platform_options"]["chejiahao"]["options"]["vertical_cover_asset_id"]
        with self.assertRaises(ArticleError):
            self.service.assets.delete(original_vertical)
        targets = [{"platform": platform, "account_id": NEW_PLATFORM_TYPES[platform]} for platform in AUTOMOTIVE_PLATFORMS]
        batch = self.publish(mode="preview", targets=targets)
        self.assertEqual([task["status"] for task in batch["tasks"]], ["queued"] * 3)
        replacement = self.service.assets.save(image_bytes((600, 800), "red"), "替换竖封面.png")
        defaults = {platform: {"options": {**NEW_PLATFORM_OPTIONS.get(platform, {}),
            "vertical_cover_asset_id": replacement["id"]}} for platform in AUTOMOTIVE_PLATFORMS}
        self.service.update_article(self.article["id"], {"expected_revision": 1, "platform_options": defaults})
        with self.assertRaises(ArticleError):
            self.service.assets.delete(original_vertical)
        with self.assertRaises(ArticleError):
            self.service.assets.delete(self.article["platform_options"]["yiche"]["cover_asset_id"])

        seen = set()
        def runner(snapshot, cookie, assets, on_submit, directory):
            platform = snapshot["platform"]
            seen.add(platform)
            self.assertEqual(snapshot["options"], {**NEW_PLATFORM_OPTIONS.get(platform, {}),
                                                   "vertical_cover_asset_id": original_vertical})
            expected_assets = {horizontal["id"], original_vertical}
            if platform == "yiche":
                expected_assets.add(self.article["platform_options"][platform]["cover_asset_id"])
            self.assertEqual(set(assets), expected_assets)
            self.assertNotIn(replacement["id"], assets)
            self.assertEqual(Path(assets[original_vertical]["path"]).read_bytes(), image_bytes((600, 800), "green"))
            self.assertEqual(cookie.name, f"{platform}.json")
            return {"status": "previewed", "message": "隔离素材引用测试"}
        self.service.runner = runner
        self.assertTrue(self.service.acquire())
        while self.service.run_next():
            pass
        self.assertEqual(seen, set(AUTOMOTIVE_PLATFORMS))
        for task in self.service.get_batch(batch["id"])["tasks"]:
            self.assertEqual(task["status"], "previewed", task)
            self.assertFalse(task["submit_started"])

    def test_automotive_vertical_cover_validation_leaves_other_targets_queued(self):
        """缺图、错误引用和车家号尺寸比例违规在入队前失败，不影响其他目标。"""
        self.add_new_platform_accounts()
        self.prepare_new_platform_article()
        bad_ratio = self.service.assets.save(image_bytes((480, 600), "red"), "错误比例竖图.png")
        too_small = self.service.assets.save(image_bytes((240, 320), "red"), "过小竖图.png")
        valid_minimum = self.service.assets.save(image_bytes((561, 748), "red"), "最小合法竖图.png")
        below_minimum = self.service.assets.save(image_bytes((558, 744), "red"), "略小于最小竖图.png")
        cases = [(platform, value, "failed") for platform in AUTOMOTIVE_PLATFORMS for value in (None, "missing-asset")]
        cases.extend([("chejiahao", bad_ratio["id"], "failed"), ("chejiahao", too_small["id"], "failed"),
                      ("chejiahao", below_minimum["id"], "failed"),
                      ("chejiahao", valid_minimum["id"], "queued")])
        for index, (platform, vertical_id, expected) in enumerate(cases):
            with self.subTest(platform=platform, asset=vertical_id):
                batch = self.publish(key=f"汽车竖封面校验-{index}", mode="preview", targets=[
                    {"platform": platform, "account_id": NEW_PLATFORM_TYPES[platform],
                     "overrides": {"options": {"vertical_cover_asset_id": vertical_id}}},
                    {"platform": "toutiao", "account_id": 2}])
                tasks = {task["platform"]: task for task in batch["tasks"]}
                self.assertEqual(tasks["toutiao"]["status"], "queued", tasks["toutiao"])
                task = tasks[platform]
                self.assertEqual(task["status"], expected, task)
                self.assertFalse(task["submit_started"])
                if expected == "failed":
                    self.assertEqual(task["stage"], "validation")
                    self.assertFalse(task["retry_allowed"])
                    self.assertTrue("封面" in task["message"] or "素材" in task["message"], task)

    def test_automotive_title_characters_and_boundaries_do_not_truncate(self):
        """原生长度规则各自生效，最长合法标题保留原文，相邻越界拒绝。"""
        self.add_new_platform_accounts()
        self.prepare_new_platform_article()
        cases = [
            ("chejiahao", "新车评测测", "failed"), ("chejiahao", "新车评测测试", "queued"),
            ("chejiahao", "车" * 30, "queued"), ("chejiahao", "车" * 31, "failed"),
            ("chejiahao", "a" * 11, "failed"), ("chejiahao", "a" * 12, "queued"),
            ("chejiahao", "a" * 60, "queued"), ("chejiahao", "a" * 61, "failed"),
            ("chejiahao", "🚗" * 2, "failed"), ("chejiahao", "🚗" * 3, "failed"),
            ("chejiahao", "🚗" * 15, "failed"), ("chejiahao", "🚗" * 16, "failed"),
            ("chejiahao", "车家标题测试☀", "failed"), ("chejiahao", "车家标题测试⟿", "failed"),
            ("yiche", "车" * 4, "failed"), ("yiche", "车" * 5, "queued"),
            ("yiche", "车" * 28, "queued"), ("yiche", "车" * 29, "failed"),
            ("dongchedi", "车abc", "failed"), ("dongchedi", "新车", "queued"),
            ("dongchedi", "车" * 30, "queued"), ("dongchedi", "车" * 31, "failed"),
        ]
        for index, (platform, title, expected) in enumerate(cases):
            with self.subTest(platform=platform, title=title):
                batch = self.publish(key=f"汽车标题-{index}", mode="preview", targets=[
                    {"platform": platform, "account_id": NEW_PLATFORM_TYPES[platform], "overrides": {"title": title}}])
                task = batch["tasks"][0]
                self.assertEqual(task["status"], expected, task)
                if expected == "queued":
                    with self.service.store.connect() as conn:
                        snapshot = json.loads(conn.execute("SELECT snapshot_json FROM article_publish_tasks WHERE id=?", (task["id"],)).fetchone()[0])
                    self.assertEqual(snapshot["title"], title)
                else:
                    self.assertIn("标题", task["message"])
                    self.assertFalse(task["retry_allowed"])

    def test_chejiahao_horizontal_cover_uses_confirmed_dimensions_and_ratio(self):
        """车家号横图的最小尺寸包含边界，比例不符或略小都不能排队。"""
        self.add_new_platform_accounts()
        self.prepare_new_platform_article()
        for size, expected in (((560, 420), "queued"), ((640, 480), "queued"),
                               ((560, 421), "failed"), ((556, 417), "failed")):
            with self.subTest(size=size):
                cover = self.service.assets.save(image_bytes(size, "red"), f"横图{size}.png")
                batch = self.publish(key=f"车家号横图-{size}", mode="preview", targets=[
                    {"platform": "chejiahao", "account_id": 22, "overrides": {"cover_asset_id": cover["id"]}}])
                task = batch["tasks"][0]
                self.assertEqual(task["status"], expected, task)
                if expected == "failed":
                    self.assertIn("封面", task["message"])
                    self.assertFalse(task["retry_allowed"])

    def test_chejiahao_upload_terms_require_explicit_consent_per_target(self):
        """条款未同意不能排队；已保存同意也允许单账号明确拒绝，其他平台不受影响。"""
        self.add_new_platform_accounts()
        self.prepare_new_platform_article()
        for index, (agreement, expected) in enumerate(((None, "failed"), (False, "failed"), (True, "queued"))):
            batch = self.publish(key=f"车家条款-{index}", mode="preview", targets=[
                {"platform": "chejiahao", "account_id": 22, "overrides": {"options": {"agree_upload_terms": agreement}}},
                {"platform": "toutiao", "account_id": 2}])
            tasks = {task["platform"]: task for task in batch["tasks"]}
            self.assertEqual(tasks["toutiao"]["status"], "queued", tasks["toutiao"])
            task = tasks["chejiahao"]
            self.assertEqual(task["status"], expected, task)
            if expected == "failed":
                self.assertIn("同意", task["message"])
                self.assertFalse(task["retry_allowed"])
                self.assertFalse(task["submit_started"])

    def test_chejiahao_links_require_explicit_conversion_before_browser(self):
        """原稿保留链接，执行前须明确允许降级为文字与完整网址，不能静默丢失。"""
        from utils.articles.adapter import validate_task
        self.add_new_platform_accounts()
        cover = self.prepare_new_platform_article()
        self.article = self.service.update_article(self.article["id"], {
            "expected_revision": self.article["revision"], "format": "html",
            "content": '<p>来源：<a href="https://example.com/original">原始文章</a></p>'})
        vertical_id = self.article["platform_options"]["chejiahao"]["options"]["vertical_cover_asset_id"]
        assets = {cover["id"]: self.service.assets.get(cover["id"]), vertical_id: self.service.assets.get(vertical_id)}
        snapshot = self.service.snapshot(self.article, {"platform": "chejiahao"}, "preview")
        with self.assertRaisesRegex(ValueError, "超链接"):
            validate_task(snapshot, assets)
        with self.assertRaisesRegex(ValueError, "超链接"):
            validate_task({**snapshot, "options": {**snapshot["options"], "links_as_text": False}}, assets)
        explicit = {**snapshot, "options": {**snapshot["options"], "links_as_text": True}}
        self.assertEqual(validate_task(explicit, assets), Path(assets[cover["id"]]["path"]))
        self.assertIn('<a href="https://example.com/original"', snapshot["content_html"])

    def test_dongchedi_separate_cover_boundaries_are_validated_before_queueing(self):
        """懂车官方横竖封面最小尺寸不同，两张图片都必须符合原生裁剪比例。"""
        self.add_new_platform_accounts()
        self.prepare_new_platform_article()
        cases = [
            ("horizontal", (532, 399), "queued"), ("horizontal", (528, 396), "failed"),
            ("horizontal", (532, 400), "failed"), ("vertical", (534, 712), "queued"),
            ("vertical", (531, 708), "failed"), ("vertical", (534, 711), "failed"),
        ]
        for role, size, expected in cases:
            with self.subTest(role=role, size=size):
                cover = self.service.assets.save(image_bytes(size, "red"), f"懂车{role}{size}.png")
                overrides = {"cover_asset_id": cover["id"]} if role == "horizontal" else {
                    "options": {"vertical_cover_asset_id": cover["id"]}}
                batch = self.publish(key=f"懂车封面-{role}-{size}", mode="preview", targets=[
                    {"platform": "dongchedi", "account_id": 24, "overrides": overrides},
                    {"platform": "toutiao", "account_id": 2}])
                tasks = {task["platform"]: task for task in batch["tasks"]}
                self.assertEqual(tasks["toutiao"]["status"], "queued", tasks["toutiao"])
                task = tasks["dongchedi"]
                self.assertEqual(task["status"], expected, task)
                if expected == "failed":
                    self.assertIn("封面", task["message"])
                    self.assertFalse(task["retry_allowed"])
                    self.assertFalse(task["submit_started"])

    def test_dongchedi_heading_levels_fail_before_queueing_without_changing_original(self):
        """一级标题/普通段落可排队，二至六级标题只阻断懂车，原稿层级不被改写。"""
        self.add_new_platform_accounts()
        self.prepare_new_platform_article()
        cases = [("p", "queued"), ("h1", "queued"), *[(f"h{level}", "failed") for level in range(2, 7)]]
        for tag, expected in cases:
            with self.subTest(tag=tag):
                content = f"<{tag}>保留原始标题层级</{tag}><p>完整正文内容。</p>"
                self.article = self.service.update_article(self.article["id"], {
                    "expected_revision": self.article["revision"], "format": "html", "content": content})
                batch = self.publish(key=f"懂车标题层级-{tag}", mode="preview", targets=[
                    {"platform": "dongchedi", "account_id": 24}, {"platform": "toutiao", "account_id": 2}])
                tasks = {task["platform"]: task for task in batch["tasks"]}
                self.assertEqual(tasks["toutiao"]["status"], "queued", tasks["toutiao"])
                self.assertEqual(tasks["dongchedi"]["status"], expected, tasks["dongchedi"])
                self.assertEqual(self.service.get_article(self.article["id"])["content_html"], content)
                if expected == "failed":
                    task = tasks["dongchedi"]
                    self.assertEqual(task["stage"], "validation")
                    self.assertIn("一级标题", task["message"])
                    self.assertFalse(task["retry_allowed"])
                    self.assertFalse(task["submit_started"])

    def test_yiche_cover_variants_and_html_limit_follow_article_contract(self):
        """易车接受契约中的两种竖图比例，横图宽度及正文 HTML 上限分别生效。"""
        self.add_new_platform_accounts()
        self.prepare_new_platform_article()
        for size, expected in (((480, 640), "queued"), ((640, 480), "queued"), ((640, 640), "failed")):
            cover = self.service.assets.save(image_bytes(size, "red"), f"易车竖图{size}.png")
            batch = self.publish(key=f"易车竖图-{size}", mode="preview", targets=[
                {"platform": "yiche", "account_id": 23, "overrides": {"options": {"vertical_cover_asset_id": cover["id"]}}}])
            self.assertEqual(batch["tasks"][0]["status"], expected, batch["tasks"][0])
        wrong_ratio = self.service.assets.save(image_bytes((640, 480), "blue"), "易车错误横图比例.png")
        invalid = self.publish(key="易车横图比例", mode="preview", targets=[
            {"platform": "yiche", "account_id": 23, "overrides": {"cover_asset_id": wrong_ratio["id"]}}])["tasks"][0]
        self.assertEqual(invalid["status"], "failed", invalid)
        self.assertIn("3:2", invalid["message"])
        for width, expected in ((4998, "queued"), (5001, "failed")):
            cover = self.service.assets.save(image_bytes((width, width * 2 // 3), "red"), f"易车横图{width}.png")
            batch = self.publish(key=f"易车横图-{width}", mode="preview", targets=[
                {"platform": "yiche", "account_id": 23, "overrides": {"cover_asset_id": cover["id"]}}])
            task = batch["tasks"][0]
            self.assertEqual(task["status"], expected, task)
            if expected == "failed":
                self.assertIn("5000", task["message"])
        for length, expected in ((8000, "queued"), (8001, "failed")):
            self.article = self.service.update_article(self.article["id"], {
                "expected_revision": self.article["revision"], "content": "<p>" + "字" * (length - 7) + "</p>", "format": "html"})
            self.assertEqual(len(self.article["content_html"]), length)
            batch = self.publish(key=f"易车正文-{length}", mode="preview", targets=[
                {"platform": "yiche", "account_id": 23}, {"platform": "toutiao", "account_id": 2}])
            tasks = {task["platform"]: task for task in batch["tasks"]}
            self.assertEqual(tasks["toutiao"]["status"], "queued", tasks["toutiao"])
            self.assertEqual(tasks["yiche"]["status"], expected, tasks["yiche"])
            if expected == "failed":
                self.assertIn("8000", tasks["yiche"]["message"])
                self.assertFalse(tasks["yiche"]["submit_started"])

    def test_yiche_reprint_source_failure_is_isolated_and_frozen_in_valid_snapshot(self):
        """有效转载链接原样冻结；缺失来源或旧声明只阻断对应账号，不能自动变更声明。"""
        self.add_new_platform_accounts()
        self.prepare_new_platform_article()
        source = "https://example.com/article?version=original"
        for index, (options, expected) in enumerate([
            ({"declaration": "内容为转载"}, "failed"),
            ({"declaration": "内容为转载", "source_url": "javascript:alert(1)"}, "failed"),
            ({"declaration": "AI生成"}, "failed"),
            ({"declaration": "内容为转载", "source_url": source}, "queued"),
        ]):
            batch = self.publish(key=f"易车转载-{index}", mode="preview", targets=[
                {"platform": "yiche", "account_id": 23, "overrides": {"options": options}},
                {"platform": "toutiao", "account_id": 2}])
            tasks = {task["platform"]: task for task in batch["tasks"]}
            self.assertEqual(tasks["toutiao"]["status"], "queued", tasks["toutiao"])
            task = tasks["yiche"]
            self.assertEqual(task["status"], expected, task)
            if expected == "queued":
                with self.service.store.connect() as conn:
                    snapshot = json.loads(conn.execute("SELECT snapshot_json FROM article_publish_tasks WHERE id=?", (task["id"],)).fetchone()[0])
                self.assertEqual(snapshot["options"]["source_url"], source)
                self.assertEqual(snapshot["options"]["declaration"], "内容为转载")
                self.assertIs(snapshot["options"]["allow_forward"], False)
                self.assertIs(snapshot["options"]["allow_abstract"], False)
            else:
                self.assertEqual(task["stage"], "validation")
                self.assertFalse(task["retry_allowed"])
                self.assertFalse(task["submit_started"])

    def test_jingdong_cover_constraints_are_enforced_before_queueing(self):
        """京东错误比例、尺寸和文件大小只阻断自己的任务，合法独立封面可入队。"""
        self.add_new_platform_accounts()
        body = self.service.assets.save(image_bytes(), "独立正文首图.png")
        oversized = io.BytesIO()
        Image.new("RGB", (2100, 1470), "blue").save(oversized, "PNG", compress_level=0)
        self.assertGreater(len(oversized.getvalue()), 5 * 1024 * 1024)
        cases = [
            ("错误比例", image_bytes((700, 500), "red"), "failed"),
            ("尺寸过小", image_bytes((500, 350), "red"), "failed"),
            ("超过五兆", oversized.getvalue(), "failed"),
            ("最小合法尺寸", image_bytes((600, 420), "red"), "queued"),
            ("独立合法封面", image_bytes((700, 490), "blue"), "queued"),
        ]
        for label, data, expected in cases:
            with self.subTest(case=label):
                cover = self.service.assets.save(data, f"{label}.png")
                self.article = self.service.create_article({
                    "title": "京东独立文章发布自动化测试标题", "format": "html",
                    "content": f'<p>正文及第一张图片<img src="{body["url"]}"></p>',
                    "cover_asset_id": cover["id"],
                })
                batch = self.publish(key=label, mode="preview", targets=[
                    {"platform": "jingdong", "account_id": 18}, {"platform": "toutiao", "account_id": 2},
                ])
                tasks = {task["platform"]: task for task in batch["tasks"]}
                self.assertEqual(tasks["toutiao"]["status"], "queued", tasks["toutiao"])
                self.assertEqual(tasks["jingdong"]["status"], expected, tasks["jingdong"])
                self.assertFalse(tasks["jingdong"]["submit_started"])
                if expected == "failed":
                    self.assertEqual(tasks["jingdong"]["stage"], "validation")
                    self.assertIn("封面", tasks["jingdong"]["message"])
                    self.assertFalse(tasks["jingdong"]["retry_allowed"])

    def test_jingdong_rejects_first_body_image_as_cover_even_after_asset_reimport(self):
        """图片重复导入仍按文件去重，不能把正文首图换个文件名当封面。"""
        self.add_new_platform_accounts()
        body = self.service.assets.save(image_bytes((700, 490), "blue"), "正文首图.png")
        duplicate = self.service.assets.save(image_bytes((700, 490), "blue"), "重新导入为封面.png")
        self.assertEqual(body["id"], duplicate["id"])
        self.article = self.service.create_article({
            "title": "京东独立文章发布自动化测试标题", "format": "html",
            "content": f'<p>正文<img src="{body["url"]}"></p>', "cover_asset_id": duplicate["id"],
        })
        batch = self.publish(mode="preview", targets=[{"platform": "jingdong", "account_id": 18}])
        task = batch["tasks"][0]
        self.assertEqual(task["status"], "failed")
        self.assertEqual(task["stage"], "validation")
        self.assertIn("封面", task["message"])
        self.assertFalse(task["submit_started"])
        self.assertFalse(task["retry_allowed"])

    def test_jingdong_title_limits_preserve_exact_boundary_without_truncation(self):
        """15 至 27 字标题均保留原文；相邻越界长度在服务入口失败。"""
        self.add_new_platform_accounts()
        self.prepare_new_platform_article()
        for length, expected in ((14, "failed"), (15, "queued"), (27, "queued"), (28, "failed")):
            with self.subTest(length=length):
                title = "京" * length
                batch = self.publish(key=f"京东标题-{length}", mode="preview", targets=[
                    {"platform": "jingdong", "account_id": 18, "overrides": {"title": title}}])
                task = batch["tasks"][0]
                self.assertEqual(task["status"], expected, task)
                if expected == "queued":
                    with self.service.store.connect() as conn:
                        stored = json.loads(conn.execute("SELECT snapshot_json FROM article_publish_tasks WHERE id=?", (task["id"],)).fetchone()[0])
                    self.assertEqual(stored["title"], title)
                else:
                    self.assertIn("标题", task["message"])
                    self.assertFalse(task["retry_allowed"])

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

    def submitted_batch(self):
        """模拟一个已受理账号与一个提交前失败账号，不访问真实平台。"""
        def run(snapshot, cookie, assets, on_submit, directory):
            if snapshot["platform"] == "toutiao":
                raise RuntimeError("提交前失败")
            on_submit()
            return {"status": "submitted", "platform_id": "article-platform-id", "message": "平台已受理"}
        self.service.runner = run
        batch = self.publish(targets=[{"platform": "zhihu", "account_id": 1}, {"platform": "toutiao", "account_id": 2}])
        self.service.acquire()
        while self.service.run_next():
            pass
        return self.service.get_batch(batch["id"])

    def test_submitted_confirmation_preserves_submission_and_isolates_failure(self):
        """链接核查只升级已受理任务，保留平台编号、提交次数及其他账号失败记录。"""
        before = self.submitted_batch()
        tasks = {task["platform"]: task for task in before["tasks"]}
        submitted, failed = tasks["zhihu"], tasks["toutiao"]
        result = self.service.resolve(submitted["id"], {"resolution": "published", "note": "公开页面核实全文和图片",
            "platform_url": "https://example.com/article/1"})
        after = {task["platform"]: task for task in result["tasks"]}
        self.assertEqual(after["zhihu"]["status"], "published")
        self.assertEqual(after["zhihu"]["platform_url"], "https://example.com/article/1")
        self.assertEqual(after["zhihu"]["stage"], "resolved")
        self.assertIn("公开页面核实全文和图片", after["zhihu"]["message"])
        for field in ("platform_id", "submit_started", "attempts"):
            self.assertEqual(after["zhihu"][field], submitted[field])
        self.assertEqual(after["zhihu"]["platform_id"], "article-platform-id")
        self.assertTrue(after["zhihu"]["submit_started"])
        self.assertFalse(after["zhihu"]["retry_allowed"])
        self.assertEqual(after["toutiao"], failed)
        with self.assertRaises(ArticleError):
            self.service.retry(submitted["id"])
        with self.assertRaises(ArticleError):
            self.publish(key="确认后重复发布")

    def test_submitted_confirmation_rejects_downgrade_and_retry(self):
        """已受理任务不能被人工核查降为未发表或失败后重新提交。"""
        before = self.submitted_batch()
        task = next(task for task in before["tasks"] if task["status"] == "submitted")
        for resolution in ("not_published", "submitted", "failed"):
            with self.subTest(resolution=resolution), self.assertRaises(ArticleError):
                self.service.resolve(task["id"], {"resolution": resolution, "note": "核查说明",
                    "platform_url": "https://example.com/article/1"})
            self.assertEqual(self.service.get_batch(before["id"]), before)
        with self.assertRaises(ArticleError):
            self.service.retry(task["id"])

    def test_submitted_confirmation_requires_note_and_http_link(self):
        """说明或完整文章链接缺失时不改变状态，也不接受本地及脚本链接。"""
        before = self.submitted_batch()
        task = next(task for task in before["tasks"] if task["status"] == "submitted")
        invalid = [{}, {"platform_url": ""}, {"platform_url": " "}, {"platform_url": None},
                   {"platform_url": "file:///tmp/a"}, {"platform_url": "javascript:alert(1)"},
                   {"platform_url": "https:///article/1"}, {"platform_url": "https://example.com/a", "note": " "}]
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ArticleError):
                self.service.resolve(task["id"], {"resolution": "published", "note": "已核查", **fields})
            self.assertEqual(self.service.get_batch(before["id"]), before)

    def test_published_repeat_confirmation_does_not_rewrite_record(self):
        """重复确认已发表任务返回冲突，不覆盖第一次核查证据或重新排队。"""
        batch = self.submitted_batch()
        task = next(task for task in batch["tasks"] if task["status"] == "submitted")
        before = self.service.resolve(task["id"], {"resolution": "published", "note": "第一次核查",
            "platform_url": "http://example.com/article/1"})
        with self.assertRaises(ArticleError) as error:
            self.service.resolve(task["id"], {"resolution": "published", "note": "重复核查",
                "platform_url": "https://example.com/article/2"})
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.service.get_batch(batch["id"]), before)

    def test_failed_task_cannot_be_confirmed_published(self):
        """新确认入口仍拒绝把提交前失败的账号伪装成成功。"""
        before = self.submitted_batch()
        task = next(task for task in before["tasks"] if task["status"] == "failed")
        with self.assertRaises(ArticleError) as error:
            self.service.resolve(task["id"], {"resolution": "published", "note": "核查说明",
                "platform_url": "https://example.com/article/1"})
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(self.service.get_batch(before["id"]), before)

    def test_unknown_resolution_keeps_existing_optional_link_contract(self):
        """未知结果仍可按既有约定核查为未发表、已受理或已发表，不新增链接必填要求。"""
        batch = self.submitted_batch()
        task = next(task for task in batch["tasks"] if task["status"] == "submitted")
        for resolution, status, started in (("not_published", "failed", 0), ("submitted", "submitted", 1),
                                             ("published", "published", 1)):
            with self.subTest(resolution=resolution):
                with self.service.store.connect(write=True) as conn:
                    conn.execute("UPDATE article_publish_tasks SET status='unknown',submit_started=1 WHERE id=?", (task["id"],))
                resolved = self.service.resolve(task["id"], {"resolution": resolution, "note": "按既有流程核查"})
                current = next(item for item in resolved["tasks"] if item["id"] == task["id"])
                self.assertEqual(current["status"], status)
                self.assertEqual(current["submit_started"], started)
                self.assertEqual(current["retry_allowed"], resolution == "not_published")
                self.assertEqual(current["platform_id"], task["platform_id"])
                self.assertEqual(current["attempts"], task["attempts"])

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

    def test_acceptance_fixture_existing_twenty_one_article_platforms(self):
        """二十一个平台共用完整测试稿；仅在隔离执行边界模拟回执。"""
        root = Path(__file__).parent / "fixtures" / "article-acceptance"
        content = (root / "原稿.md").read_text(encoding="utf-8")
        # 共用合法稿仅用一级标题；懂车拒绝更深层级另有独立回归。
        content = content.replace("\n## ", "\n# ")
        assets = []
        for number in range(1, 4):
            asset = self.service.assets.save((root / f"image-{number}.png").read_bytes(), f"图片{number}.png")
            assets.append(asset)
            content = content.replace(f"image-{number}.png", asset["url"])
        jingdong_cover = self.service.assets.save(image_bytes((700, 490), "blue"), "京东独立封面.png")
        automotive_cover = self.service.assets.save(image_bytes((640, 480), "red"), "汽车平台横封面.png")
        vertical_cover = self.service.assets.save(image_bytes((600, 800), "green"), "汽车平台竖封面.png")
        yiche_cover = self.service.assets.save(image_bytes((720, 480), "red"), "易车横版封面.png")
        defaults = {platform: {"options": dict(options)} for platform, options in NEW_PLATFORM_OPTIONS.items()}
        defaults["jingdong"] = {"cover_asset_id": jingdong_cover["id"]}
        defaults["chejiahao"]["options"]["links_as_text"] = True
        for platform in AUTOMOTIVE_PLATFORMS:
            defaults.setdefault(platform, {}).setdefault("options", {})["vertical_cover_asset_id"] = vertical_cover["id"]
            defaults[platform]["cover_asset_id"] = automotive_cover["id"]
        defaults["yiche"]["cover_asset_id"] = yiche_cover["id"]
        self.article = self.service.create_article({"title": "PostSail 图文发布测试，请忽略", "content": content,
            "format": "markdown", "cover_asset_id": assets[0]["id"], "tags": ["技术"],
            "platform_options": defaults})
        self.assertEqual(self.article["content_html"].count("<img"), 3)
        self.assertIn("<table", self.article["content_html"])
        self.assertIn("<pre><code", self.article["content_html"])
        with self.service.store.connect(write=True) as conn:
            conn.executemany("INSERT INTO user_info VALUES (?,?,?,?,?)", [
                (3, 5, "a.json", "百家号测试账号", 1), (4, 8, "b.json", "搜狐测试账号", 1),
                (5, 3, "a.json", "抖音测试账号", 1), (6, 6, "b.json", "B站测试账号", 1),
                (7, 10, "a.json", "微博测试账号", 1), (8, 11, "b.json", "企鹅号测试账号", 1)])
        targets = [{"platform": platform, "account_id": account} for platform, account in
                   [("zhihu", 1), ("toutiao", 2), ("baijiahao", 3), ("sohu", 4),
                    ("douyin", 5), ("bilibili", 6), ("weibo", 7), ("qiehao", 8)]]
        targets.extend(self.add_new_platform_accounts())
        observed = []
        def runner(snapshot, cookie, managed_assets, on_submit, directory):
            observed.append((snapshot["platform"], snapshot["mode"]))
            expected_assets = 5 if snapshot["platform"] in AUTOMOTIVE_PLATFORMS else 4 if snapshot["platform"] == "jingdong" else 3
            self.assertEqual(len(managed_assets), expected_assets)
            self.assertEqual(snapshot["content_html"], self.article["content_html"])
            if snapshot["mode"] == "preview":
                return {"status": "previewed", "message": "模拟平台预览"}
            on_submit()
            return {"status": "submitted", "platform_status": "模拟审核中"}
        self.service.runner = runner
        self.service.acquire()
        for mode in ("preview", "publish"):
            batch = self.publish(key=f"二十一平台契约-{mode}", mode=mode, targets=targets)
            while self.service.run_next():
                pass
            tasks = self.service.get_batch(batch["id"])["tasks"]
            expected = "previewed" if mode == "preview" else "submitted"
            self.assertEqual(len(tasks), 21)
            for task in tasks:
                with self.subTest(platform=task["platform"], mode=mode):
                    self.assertEqual(task["status"], expected, task)
                    self.assertEqual(bool(task["submit_started"]), mode == "publish")
        self.assertEqual(set(observed), {(target["platform"], mode) for target in targets for mode in ("preview", "publish")})
        self.assertEqual(len(observed), 42)

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
        self.assertEqual(len(caps), 28)
        self.assertTrue(all(item["scheduled"] for item in caps))


    def test_new_image_text_platforms_preflight_in_same_batch(self):
        """新增笔记与文章共用批次，转换明确且公众号与视频号账号不混用。"""
        asset = self.service.assets.save(image_bytes(), "图文封面.png")
        for name in ("xhs.json", "ks.json", "channels.json", "wechat.json"):
            (self.cookies / name).write_text('{"cookies":[],"origins":[]}', encoding="utf-8")
        with self.service.store.connect(write=True) as conn:
            conn.executemany("INSERT INTO user_info VALUES (?,?,?,?,?)", [
                (3, 1, "xhs.json", "小红书", 1), (4, 4, "ks.json", "快手", 1),
                (5, 2, "channels.json", "视频号", 1), (6, 25, "wechat.json", "公众号", 1)])
            for account_id, platform in ((3, "xiaohongshu"), (4, "kuaishou"), (5, "tencent"), (6, "wechat")):
                bind_account(conn, account_id, platform, source="test-fixture")
        self.article = self.service.update_article(self.article["id"], {"expected_revision": 1,
            "cover_asset_id": asset["id"]})
        targets = [{"platform": "zhihu", "account_id": 1}]
        targets += [{"platform": platform, "account_id": account_id,
                     "overrides": {"options": {"flatten_content": True}}}
                    for platform, account_id in (("xiaohongshu", 3), ("kuaishou", 4), ("tencent", 5))]
        targets.append({"platform": "wechat", "account_id": 6})
        batch = self.publish(targets=targets, mode="preview")
        self.assertEqual(len(batch["tasks"]), 5)
        self.assertTrue(all(task["status"] == "queued" for task in batch["tasks"]))
        with self.assertRaisesRegex(ArticleError, "平台|账号"):
            self.service.account_file(5, "wechat")
        with self.assertRaisesRegex(ArticleError, "平台|账号"):
            self.service.account_file(6, "tencent")


    def test_note_rich_format_error_does_not_block_other_targets(self):
        """富文本未同意转换时立即记录该目标失败，保留原稿并继续其他目标。"""
        with self.service.store.connect(write=True) as conn:
            conn.execute("INSERT INTO user_info VALUES (3,1,'a.json','小红书测试账号',1)")
        batch = self.publish(targets=[{"platform": "xiaohongshu", "account_id": 3},
                                      {"platform": "zhihu", "account_id": 1}], mode="preview")
        results = {task["platform"]: task for task in batch["tasks"]}
        self.assertEqual(results["xiaohongshu"]["status"], "failed")
        self.assertIn("纯文本", results["xiaohongshu"]["message"])
        self.assertEqual(results["zhihu"]["status"], "queued")
        self.assertIn("<strong>", self.service.get_article(self.article["id"])["content_html"])


    def commerce_accounts(self):
        platforms = {"jd": (3, 26), "xiaohongshu_merchant": (4, 27), "dongchedi": (5, 24), "taobao": (6, 28)}
        rows = []
        for platform, (account_id, kind) in platforms.items():
            filename = f"独立-{platform}.json"
            (self.cookies / filename).write_text('{"cookies":[],"origins":[]}', encoding="utf-8")
            rows.append((account_id, kind, filename, f"隔离{platform}账号", 1))
        with self.service.store.connect(write=True) as conn:
            conn.executemany("INSERT INTO user_info VALUES (?,?,?,?,?)", rows)
            for platform, (account_id, _) in platforms.items():
                bind_account(conn, account_id, platform, source="test-fixture")


    def test_four_more_platforms_share_batch_and_keep_required_overrides(self):
        self.commerce_accounts()
        asset = self.service.assets.save(image_bytes((800, 800)), "商品图.png")
        horizontal = self.service.assets.save(image_bytes((640, 480), "blue"), "懂车横图.png")
        vertical = self.service.assets.save(image_bytes((600, 800), "green"), "懂车竖图.png")
        self.article = self.service.update_article(self.article["id"], {"expected_revision": 1,
            "format": "html", "content": f'<h1>图文与文章同批次</h1><p>保留原始正文<img src="{asset["url"]}"></p>',
            "cover_asset_id": asset["id"], "platform_options": {
                "xiaohongshu_merchant": {"options": {"shop_name": "测试商家店铺", "flatten_content": True}},
                "taobao": {"options": {"statement": "含AI生成内容", "flatten_content": True}},
                "dongchedi": {"cover_asset_id": horizontal["id"], "options": {"vertical_cover_asset_id": vertical["id"]}}}})
        targets = [
            {"platform": "jd", "account_id": 3, "overrides": {"options": {"flatten_content": True}}},
            {"platform": "xiaohongshu_merchant", "account_id": 4,
             "overrides": {"options": {"product_id": "12345678"}}},
            {"platform": "dongchedi", "account_id": 5},
            {"platform": "taobao", "account_id": 6},
        ]
        batch = self.publish(targets=targets, mode="preview")
        self.assertEqual(len(batch["tasks"]), 4)
        for task in batch["tasks"]:
            self.assertEqual(task["status"], "queued", task)
        accounts = {account["id"]: account["platform"] for account in self.service.accounts()}
        self.assertEqual([accounts[i] for i in (3, 4, 5, 6)], ["jd", "xiaohongshu_merchant", "dongchedi", "taobao"])
        with self.service.store.connect() as conn:
            snapshots = {row["platform"]: json.loads(row["snapshot_json"]) for row in conn.execute(
                "SELECT platform,snapshot_json FROM article_publish_tasks WHERE batch_id=?", (batch["id"],))}
        self.assertEqual(snapshots["xiaohongshu_merchant"]["options"],
                         {"shop_name": "测试商家店铺", "product_id": "12345678", "flatten_content": True})
        self.assertEqual(snapshots["taobao"]["options"]["statement"], "含AI生成内容")
        with self.assertRaises(ArticleError):
            self.service.account_file(4, "xiaohongshu")


    def test_missing_commerce_requirements_fail_only_their_target(self):
        self.commerce_accounts()
        batch = self.publish(targets=[{"platform": "xiaohongshu_merchant", "account_id": 4},
                                      {"platform": "taobao", "account_id": 6},
                                      {"platform": "zhihu", "account_id": 1}], mode="preview")
        results = {task["platform"]: task for task in batch["tasks"]}
        for platform in ("xiaohongshu_merchant", "taobao"):
            self.assertEqual(results[platform]["status"], "failed")
            self.assertIn("必须", results[platform]["message"])
        self.assertEqual(results["zhihu"]["status"], "queued")

    def test_jd_note_and_jingdong_article_accounts_and_covers_do_not_cross(self):
        """京东图文使用首图封面，京东长文章使用独立封面；相同门户也不能串账号。"""
        self.add_new_platform_accounts()
        self.commerce_accounts()
        first = self.service.assets.save(image_bytes((800, 800), "white"), "图文首图.png")
        article_cover = self.service.assets.save(image_bytes((700, 490), "blue"), "长文章独立封面.png")
        self.article = self.service.create_article({
            "title": "京东图文与长文章独立账号验证标题", "format": "html",
            "content": f'<p>保留文章正文和首图<img src="{first["url"]}"></p>',
            "cover_asset_id": first["id"], "platform_options": {
                "jingdong": {"cover_asset_id": article_cover["id"]},
                "jd": {"options": {"product_links": "https://item.jd.com/12345678.html"}}}})
        batch = self.publish(mode="preview", targets=[
            {"platform": "jd", "account_id": 3}, {"platform": "jingdong", "account_id": 18}])
        for task in batch["tasks"]:
            self.assertEqual(task["status"], "queued", task)
        seen = set()
        def runner(snapshot, cookie, assets, on_submit, directory):
            platform = snapshot["platform"]
            seen.add(platform)
            if platform == "jd":
                self.assertEqual(cookie.name, "独立-jd.json")
                self.assertEqual(snapshot["cover_asset_id"], first["id"])
                self.assertEqual(set(assets), {first["id"]})
                self.assertEqual(snapshot["options"], {"product_links": "https://item.jd.com/12345678.html"})
            else:
                self.assertEqual(cookie.name, "jingdong.json")
                self.assertEqual(snapshot["cover_asset_id"], article_cover["id"])
                self.assertEqual(set(assets), {first["id"], article_cover["id"]})
                self.assertEqual(snapshot["options"], {})
            return {"status": "previewed", "message": "隔离校验两种京东内容类型"}
        self.service.runner = runner
        self.assertTrue(self.service.acquire())
        while self.service.run_next():
            pass
        self.assertEqual(seen, {"jd", "jingdong"})
        for task in self.service.get_batch(batch["id"])["tasks"]:
            self.assertEqual(task["status"], "previewed", task)
            self.assertFalse(task["submit_started"])
        swapped = self.publish(key="京东账号交叉拒绝", mode="preview", targets=[
            {"platform": "jd", "account_id": 18}, {"platform": "jingdong", "account_id": 3}])
        for task in swapped["tasks"]:
            self.assertEqual(task["status"], "failed", task)
            self.assertIn("不匹配", task["message"])
            self.assertFalse(task["submit_started"])

    def test_legacy_type_13_requires_confirmation_and_preserves_existing_task_identity(self):
        """旧编号不能猜成大鱼或京东；明确迁移后原 ID、会话和历史平台快照保持不变。"""
        from utils.account_bindings import confirm_account_platform
        account_file = self.cookies / "来源待确认.json"
        original_cookie = b'{"cookies":[],"origins":[]}'
        account_file.write_bytes(original_cookie)
        with self.service.store.connect(write=True) as conn:
            conn.execute("INSERT INTO user_info VALUES (?,?,?,?,?)", (13, 13, account_file.name, "旧账号", 1))
        asset = self.service.assets.save(image_bytes((800, 800)), "迁移测试配图.png")
        self.article = self.service.create_article({
            "title": "旧账号所属平台确认测试", "format": "html",
            "content": f'<p>完整原稿与配图<img src="{asset["url"]}"></p>', "cover_asset_id": asset["id"]})
        before_account = next(account for account in self.service.accounts() if account["id"] == 13)
        self.assertIsNone(before_account["platform"])
        self.assertTrue(before_account["needs_confirmation"])
        original = self.publish(mode="preview", targets=[
            {"platform": "jd", "account_id": 13}, {"platform": "dayu", "account_id": 13}])
        for task in original["tasks"]:
            self.assertEqual(task["status"], "failed", task)
            self.assertEqual(task["stage"], "validation")
            self.assertIn("确认", task["message"])
            self.assertFalse(task["submit_started"])
            self.assertFalse(task["retry_allowed"])
        with self.service.store.connect() as conn:
            before = [tuple(row) for row in conn.execute(
                "SELECT id,platform,account_id,snapshot_json FROM article_publish_tasks WHERE batch_id=? ORDER BY id", (original["id"],))]
        confirmed = confirm_account_platform(self.base / "db.sqlite", 13, "jd", 13)
        self.assertEqual((confirmed["account_id"], confirmed["platform"], confirmed["type"]), (13, "jd", 26))
        self.assertTrue(Path(confirmed["backup_path"]).is_file())
        self.assertEqual(account_file.read_bytes(), original_cookie)
        after_account = next(account for account in self.service.accounts() if account["id"] == 13)
        self.assertEqual(after_account["platform"], "jd")
        self.assertFalse(after_account["needs_confirmation"])
        with self.service.store.connect() as conn:
            after = [tuple(row) for row in conn.execute(
                "SELECT id,platform,account_id,snapshot_json FROM article_publish_tasks WHERE batch_id=? ORDER BY id", (original["id"],))]
            self.assertEqual(tuple(conn.execute("SELECT id,type,filePath FROM user_info WHERE id=13").fetchone()),
                             (13, 26, account_file.name))
        self.assertEqual(after, before)
        self.assertEqual(self.service.account_file(13, "jd"), account_file)
        with self.assertRaisesRegex(ArticleError, "不匹配"):
            self.service.account_file(13, "dayu")
        batch = self.publish(key="确认所属平台后", mode="preview", targets=[
            {"platform": "jd", "account_id": 13}, {"platform": "dayu", "account_id": 13}])
        tasks = {task["platform"]: task for task in batch["tasks"]}
        self.assertEqual(tasks["jd"]["status"], "queued", tasks["jd"])
        self.assertEqual(tasks["dayu"]["status"], "failed", tasks["dayu"])
        self.assertIn("不匹配", tasks["dayu"]["message"])


    def test_taobao_image_size_is_validated_before_queueing(self):
        self.commerce_accounts()
        asset = self.service.assets.save(image_bytes(), "尺寸不足.png")
        self.article = self.service.update_article(self.article["id"], {"expected_revision": 1,
            "content": "平台正文", "format": "text", "cover_asset_id": asset["id"]})
        batch = self.publish(targets=[{"platform": "taobao", "account_id": 6,
                                      "overrides": {"options": {"statement": "内容无需标注"}}},
                                     {"platform": "jd", "account_id": 3}], mode="preview")
        results = {task["platform"]: task for task in batch["tasks"]}
        self.assertEqual(results["taobao"]["status"], "failed")
        self.assertIn("720", results["taobao"]["message"])
        self.assertEqual(results["jd"]["status"], "queued")



if __name__ == "__main__":
    unittest.main()

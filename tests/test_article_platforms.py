"""二十一个平台的公共约定、图片归属和明确回执的回归测试。"""
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from utils.articles.adapter import create_adapter, validate_task
from utils.articles.browser import is_uploaded_image, read_result_evidence
from utils.articles.cli import ARTICLE_PLATFORMS
from utils.articles.model import ArticleError, capabilities, validate_options
from utils.articles.platforms import PLATFORMS


class PlatformContractTests(unittest.TestCase):
    def test_twenty_one_platforms_keep_account_types_and_adapter_availability_consistent(self):
        """API、CLI、执行器覆盖一致，企鹅号绝不能复用视频号账号。"""
        expected = {"douyin": 3, "bilibili": 6, "baijiahao": 5, "toutiao": 7,
                    "weibo": 10, "zhihu": 9, "qiehao": 11, "sohu": 8,
                    "yidian": 12, "dayu": 13, "netease": 14, "acfun": 15,
                    "kuaichuan": 16, "xueqiu": 17, "jingdong": 18, "douban": 19,
                    "csdn": 20, "jianshu": 21, "chejiahao": 22, "yiche": 23, "dongchedi": 24}
        self.assertEqual(set(ARTICLE_PLATFORMS), set(expected))
        self.assertEqual({item["platform"]: item["account_type"] for item in capabilities()}, expected)
        self.assertEqual(len(set(expected.values())), len(expected))
        for platform in expected:
            with self.subTest(platform=platform):
                snapshot = {"platform": platform, "title": "多平台独立文章发布自动化测试标题",
                            "mode": "preview", "options": {}, "tags": []}
                self.assertIsNot(PLATFORMS[platform].get("available"), False)
                adapter = create_adapter(snapshot, Path("测试账号.json"), None)
                self.assertEqual(adapter.platform, platform)
        with self.assertRaisesRegex(ValueError, "不支持"):
            create_adapter({"platform": "unknown"}, Path("账号.json"), None)

    def test_implementation_is_not_reported_as_live_verified(self):
        """离线实现与真实发布验收分开，能力清单不伪造验收记录。"""
        for item in capabilities():
            self.assertFalse(item["scheduled"])
            self.assertIn("content_kind", item)
            self.assertEqual(set(item["verification"]), {"preview", "submitted", "published"})
            self.assertEqual(item["format_fallbacks"]["table"], "image")
            if item["platform"] == "douyin":
                self.assertTrue(all(item["verification"].values()))
                self.assertIn("话题、声明", item["verification_scope"])
                self.assertEqual(item["verification_date"], "2026-10-01")
            else:
                self.assertFalse(item["live_verified"])
                self.assertFalse(any(item["verification"].values()))
                self.assertEqual(item["verification_date"], "")
                self.assertEqual(item["verification_url"], "")

    def test_platform_options_cannot_be_ignored_or_truncated(self):
        """摘要超限、错误声明和不存在的平台选项必须在提交前拒绝。"""
        with self.assertRaisesRegex(ArticleError, "30"):
            validate_options("douyin", {"summary": "字" * 31})
        with self.assertRaisesRegex(ArticleError, "不支持"):
            validate_options("bilibili", {"category": "自动选择"})
        with self.assertRaises(ArticleError):
            validate_options("weibo", {"summary": 123})
        with self.assertRaisesRegex(ArticleError, "布尔"):
            validate_options("baijiahao", {"ai_generated": "false"})
        validate_options("baijiahao", {"ai_generated": False})
        validate_options("weibo", {"summary": "", "publish_text": ""})

    def test_required_cover_applies_to_new_platforms(self):
        options = {"acfun": {"category": "生活"}, "csdn": {"summary": "测试摘要", "create_type": "原创"}}
        for platform in ("douyin", "weibo", "yidian", "netease", "acfun", "kuaichuan", "jingdong", "csdn"):
            with self.subTest(platform=platform), self.assertRaisesRegex(ValueError, "封面"):
                validate_task({"platform": platform, "title": "多平台独立文章发布自动化测试标题", "mode": "preview",
                               "content_html": "<p>正文</p>", "options": options.get(platform, {}),
                               "tags": ["技术"] if platform == "csdn" else []}, {})

    def test_jingdong_cover_compares_image_identity_not_only_asset_id(self):
        """外部导入或迁移产生不同 ID 时，相同文件摘要仍不能绕过首图限制。"""
        from utils.articles.model import validate_platform_cover
        cover = {"id": "cover-image", "width": 700, "height": 490,
                 "size": 2048, "sha256": "same-image-digest"}
        body = {"id": "different-body-image", "width": 700, "height": 490,
                "size": 2048, "sha256": "same-image-digest"}
        with self.assertRaises(ArticleError):
            validate_platform_cover("jingdong", cover, body)
        validate_platform_cover("jingdong", cover, {**body, "sha256": "different-image-digest"})

    def test_automotive_options_require_uploaded_cover_ids_and_preserve_false(self):
        """汽车平台竖封面不是可省略的文本项；False 仍是明确的原生开关值。"""
        for platform in ("chejiahao", "yiche", "dongchedi"):
            base = {"agree_upload_terms": True} if platform == "chejiahao" else {}
            for options in ({}, {"vertical_cover_asset_id": " "}, {"vertical_cover_asset_id": False}):
                with self.subTest(platform=platform, options=options), self.assertRaisesRegex(ArticleError, "竖版封面"):
                    validate_options(platform, {**base, **options})
            validate_options(platform, {**base, "vertical_cover_asset_id": "uploaded-image-id"})
        for platform, name in (("chejiahao", "original"), ("chejiahao", "first_publish"),
                               ("yiche", "allow_forward"), ("yiche", "allow_abstract")):
            valid = {"vertical_cover_asset_id": "uploaded-image-id", name: False}
            if platform == "chejiahao":
                valid["agree_upload_terms"] = True
            validate_options(platform, valid)
            with self.subTest(platform=platform, field=name), self.assertRaisesRegex(ArticleError, "布尔"):
                validate_options(platform, {**valid, name: "false"})
        for declaration in ("内容无需标注", "含AI生成内容", "含虚构演绎内容", "内容含营销信息", "个人观点，仅供参考"):
            validate_options("yiche", {"vertical_cover_asset_id": "uploaded-image-id", "declaration": declaration})
        for declaration in ("不声明", "AI生成", "内容来源网络", "引用站内", "个人观点"):
            with self.subTest(declaration=declaration), self.assertRaisesRegex(ArticleError, "不受支持"):
                validate_options("yiche", {"vertical_cover_asset_id": "uploaded-image-id", "declaration": declaration})

    def test_chejiahao_upload_terms_cannot_be_omitted_or_coerced_to_true(self):
        """原生上传协议必须明确同意，数字/字符串真值不能冒充同意。"""
        base = {"vertical_cover_asset_id": "uploaded-image-id"}
        for agreement in (None, False, "true", 1):
            options = base if agreement is None else {**base, "agree_upload_terms": agreement}
            with self.subTest(agreement=agreement), self.assertRaisesRegex(ArticleError, "同意"):
                validate_options("chejiahao", options)
        for content_type in ("非商业内容", "商业内容"):
            validate_options("chejiahao", {**base, "agree_upload_terms": True, "content_type": content_type})
        with self.assertRaisesRegex(ArticleError, "不受支持"):
            validate_options("chejiahao", {**base, "agree_upload_terms": True, "content_type": "自动决定"})

    def test_chejiahao_title_weight_matches_official_utf16_unit_boundaries(self):
        """U+0100 仍计半字，U+0101 计一字，代理对不能误当一个计数字符。"""
        from utils.articles.model import validate_title_characters, weighted_character_count
        self.assertEqual(weighted_character_count("A\u0100\u0101🚗"), 4)
        validate_title_characters("chejiahao", "\u0100" * 12)
        validate_title_characters("chejiahao", "\u0101" * 6)
        # 计数通过不代表字符合法：官网 FU 另拒 emoji 和指定符号。
        for title in ("\u0100" * 11, "\u0101" * 5, "🚗" * 3, "🚗" * 16, "车家标题测试☀", "车家标题测试⟿"):
            with self.subTest(title=title), self.assertRaisesRegex(ArticleError, "标题"):
                validate_title_characters("chejiahao", title)

    def test_yiche_reprint_declaration_requires_explicit_http_source(self):
        """原生转载声明必须带来源；旧版声明不静默转换，非法 URL 不进入浏览器。"""
        options = {"vertical_cover_asset_id": "uploaded-image-id", "declaration": "内容为转载"}
        for source in (None, "", " ", "javascript:alert(1)", "file:///tmp/article", "https:///article",
                       "https://user:password@example.com/article"):
            candidate = options if source is None else {**options, "source_url": source}
            with self.subTest(source=source), self.assertRaisesRegex(ArticleError, "来源"):
                validate_options("yiche", candidate)
        validate_options("yiche", {**options, "source_url": "https://example.com/article"})

    def test_yiche_vertical_cover_width_size_and_ratio_limits_are_independent(self):
        """宽度与文件大小边界包含等号，容差不能绕过独立的宽度限制。"""
        from utils.articles.model import validate_option_asset
        field = next(field for field in PLATFORMS["yiche"]["option_fields"] if field["name"] == "vertical_cover_asset_id")
        valid = {"width": 5000, "height": 6667, "size": 10 * 1024 * 1024, "mime_type": "image/png"}
        validate_option_asset(field, valid)
        for changed in ({"width": 5001, "height": 6668}, {"size": 10 * 1024 * 1024 + 1},
                        {"width": 762, "height": 1000}, {"mime_type": "image/webp"}):
            with self.subTest(changed=changed), self.assertRaises(ArticleError):
                validate_option_asset(field, {**valid, **changed})

    def test_jingdong_category_requires_complete_three_level_path(self):
        """显式分类必须完整，不能把一级标签或空分支当作已选分类。"""
        for category in ("生活", "生活/居家", "生活//好物", "生活/ /好物", "生活/居家/好物/其他"):
            with self.subTest(category=category), self.assertRaisesRegex(ArticleError, "三级"):
                validate_options("jingdong", {"category": category})
        validate_options("jingdong", {"category": "生活/居家/好物"})
        validate_options("jingdong", {})

    def test_new_platform_required_fields_and_semantics_are_validated(self):
        """必填分类、创作类型和摘要不能空缺；公开范围和原创声明保留原生语义。"""
        invalid = [
            ("acfun", {}, "分类"), ("acfun", {"category": " "}, "分类"),
            ("acfun", {"category": "生活", "summary": "字" * 201}, "200"),
            ("csdn", {"create_type": "原创"}, "摘要"),
            ("csdn", {"summary": "有效摘要"}, "创作类型"),
            ("csdn", {"summary": "有效摘要", "create_type": "抄录"}, "不受支持"),
            ("xueqiu", {"visibility": "好友可见"}, "不受支持"),
            ("douban", {"visibility": "好友可见"}, "不受支持"),
            ("jianshu", {"statement": "原创内容"}, "不支持"),
        ]
        for platform, options, message in invalid:
            with self.subTest(platform=platform, options=options), self.assertRaisesRegex(ArticleError, message):
                validate_options(platform, options)
        for platform in ("netease", "kuaichuan", "douban"):
            validate_options(platform, {"original": False})
            with self.subTest(platform=platform), self.assertRaisesRegex(ArticleError, "布尔"):
                validate_options(platform, {"original": "false"})
        for platform in ("xueqiu", "douban"):
            validate_options(platform, {"visibility": "仅自己可见"})

    def test_csdn_reprints_and_translations_require_valid_source(self):
        """转载来源不接受空值、脚本、文件地址或 URL 内的账号凭据。"""
        for create_type in ("转载", "翻译"):
            for source in ("", " ", "javascript:alert(1)", "file:///tmp/article", "https:///article",
                           "https://user:password@example.com/article"):
                with self.subTest(create_type=create_type, source=source), self.assertRaisesRegex(ArticleError, "链接"):
                    validate_options("csdn", {"summary": "有效摘要", "create_type": create_type, "source_url": source})
            validate_options("csdn", {"summary": "有效摘要", "create_type": create_type,
                                      "source_url": "https://example.com/article"})

    def test_douyin_native_limits_and_explicit_link_conversion(self):
        """平台已核实的正文、图片、话题上限与链接策略不可静默绕过。"""
        snapshot = {"platform": "douyin", "title": "测试文章", "mode": "preview", "content_html": "<p>正文</p>"}
        for changes, message in (
            ({"content_html": "<p>" + "字" * 20001 + "</p>"}, "20000"),
            ({"content_html": '<img data-asset-id="图片">' * 31}, "30"),
            ({"tags": [str(i) for i in range(6)]}, "5"),
            ({"content_html": '<p><a href="https://example.org">原文</a></p>'}, "超链接"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                validate_task({**snapshot, **changes}, {})
        validate_options("douyin", {"links_as_text": True})
        with self.assertRaisesRegex(ArticleError, "布尔"):
            validate_options("douyin", {"links_as_text": "true"})

    def test_new_platform_image_hosts_reject_lookalikes_and_local_previews(self):
        """只认所属平台已上传图片，外链和相似恶意域名不能冒充完成。"""
        hosts = {"douyin": "p3.douyinpic.com", "bilibili": "i0.hdslb.com",
                 "weibo": "wx1.sinaimg.cn", "qiehao": "inews.gtimg.com"}
        for platform, host in hosts.items():
            self.assertTrue(is_uploaded_image({"src": f"https://{host}/a.jpg", "ready": True}, platform))
            for source in (f"https://{host}.example.com/a.jpg", f"blob:https://{host}/local",
                           "https://www.yinzon.com/未上传.jpg", f"https://{host}/pending.jpg"):
                ready = not source.endswith("pending.jpg")
                self.assertFalse(is_uploaded_image({"src": source, "ready": ready}, platform))


class NativeReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_public_article_url_requires_matching_title(self):
        """新平台公共链接必须同时出现原稿标题；仅跳转地址不能算已发表。"""
        urls = {"douyin": "https://www.douyin.com/article/123456",
                "bilibili": "https://www.bilibili.com/opus/123456",
                "weibo": "https://weibo.com/ttarticle/p/show?id=230940123456",
                "qiehao": "https://new.qq.com/rain/a/20261001A12345"}
        for platform, url in urls.items():
            page = MagicMock(url=url)
            page.locator.return_value.inner_text = AsyncMock(return_value="多平台文章测试 正文")
            page.locator.return_value.evaluate_all = AsyncMock(return_value=[])
            result = await read_result_evidence(page, platform, "多平台文章测试")
            self.assertEqual(result["status"], "published")
            self.assertEqual(result["platform_url"], url)
            result = await read_result_evidence(page, platform, "另一篇文章")
            self.assertEqual(result["status"], "unknown")


if __name__ == "__main__":
    unittest.main()

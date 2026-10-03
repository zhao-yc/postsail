"""文章适配安全边界测试；可选本地浏览器用例不访问外部平台。"""
import base64
import os
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from utils.articles.adapter import (_submit_once, _selected_statement, _create_app, _verify_tags,
                                   _verify_title, _verify_final_body, validate_task)
from utils.articles.browser import (
    PreparationError, insert_body_images, is_uploaded_image, paste_rich_html,
    prepare_document, read_result_evidence, install_preview_guard, launch_article_browser,
    prepare_and_paste_document,
    receipt_status, normalize_code_text, PreparedDocument, body_sequence, _PREVIEW_GUARD,
    install_native_preview_request_guard,
)


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jDlsAAAAASUVORK5CYII=")


class ArticleValidationTests(unittest.TestCase):
    """检验平台约束和未实现定时不会静默降级。"""

    def snapshot(self, **changes):
        result = dict(platform="zhihu", title="测试文章", content_html="<p>正文</p>",
                      mode="preview", cover_asset_id=None)
        result.update(changes)
        return result

    def test_title_overflow_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "1-30"):
            validate_task(self.snapshot(platform="toutiao", title="字" * 31), {})

    def test_missing_body_image_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "素材不存在"):
            validate_task(self.snapshot(content_html='<p>正文<img data-asset-id="missing"></p>'), {})

    def test_external_image_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "素材库"):
            validate_task(self.snapshot(content_html='<img src="https://example.org/a.png">'), {})

    def test_baijiahao_requires_cover(self):
        with self.assertRaisesRegex(ValueError, "封面"):
            validate_task(self.snapshot(platform="baijiahao"), {})

    def test_local_image_url_is_not_upload_confirmation(self):
        for src in ("blob:https://zhihu.com/a", "data:image/png;base64,x", "file:///tmp/a.png",
                    "http://127.0.0.1/a.png", "http://localhost/a.png"):
            self.assertFalse(is_uploaded_image(dict(src=src, ready=True)))
        self.assertTrue(is_uploaded_image(dict(src="https://pic.zhimg.com/a.png", ready=True)))
        self.assertFalse(is_uploaded_image(dict(src="https://pic.zhimg.com/a.png", ready=False)))
        self.assertTrue(is_uploaded_image(dict(src="https://pic.zhimg.com/a.png", ready=True), "zhihu"))
        self.assertFalse(is_uploaded_image(dict(src="https://yinzon.com/a.png", ready=True), "zhihu"))
        self.assertFalse(is_uploaded_image(dict(src="https://pic.zhimg.com.evil.test/a.png", ready=True), "zhihu"))

    def test_legacy_articles_reject_schedule(self):
        from uploader.baijiahao_uploader.main import BaiJiaHaoArticle
        from uploader.zhihu_uploader.main import ZhiHuArticle
        from uploader.toutiao_uploader.main import TouTiaoArticle
        from uploader.sohu_uploader.main import SoHuArticle
        for klass in (BaiJiaHaoArticle, ZhiHuArticle, TouTiaoArticle, SoHuArticle):
            with self.subTest(klass=klass.__name__), self.assertRaisesRegex(ValueError, "定时"):
                klass("有效文章标题", "正文", [], datetime(2026, 10, 1), "account.json")

    def test_unknown_requested_statement_cannot_fall_back(self):
        for platform in ("zhihu", "toutiao", "sohu"):
            with self.subTest(platform=platform), self.assertRaisesRegex(ValueError, "不能忽略或回退"):
                _create_app(self.snapshot(platform=platform, title="有效文章标题", options={"statement": "未知声明"}), Path("account.json"), None)

    @staticmethod
    def legacy_article_classes():
        """历史文章入口必须与新接口使用一致的标题范围。"""
        from uploader.baijiahao_uploader.main import BaiJiaHaoArticle
        from uploader.zhihu_uploader.main import ZhiHuArticle
        from uploader.toutiao_uploader.main import TouTiaoArticle
        from uploader.sohu_uploader.main import SoHuArticle
        return [(BaiJiaHaoArticle, 2, 64), (ZhiHuArticle, 1, 100),
                (TouTiaoArticle, 1, 30), (SoHuArticle, 5, 72)]

    def test_legacy_articles_reject_empty_title(self):
        for klass, _minimum, _maximum in self.legacy_article_classes():
            for title in (None, "", "  \n "):
                with self.subTest(klass=klass.__name__, title=title), self.assertRaisesRegex(ValueError, "标题"):
                    klass(title, "正文", [], 0, "account.json")

    def test_legacy_articles_reject_oversized_title(self):
        for klass, _minimum, maximum in self.legacy_article_classes():
            with self.subTest(klass=klass.__name__), self.assertRaisesRegex(ValueError, "标题"):
                klass("字" * (maximum + 1), "正文", [], 0, "account.json")

    def test_legacy_articles_preserve_valid_title_boundaries(self):
        for klass, minimum, maximum in self.legacy_article_classes():
            for length in (minimum, maximum):
                with self.subTest(klass=klass.__name__, length=length):
                    title = "字" * length
                    app = klass("  " + title + "  ", "正文", [], 0, "account.json")
                    self.assertEqual(app.title, title)

    def test_receipt_phrases_require_clear_statement_boundary(self):
        for text in ("发布成功", "发布成功，等待审核", "提交成功。请查看内容管理", "✅ 发布成功！"):
            with self.subTest(text=text):
                self.assertIsNotNone(receipt_status(text))
        for text in ("发布成功后请查看内容管理", "审核中表示还没通过", "请等待审核", "提交失败时请重试"):
            with self.subTest(text=text):
                self.assertIsNone(receipt_status(text))

    def test_code_normalization_preserves_indentation_and_line_breaks(self):
        expected = 'def demo():\n    print("中文")\n    return 1'
        self.assertEqual(normalize_code_text('\r\n' + expected.replace('\n', '\r\n') + '\r\n'), expected)
        self.assertNotEqual(normalize_code_text(expected), normalize_code_text(expected.replace('    ', '')))
        self.assertNotEqual(normalize_code_text(expected), normalize_code_text(expected.replace('\n', '')))


class ArticleSubmissionTests(unittest.IsolatedAsyncioTestCase):
    """提交超时不再次点击，反馈来源与公开文章状态分别判断。"""

    async def test_click_timeout_only_attempts_once(self):
        button = MagicMock()
        button.is_visible = AsyncMock(return_value=True)
        button.is_enabled = AsyncMock(return_value=True)
        button.scroll_into_view_if_needed = AsyncMock()
        button.click = AsyncMock(side_effect=TimeoutError("模拟提交后超时"))
        found, empty = MagicMock(), MagicMock()
        found.count = AsyncMock(return_value=1)
        found.nth.return_value = button
        empty.count = AsyncMock(return_value=0)
        page = MagicMock()
        page.get_by_role.side_effect = [found, empty]
        marks = []
        with self.assertRaises(TimeoutError):
            await _submit_once(page, lambda: marks.append("已标记提交边界"))
        self.assertEqual(marks, ["已标记提交边界"])
        button.click.assert_awaited_once()

    async def test_multiple_publish_buttons_do_not_submit(self):
        button = MagicMock()
        button.is_visible = AsyncMock(return_value=True)
        button.is_enabled = AsyncMock(return_value=True)
        found, empty = MagicMock(), MagicMock()
        found.count = AsyncMock(return_value=2)
        found.nth.return_value = button
        empty.count = AsyncMock(return_value=0)
        page = MagicMock()
        page.get_by_role.side_effect = [found, empty]
        marks = []
        with self.assertRaises(PreparationError):
            await _submit_once(page, lambda: marks.append(True))
        self.assertEqual(marks, [])

    def result_page(self, body="操作说明：发布成功后进入内容管理", alerts=None,
                    headings_text=None, url="https://creator.test/editor"):
        page = MagicMock()
        page.url = url
        body_locator, feedback, headings, challenges = MagicMock(), MagicMock(), MagicMock(), MagicMock()
        body_locator.inner_text = AsyncMock(return_value=body)
        feedback.evaluate_all = AsyncMock(return_value=alerts or [])
        headings.evaluate_all = AsyncMock(return_value=headings_text or [])
        challenges.evaluate_all = AsyncMock(return_value=[])
        page.locator.side_effect = [body_locator, feedback, challenges, headings]
        return page

    async def test_help_text_is_not_publish_confirmation(self):
        result = await read_result_evidence(self.result_page(), "zhihu", "测试文章")
        self.assertEqual(result["status"], "unknown")

    async def test_success_toast_is_submitted_not_published(self):
        result = await read_result_evidence(self.result_page(alerts=["发布成功，等待审核"]), "zhihu")
        self.assertEqual(result["status"], "submitted")

    async def test_explanatory_toast_is_not_confirmation(self):
        result = await read_result_evidence(self.result_page(alerts=["发布成功后请到内容管理查看"]), "zhihu")
        self.assertEqual(result["status"], "unknown")

    async def test_explicit_external_heading_is_submitted(self):
        result = await read_result_evidence(self.result_page(headings_text=["发布成功"]), "zhihu", "测试文章")
        self.assertEqual(result["status"], "submitted")

    async def test_original_title_is_not_a_receipt(self):
        result = await read_result_evidence(self.result_page(headings_text=["发布成功"]), "zhihu", "发布成功")
        self.assertEqual(result["status"], "unknown")

    async def test_matching_public_article_is_published(self):
        result = await read_result_evidence(self.result_page(body="测试文章 正文", url="https://zhuanlan.zhihu.com/p/123456"),
                                            "zhihu", "测试文章")
        self.assertEqual(result["status"], "published")
        self.assertEqual(result["platform_id"], "123456")

    async def test_receipt_like_title_on_public_article_still_is_published(self):
        result = await read_result_evidence(self.result_page(body="发布成功 正文", url="https://zhuanlan.zhihu.com/p/123456"),
                                            "zhihu", "发布成功")
        self.assertEqual(result["status"], "published")

    async def test_public_article_with_captcha_tutorial_is_published(self):
        result = await read_result_evidence(self.result_page(body="验证码教程：如何输入验证码", url="https://zhuanlan.zhihu.com/p/123456"),
                                            "zhihu", "验证码教程")
        self.assertEqual(result["status"], "published")

    async def test_missing_chrome_falls_back_to_installed_chromium(self):
        runtime = MagicMock()
        runtime.chromium.launch = AsyncMock(side_effect=[RuntimeError("Chromium distribution 'chrome' is not found"), "浏览器"])
        self.assertEqual(await launch_article_browser(runtime, True), "浏览器")
        self.assertEqual(runtime.chromium.launch.await_count, 2)
        self.assertNotIn("channel", runtime.chromium.launch.await_args_list[-1].kwargs)

    async def test_other_launch_failures_are_not_masked(self):
        runtime = MagicMock()
        runtime.chromium.launch = AsyncMock(side_effect=RuntimeError("模拟浏览器崩溃"))
        with self.assertRaisesRegex(RuntimeError, "崩溃"):
            await launch_article_browser(runtime, True)
        runtime.chromium.launch.assert_awaited_once()

    async def test_explicit_missing_path_does_not_launch(self):
        runtime = MagicMock()
        runtime.chromium.launch = AsyncMock()
        with self.assertRaisesRegex(PreparationError, "路径不存在"):
            await launch_article_browser(runtime, True, "/不存在的浏览器/chrome")
        runtime.chromium.launch.assert_not_awaited()

    async def test_only_preparation_check_failure_triggers_png_retry(self):
        first, second = MagicMock(), MagicMock()
        with patch("utils.articles.browser.prepare_document", new=AsyncMock(side_effect=[first, second])) as prepare, \
             patch("utils.articles.browser.paste_rich_html", new=AsyncMock(side_effect=[PreparationError("丢失表格"), None])) as paste:
            result = await prepare_and_paste_document(None, None, None, "<p>正文</p>", {}, Path("/tmp"), "sans-serif")
        self.assertIs(result, second)
        self.assertEqual([call.kwargs["preserve_blocks"] for call in prepare.await_args_list], [True, False])
        self.assertEqual(paste.await_count, 2)

    async def test_clipboard_permission_error_does_not_retry(self):
        with patch("utils.articles.browser.prepare_document", new=AsyncMock(return_value=MagicMock())) as prepare, \
             patch("utils.articles.browser.paste_rich_html", new=AsyncMock(side_effect=RuntimeError("剪贴板权限拒绝"))) as paste:
            with self.assertRaisesRegex(RuntimeError, "权限"):
                await prepare_and_paste_document(None, None, None, "<p>正文</p>", {}, Path("/tmp"), "sans-serif")
        prepare.assert_awaited_once()
        paste.assert_awaited_once()


class ArticleFinalBodyTests(unittest.IsolatedAsyncioTestCase):
    """选项操作后重新校验正文，测试本身不启动浏览器或使用剪贴板。"""

    async def verify_readback(self, text, sequence=None, images=None, urls=None,
                              platform="douyin", tags=None, topics=None, image_verifier=None):
        """仅替代浏览器读回，保持生产比较及拒绝路径不变。"""
        urls = urls or []
        document = PreparedDocument("<p>正文</p>", "<p>正文</p>", "正文",
                                    [Path("photo.png")] * len(urls), [], [], urls)
        editor = MagicMock()
        editor.evaluate = AsyncMock(return_value=images or [])
        editor.locator.return_value.evaluate_all = AsyncMock(return_value=topics or [])
        with patch("utils.articles.browser.body_sequence", AsyncMock(side_effect=[text, sequence or text])), \
                patch("utils.articles.adapter.verify_rich_structure", AsyncMock()):
            await _verify_final_body(editor, document, platform, tags, image_verifier=image_verifier)

    async def test_local_image_preview_requires_native_upload_receipt(self):
        urls = ["data:image/png;base64,fixture"]
        images = [{"src": urls[0], "ready": True}]
        with self.assertRaisesRegex(PreparationError, "图片读回不完整"):
            await self.verify_readback("正文", images=images, urls=urls)
        verifier = AsyncMock()
        await self.verify_readback("正文", images=images, urls=urls, image_verifier=verifier)
        verifier.assert_awaited_once()
        verifier.side_effect = PreparationError("未收到本次上传回执")
        with self.assertRaisesRegex(PreparationError, "本次上传回执"):
            await self.verify_readback("正文", images=images, urls=urls, image_verifier=verifier)

    async def test_native_upload_verifier_cannot_bypass_image_integrity(self):
        verifier = AsyncMock()
        url = "blob:https://mp.yiche.com/fixture"
        for images, sequence, message in (
                ([{"src": url, "ready": False}], "正文", "图片读回不完整"),
                ([{"src": url, "ready": True}] * 2, "正文", "图片读回不完整"),
                ([{"src": url + "changed", "ready": True}], "正文", "图片地址或顺序"),
                ([{"src": url, "ready": True}], "正文OMNIPOSTIMAGE0000END", "相邻段落")):
            with self.subTest(message=message), self.assertRaisesRegex(PreparationError, message):
                await self.verify_readback("正文", images=images, urls=[url], sequence=sequence,
                                           image_verifier=verifier)

    async def test_native_document_reader_preserves_shared_final_checks(self):
        url = "https://car.autoimg.cn/body.png"
        document = PreparedDocument("", "<p>首段OMNIPOSTIMAGE0000END尾段</p>", "首段尾段",
                                    [Path("photo.png")], [], [], [url])
        reader = AsyncMock(return_value={"text": "首段尾段", "sequence": "首段OMNIPOSTIMAGE0000END尾段",
                                         "images": [{"src": url, "ready": True}]})
        editor = MagicMock()
        await _verify_final_body(editor, document, "chejiahao", document_reader=reader,
                                 rich_verifier=AsyncMock())
        for field, value, error in (
                ("text", "首段尾段图片上传失败", "正文不一致"),
                ("sequence", "OMNIPOSTIMAGE0000END首段尾段", "相邻段落"),
                ("images", [{"src": url, "ready": True}] * 2, "图片读回不完整"),
                ("images", [{"src": url + "other", "ready": True}], "图片地址或顺序")):
            state = dict(reader.return_value)
            state[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(PreparationError, error):
                await _verify_final_body(editor, document, "chejiahao", document_reader=AsyncMock(return_value=state),
                                         rich_verifier=AsyncMock())

    async def test_missing_body_is_rejected(self):
        with self.assertRaisesRegex(PreparationError, "正文不一致"):
            await self.verify_readback("正")

    async def test_warning_after_body_is_rejected(self):
        """平台警告出现在原正文之后时，也不能被当作允许追加的话题。"""
        with self.assertRaises(PreparationError):
            await self.verify_readback("正文图片上传失败，请重新上传")

    async def test_only_confirmed_requested_topic_suffix_is_allowed(self):
        """三个正文话题平台只允许真实话题节点组成的精确请求后缀。"""
        for platform in ("baijiahao", "toutiao", "bilibili"):
            with self.subTest(platform=platform):
                await self.verify_readback("正文#测试##文章#", platform=platform,
                                           tags=["测试", "文章"], topics=["#测试#", "#文章#"])
                for text, topics in (("正文#测试##文章#警告", ["#测试#", "#文章#"]),
                                     ("正文#测试##文章#", []),
                                     ("正文#文章##测试#", ["#文章#", "#测试#"]),
                                     ("正文#测试##其他#", ["#测试#", "#其他#"])):
                    with self.assertRaises(PreparationError):
                        await self.verify_readback(text, platform=platform,
                                                   tags=["测试", "文章"], topics=topics)

    async def test_other_platforms_do_not_allow_topic_text_suffix(self):
        for platform in ("douyin", "zhihu", "weibo", "qiehao", "sohu"):
            with self.subTest(platform=platform), self.assertRaises(PreparationError):
                await self.verify_readback("正文#测试#", platform=platform,
                                           tags=["测试"], topics=["#测试#"])

    async def test_uploaded_image_order_is_rejected(self):
        urls = ["https://p3.douyinpic.com/a.png", "https://p3.douyinpic.com/b.png"]
        images = [dict(src=url, ready=True) for url in reversed(urls)]
        with self.assertRaisesRegex(PreparationError, "图片地址或顺序"):
            await self.verify_readback("正文", images=images, urls=urls)

    async def test_image_moved_before_body_is_rejected(self):
        url = "https://p3.douyinpic.com/a.png"
        with self.assertRaisesRegex(PreparationError, "相邻段落"):
            await self.verify_readback("正文", sequence="OMNIPOSTIMAGE0000END正文",
                                       images=[dict(src=url, ready=True)], urls=[url])


@unittest.skipUnless(os.environ.get("OMNIPOST_BROWSER_TESTS") == "1", "本地浏览器用例需显式启用")
class ArticleLocalBrowserTests(unittest.IsolatedAsyncioTestCase):
    """通过受控 HTTPS 页面模拟编辑器上传，不连接任何真实平台。"""

    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        import conf
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.runtime = await async_playwright().start()
        executable = getattr(conf, "LOCAL_CHROME_PATH", "")
        options = dict(headless=True)
        if executable:
            options["executable_path"] = executable
        self.browser = await self.runtime.chromium.launch(**options)
        self.context = await self.browser.new_context(viewport={"width": 1440, "height": 1000})
        self.page = await self.context.new_page()
        self.render_page = await self.context.new_page()

        async def fixture(route):
            if route.request.url.endswith("uploaded.png"):
                await route.fulfill(body=PNG, content_type="image/png")
                return
            await route.fulfill(content_type="text/html; charset=utf-8", body=r"""<!doctype html><html><head><meta charset="utf-8"></head><body>
                <div id="editor" contenteditable="true" style="min-height:600px"></div>
                <button onclick="window.submissions=(window.submissions||0)+1">发布</button>
                <script>document.getElementById('editor').addEventListener('paste',event=>{
                    if(!event.clipboardData.files.length){
                        if(window.dropBlocks||window.preserveBlocks||window.flattenCode){event.preventDefault();
                            const range=getSelection().getRangeAt(0);range.deleteContents();
                            const content=range.createContextualFragment(event.clipboardData.getData('text/html'));
                            if(window.dropBlocks)content.querySelectorAll('table,pre').forEach(el=>
                                el.replaceWith(document.createTextNode(el.textContent)));
                            if(window.flattenCode)content.querySelectorAll('pre').forEach(pre=>{
                                const node=pre.querySelector('code')||pre;
                                node.textContent=node.textContent.split('\n').map(line=>line.replace(/^[\t ]+/,'')).join('\n');
                            });
                            range.insertNode(content);
                        }return;
                    }event.preventDefault();
                    const selection=getSelection(),range=selection.getRangeAt(0);
                    range.deleteContents();const img=document.createElement('img');
                    img.src='https://fixture.test/uploaded.png';
                    if(window.insertWrong){document.getElementById('editor').appendChild(img);}
                    else{range.insertNode(img);}
                });</script></body></html>""")

        await self.page.route("https://fixture.test/**", fixture)
        await self.page.goto("https://fixture.test/editor")

    async def asyncTearDown(self):
        await self.context.close()
        await self.browser.close()
        await self.runtime.stop()
        self.directory.cleanup()

    async def test_rich_paste_and_native_picture_upload(self):
        path = self.root / "photo.png"
        path.write_bytes(PNG)
        assets = {"photo": dict(path=str(path), mime_type="image/png")}
        content = ('<h1>一级</h1><h2>小标题</h2><h3>三级</h3><h4>四级</h4><h5>五级</h5><h6>六级</h6>'
                   '<blockquote>引用</blockquote><p>第一段<strong>加粗</strong><em>斜体</em><u>下划线</u>'
                   '<s>删除线</s><a href="https://example.org/article">链接</a></p>'
                   '<p><img data-asset-id="photo"></p><ul><li>列表</li></ul><ol><li>编号</li></ol>')
        document = await prepare_document(self.render_page, content, assets, self.root, "sans-serif")
        editor = self.page.locator("#editor")
        await paste_rich_html(self.page, editor, document)
        await insert_body_images(self.page, editor, self.render_page, document)
        self.assertEqual(await editor.locator("h2").inner_text(), "小标题")
        self.assertEqual(await editor.locator("img").get_attribute("src"), "https://fixture.test/uploaded.png")
        self.assertNotIn("OMNIPOSTIMAGE", await editor.inner_text())

    async def test_long_code_becomes_multiple_png_segments(self):
        content = "<p>代码示例</p><pre><code>" + "\n".join(f"第 {i} 行代码" for i in range(150)) + "</code></pre>"
        document = await prepare_document(self.render_page, content, {}, self.root, "sans-serif")
        self.assertGreater(len(document.generated_files), 2)
        self.assertNotIn("<pre", document.prepared_html)
        self.assertTrue(all(path.is_file() for path in document.image_paths))

    async def test_explicit_link_text_fallback_keeps_label_format_and_url(self):
        """抖音可选链接转换须保留加粗文字、完整地址，不改原稿。"""
        content = '<p>查看<a href="https://example.org/a?q=1&amp;b=2"><strong>原文</strong></a></p>'
        document = await prepare_document(self.render_page, content, {}, self.root, "sans-serif",
                                          links_as_text=True)
        self.assertNotIn('<a ', document.prepared_html)
        self.assertIn('<strong>原文</strong>', document.prepared_html)
        self.assertIn('https://example.org/a?q=1&b=2', document.expected_text)
        self.assertIn('<a ', content)
        unchanged = await prepare_document(self.render_page, content, {}, self.root, "sans-serif")
        self.assertIn('<a ', unchanged.prepared_html)

    async def test_douyin_picture_controls_are_excluded_without_losing_body(self):
        """仅跳过图片节点的已知编辑按钮；原正文同名文字及其他警告仍保留。"""
        editor = self.page.locator("#editor")
        await editor.evaluate("""el=>el.innerHTML='<p>正文编辑图片</p>'+
            '<div class="node-image"><img src="https://fixture.test/uploaded.png">'+
            '<button title="编辑图片">编辑图片</button><span>图片上传失败</span></div>'+
            '<button title="编辑图片">其他编辑图片</button><p>末段</p>'""")
        self.assertEqual(await body_sequence(editor, "douyin", include_images=False),
                         "正文编辑图片图片上传失败其他编辑图片末段")
        self.assertEqual(await body_sequence(editor, "douyin"),
                         "正文编辑图片OMNIPOSTIMAGE0000END图片上传失败其他编辑图片末段")
        self.assertIn("编辑图片图片上传失败", await body_sequence(editor, "zhihu"))

    async def test_jingdong_image_toolbar_does_not_hide_body_or_upload_warnings(self):
        """官方 Braft 的悬停删除图标不属于正文，警告和同名非工具节点必须保留。"""
        editor = self.page.locator("#editor")
        await editor.evaluate("""el=>el.innerHTML='<p>首段</p><div class="bf-media"><div class="bf-image">'+
            '<div class="bf-media-toolbar"><a><span>删除图标</span></a></div>'+
            '<img src="https://fixture.test/uploaded.png"><span>上传失败</span></div></div>'+
            '<p class="bf-media-toolbar">正文尾段</p>'""")
        self.assertEqual(await body_sequence(editor, "jingdong"),
                         "首段OMNIPOSTIMAGE0000END上传失败正文尾段")
        self.assertEqual(await body_sequence(editor, "jingdong", include_images=False),
                         "首段上传失败正文尾段")
        self.assertIn("删除图标", await body_sequence(editor, "zhihu"))

    async def test_dongchedi_image_counter_does_not_hide_caption_or_warning(self):
        editor = self.page.locator("#editor")
        await editor.evaluate("""el=>el.innerHTML='<p>首段</p><div class="pgc-image">'+
            '<img src="https://fixture.test/uploaded.png"><span class="pgc-img-caption-tip">0/50</span>'+
            '<span class="pgc-img-caption">图注</span><span>上传失败</span></div><p>尾段</p>'""")
        self.assertEqual(await body_sequence(editor, "dongchedi"),
                         "首段OMNIPOSTIMAGE0000END图注上传失败尾段")
        self.assertIn("0/50", await body_sequence(editor, "zhihu"))

    async def test_picture_controls_do_not_hide_image_position(self):
        """图片标记在原来的段落之间，移动节点后顺序读回应产生可见差异。"""
        editor = self.page.locator("#editor")
        await editor.evaluate("""el=>el.innerHTML='<p>首段</p><div class="node-image">'+
            '<img src="https://fixture.test/uploaded.png"><button title="编辑图片">编辑图片</button>'+
            '</div><p>尾段</p>'""")
        expected = "首段OMNIPOSTIMAGE0000END尾段"
        self.assertEqual(await body_sequence(editor, "douyin"), expected)
        await editor.evaluate("el=>el.appendChild(el.querySelector('.node-image'))")
        self.assertNotEqual(await body_sequence(editor, "douyin"), expected)

    async def test_final_douyin_body_rejects_warning_missing_text_and_image_changes(self):
        """不使用剪贴板：模拟平台图片节点，并检查选项之后的正文变化。"""
        urls = ["https://p3.douyinpic.com/a.png", "https://p3.douyinpic.com/b.png"]
        await self.page.route("https://p3.douyinpic.com/**", lambda route: route.fulfill(
            body=PNG, content_type="image/png"))
        document = PreparedDocument("", "<p>首段OMNIPOSTIMAGE0000END</p>"
                                    "<p>中段OMNIPOSTIMAGE0001END</p><p>尾段</p>",
                                    "首段中段尾段", [self.root / "a.png", self.root / "b.png"], [], [], urls)
        html = ('<p>首段</p><div class="node-image"><img src="' + urls[0] + '">'
                '<button title="编辑图片">编辑图片</button></div><p>中段</p>'
                '<div class="node-image"><img src="' + urls[1] + '">'
                '<button title="编辑图片">编辑图片</button></div><p>尾段</p>')
        editor = self.page.locator("#editor")
        await editor.evaluate("(el,html)=>el.innerHTML=html", html)
        await editor.evaluate("el=>Promise.all(Array.from(el.querySelectorAll('img')).map(img=>img.decode()))")
        await _verify_final_body(editor, document, "douyin")
        for modification, message in (
                ("el=>el.insertAdjacentHTML('beforeend','<span>图片上传失败</span>')", "正文不一致"),
                ("el=>el.querySelector('p').remove()", "正文不一致"),
                ("el=>el.querySelector('img').src='https://p3.douyinpic.com/b.png'", "图片地址或顺序"),
                # 移到首段之前，保持两张图片地址顺序，单独覆盖图片与段落的相对位置。
                ("el=>el.insertBefore(el.querySelector('.node-image'),el.firstChild)", "相邻段落")):
            with self.subTest(message=message):
                await editor.evaluate("(el,html)=>el.innerHTML=html", html)
                await editor.evaluate(modification)
                await editor.evaluate("el=>Promise.all(Array.from(el.querySelectorAll('img')).map(img=>img.decode()))")
                with self.assertRaisesRegex(PreparationError, message):
                    await _verify_final_body(editor, document, "douyin")

    async def test_link_text_fallback_keeps_empty_labels_and_existing_url_labels(self):
        """空标签仍保留目标地址，已经以地址为文字的链接不会重复附加。"""
        content = '<p><a href="https://example.org/empty"></a>' \
                  '<a href="https://example.org/same">https://example.org/same</a></p>'
        document = await prepare_document(self.render_page, content, {}, self.root,
                                          "sans-serif", links_as_text=True)
        self.assertNotIn("<a ", document.prepared_html)
        self.assertIn("https://example.org/empty", document.expected_text)
        self.assertEqual(document.expected_text.count("https://example.org/same"), 1)

    async def test_preview_blocks_click_and_shortcut(self):
        await install_preview_guard(self.page)
        self.assertTrue(await self.page.evaluate("Boolean(window.__omnipostPreviewGuard)"))
        self.assertTrue(await self.page.locator("button").evaluate("el=>el.disabled"))
        await self.page.locator("button").evaluate("el=>el.click()")
        await self.page.keyboard.press("ControlOrMeta+Enter")
        self.assertEqual(await self.page.evaluate("window.submissions||0"), 0)

    async def test_preview_blocks_community_publish_controls_and_implicit_submit(self):
        """豆瓣按钮、原生 submit 与动态控件均不能越过预览，保存草稿仍可用。"""
        await self.page.set_content('''<form id="article"><button id="note">发布日记</button>
            <button id="post">发表</button><input id="input" type="submit" value="发表">
            <button id="aria" aria-label="确认投稿"><span>图标</span></button>
            <div id="custom">发布</div>
            <input id="draft" type="button" value="保存草稿"></form><script>
            window.submissions=0;window.saved=0;
            document.getElementById('article').addEventListener('click',event=>{
                if(event.target.id==='draft')window.saved++;else window.submissions++;
            });
            document.getElementById('article').addEventListener('submit',event=>{
                event.preventDefault();window.submissions++;
            });</script>''')
        await install_preview_guard(self.page)
        for control in ("note", "post", "input", "aria"):
            self.assertTrue(await self.page.locator("#" + control).is_disabled())
            await self.page.locator("#" + control).dispatch_event("click")
        await self.page.locator("#custom").dispatch_event("click")
        await self.page.locator("#article").evaluate("form=>form.requestSubmit()")
        self.assertEqual(await self.page.evaluate("window.submissions"), 0)
        await self.page.locator("#draft").click()
        self.assertEqual(await self.page.evaluate("window.saved"), 1)
        await self.page.locator("#draft").evaluate("el=>el.setAttribute('value','发布日记')")
        await self.page.wait_for_function("document.getElementById('draft').disabled")
        await self.page.locator("#draft").dispatch_event("click")
        self.assertEqual(await self.page.evaluate("window.saved"), 1)

    async def test_preview_init_script_guards_early_events_and_dynamic_buttons(self):
        """页面加载前安装保护，根节点尚未创建时不报错，加载后持续禁用动态按钮。"""
        errors = []
        self.page.on("pageerror", lambda error: errors.append(str(error)))
        await self.page.add_init_script(_PREVIEW_GUARD)
        await self.page.route("https://fixture.test/preview-init", lambda route: route.fulfill(
            content_type="text/html; charset=utf-8", body="""<!doctype html><body>
                <button id="early">发布</button><script>
                window.submissions=0;window.shortcuts=0;
                document.addEventListener('click',()=>window.submissions++);
                document.addEventListener('keydown',event=>{
                    if((event.ctrlKey||event.metaKey)&&event.key==='Enter')window.shortcuts++;
                });
                document.getElementById('early').dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));
                document.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',ctrlKey:true,bubbles:true,cancelable:true}));
                </script></body>"""))
        await self.page.goto("https://fixture.test/preview-init")
        self.assertEqual(errors, [])
        self.assertEqual(await self.page.evaluate("[window.submissions,window.shortcuts]"), [0, 0])

        self.assertTrue(await self.page.locator("#early").evaluate("el=>el.disabled"))
        await self.page.evaluate("""()=>{
            const button=document.createElement('button');button.id='late';button.textContent='确认发布';
            document.body.appendChild(button);
            const save=document.createElement('button');save.id='save';save.textContent='保存草稿';
            document.body.appendChild(save);
        }""")
        await self.page.wait_for_function("document.getElementById('late').disabled")
        self.assertEqual(await self.page.locator("#late").get_attribute("aria-disabled"), "true")
        self.assertFalse(await self.page.locator("#save").evaluate("el=>el.disabled"))
        # 再次安装不得撤销首次安装后动态节点的保护。
        await self.page.evaluate(_PREVIEW_GUARD)
        await self.page.locator("#late").dispatch_event("click")
        await self.page.keyboard.press("ControlOrMeta+Enter")
        self.assertEqual(await self.page.evaluate("[window.submissions,window.shortcuts]"), [0, 0])

    async def test_native_preview_request_guard_blocks_only_exact_douyin_publish(self):
        """真实 fetch 经过路由保护；模拟远端只接收允许的上传及认证请求。"""
        received = []

        async def remote(route):
            """记录最终到达模拟远端的请求，禁止回退到实际网络。"""
            received.append(route.request.url)
            await route.fulfill(content_type="application/json", body='{"ok":true}',
                                headers={"Access-Control-Allow-Origin": "*"})

        # 先安装模拟远端，再安装生产保护，验证保护不会向下转交提交请求。
        await self.page.route("https://creator.douyin.com/**", remote)
        self.assertTrue(await install_native_preview_request_guard(self.page, "douyin"))
        endpoint = "https://creator.douyin.com/web/api/media/aweme/create_v2/"
        for url in (endpoint, endpoint + "?test=preview"):
            result = await self.page.evaluate("""async url=>{
                try{await fetch(url,{method:'POST',body:'test'});return 'allowed';}
                catch(error){return 'blocked';}
            }""", url)
            self.assertEqual(result, "blocked")
        self.assertEqual(received, [])
        allowed = ["https://creator.douyin.com/web/api/media/upload/",
                   "https://creator.douyin.com/web/api/auth/",
                   endpoint + "other"]
        for url in allowed:
            result = await self.page.evaluate("async url=>(await fetch(url)).json()", url)
            self.assertEqual(result, {"ok": True})
        self.assertEqual(received, allowed)
        for platform in ("bilibili", "baijiahao", "toutiao", "weibo", "zhihu", "qiehao", "sohu"):
            with self.subTest(platform=platform):
                unguarded = MagicMock()
                unguarded.route = AsyncMock()
                self.assertFalse(await install_native_preview_request_guard(unguarded, platform))
                unguarded.route.assert_not_awaited()

    async def test_statement_checks_exact_selected_option(self):
        await self.page.locator("body").evaluate("""el=>{
            const group=document.createElement('div');group.className='radio-group';
            group.innerHTML='<label><input type="radio" name="source" checked>无特别声明</label>'+
                '<label><input type="radio" name="source">引用声明</label>';
            el.appendChild(group);
        }""")
        self.assertTrue(await _selected_statement(self.page, "无特别声明"))
        self.assertFalse(await _selected_statement(self.page, "引用声明"))

    async def test_title_must_be_read_back(self):
        await self.page.locator("body").evaluate("""el=>{
            const input=document.createElement('input');input.placeholder='请输入标题';el.appendChild(input);
        }""")
        await self.page.get_by_placeholder("请输入标题").fill("正确标题")
        await _verify_title(self.page, "正确标题")
        with self.assertRaisesRegex(PreparationError, "标题读回"):
            await _verify_title(self.page, "错误标题")

    async def test_plain_hash_text_is_not_selected_topic(self):
        editor = self.page.locator("#editor")
        await editor.fill("#测试")
        with self.assertRaisesRegex(PreparationError, "已选话题"):
            await _verify_tags("baijiahao", self.page, editor, ["测试"])
        await editor.evaluate("el=>el.innerHTML='<a data-bjh-box=\"topic\">#测试#</a>'")
        await _verify_tags("baijiahao", self.page, editor, ["测试"])

    async def test_topic_candidate_is_not_selected_chip(self):
        await self.page.locator("body").evaluate("""el=>{
            const suggestion=document.createElement('div');suggestion.role='listbox';
            suggestion.innerHTML='<span class="TopicTag" aria-selected="true">测试</span>';
            el.appendChild(suggestion);
        }""")
        with self.assertRaisesRegex(PreparationError, "已选话题"):
            await _verify_tags("zhihu", self.page, self.page.locator("#editor"), ["测试"])
        await self.page.locator("body").evaluate("""el=>{
            const chip=document.createElement('span');chip.className='Tag';
            chip.innerHTML='测试<button class="Tag-remove" aria-label="删除">×</button>';el.appendChild(chip);
        }""")
        await _verify_tags("zhihu", self.page, self.page.locator("#editor"), ["测试"])

    async def test_wrong_picture_position_blocks_preparation(self):
        path = self.root / "photo.png"
        path.write_bytes(PNG)
        assets = {"photo": dict(path=str(path), mime_type="image/png")}
        document = await prepare_document(self.render_page,
            '<p>第一段<img data-asset-id="photo"></p><p>图片后段落</p>', assets, self.root, "sans-serif")
        editor = self.page.locator("#editor")
        await paste_rich_html(self.page, editor, document)
        await self.page.evaluate("window.insertWrong=true")
        with self.assertRaisesRegex(PreparationError, "位置与相邻段落"):
            await insert_body_images(self.page, editor, self.render_page, document)

    async def test_native_table_and_code_are_preserved_first(self):
        await self.page.evaluate("window.preserveBlocks=true")
        document = await prepare_and_paste_document(self.page, self.page.locator("#editor"), self.render_page,
            '<p>示例</p><table><tr><th>列</th></tr><tr><td>数据</td></tr></table><pre><code>print("中文")</code></pre>',
            {}, self.root, "sans-serif")
        self.assertEqual(document.generated_files, [])
        self.assertIn("<table", document.prepared_html)
        self.assertIn("<pre", document.prepared_html)
        self.assertEqual(await self.page.locator("#editor td").inner_text(), "数据")

    async def test_lost_native_blocks_fall_back_to_segmented_png(self):
        await self.page.evaluate("window.dropBlocks=true")
        content = '<p>长块示例</p><table><tr><th>列</th></tr>' + \
            ''.join(f'<tr><td>第 {i} 行表格</td></tr>' for i in range(80)) + \
            '</table><pre><code>' + '\n'.join(f'第 {i} 行代码' for i in range(100)) + '</code></pre>'
        versions = []
        document = await prepare_and_paste_document(self.page, self.page.locator("#editor"), self.render_page,
            content, {}, self.root, "sans-serif", on_prepared=lambda doc: versions.append(doc.prepared_html))
        self.assertEqual(len(versions), 2)
        self.assertIn("<table", versions[0])
        self.assertNotIn("<table", document.prepared_html)
        self.assertNotIn("<pre", document.prepared_html)
        self.assertGreater(len(document.generated_files), 3)
        from PIL import Image
        for path in document.image_paths:
            with Image.open(path) as image:
                self.assertLessEqual(image.height, 1200)

    async def test_editor_headings_and_instruction_toasts_are_not_receipts(self):
        await self.page.locator('#editor').evaluate("el=>el.innerHTML='<h2>发布成功</h2><h3>审核中</h3><code class=\"toast\">发布成功</code>'")
        result = await read_result_evidence(self.page, "zhihu", "测试文章")
        self.assertEqual(result["status"], "unknown")
        await self.page.locator('body').evaluate("""el=>{
            const alert=document.createElement('div');alert.role='alert';
            alert.textContent='发布成功后请去内容管理查看';el.appendChild(alert);
        }""")
        self.assertEqual((await read_result_evidence(self.page, "zhihu", "测试文章"))["status"], "unknown")
        await self.page.get_by_role('alert').evaluate("el=>el.textContent='发布成功，等待审核'")
        self.assertEqual((await read_result_evidence(self.page, "zhihu", "测试文章"))["status"], "submitted")
        await self.page.get_by_role('alert').evaluate('el=>el.remove()')
        await self.page.locator('body').evaluate("""el=>{
            const heading=document.createElement('h1');heading.textContent='发布成功';el.appendChild(heading);
        }""")
        self.assertEqual((await read_result_evidence(self.page, "zhihu", "测试文章"))["status"], "submitted")

    async def test_code_indentation_loss_triggers_png_conversion(self):
        await self.page.evaluate('window.flattenCode=true')
        versions = []
        document = await prepare_and_paste_document(self.page, self.page.locator('#editor'), self.render_page,
            '<p>代码示例</p><pre><code>def demo():\n    print("中文")\n    return 1</code></pre>', {}, self.root,
            'sans-serif', on_prepared=lambda doc: versions.append(doc.prepared_html))
        self.assertEqual(len(versions), 2)
        self.assertIn('<pre', versions[0])
        self.assertNotIn('<pre', document.prepared_html)
        self.assertTrue(document.generated_files)

    async def test_captcha_tutorial_text_is_not_a_challenge(self):
        await self.page.locator('#editor').evaluate("el=>el.innerHTML='<h2>验证码教程</h2><p>请完成验证后输入验证码。</p>'")
        self.assertEqual((await read_result_evidence(self.page, 'zhihu', '验证码教程'))['status'], 'unknown')
        await self.page.locator('body').evaluate("""el=>{
            const dialog=document.createElement('div');dialog.role='dialog';
            dialog.textContent='请完成安全验证：请输入验证码';el.appendChild(dialog);
        }""")
        self.assertEqual((await read_result_evidence(self.page, 'zhihu', '验证码教程'))['status'], 'needs_action')

    async def test_public_captcha_tutorial_is_published(self):
        await self.page.route('https://zhuanlan.zhihu.com/p/123456', lambda route: route.fulfill(
            content_type='text/html; charset=utf-8', body='<h1>验证码教程</h1><p>这里说明验证码、安全验证和滑块验证。</p>'))
        await self.page.goto('https://zhuanlan.zhihu.com/p/123456')
        self.assertEqual((await read_result_evidence(self.page, 'zhihu', '验证码教程'))['status'], 'published')


    async def test_wechat_cursor_separator_is_not_a_body_image(self):
        """只排除已核实的公众号编辑器占位图，额外原图仍会阻止提交。"""
        editor = self.page.locator("#editor")
        await editor.evaluate("el=>el.innerHTML='<p>正文<img class=ProseMirror-separator></p>'")
        document = PreparedDocument("<p>正文</p>", "<p>正文</p>", "正文", [], [], [])
        await _verify_final_body(editor, document, "wechat")
        self.assertEqual(await body_sequence(editor, "wechat"), "正文")
        with self.assertRaisesRegex(PreparationError, "正文图片"):
            await _verify_final_body(editor, document, "zhihu")
        await editor.evaluate("el=>el.insertAdjacentHTML('beforeend','<img src=https://fixture.test/uploaded.png>')")
        with self.assertRaisesRegex(PreparationError, "正文图片"):
            await _verify_final_body(editor, document, "wechat")



if __name__ == "__main__":
    unittest.main()

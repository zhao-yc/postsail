"""文章适配安全边界测试；可选本地浏览器用例不访问外部平台。"""
import base64
import os
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from utils.articles.adapter import (_submit_once, _selected_statement, _create_app, _verify_tags,
                                   _verify_title, validate_task)
from utils.articles.browser import (
    PreparationError, insert_body_images, is_uploaded_image, paste_rich_html,
    prepare_document, read_result_evidence, install_preview_guard, launch_article_browser,
    prepare_and_paste_document,
    receipt_status, normalize_code_text,
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

    async def test_preview_blocks_click_and_shortcut(self):
        await install_preview_guard(self.page)
        self.assertTrue(await self.page.evaluate("Boolean(window.__omnipostPreviewGuard)"))
        self.assertTrue(await self.page.locator("button").evaluate("el=>el.disabled"))
        await self.page.locator("button").evaluate("el=>el.click()")
        await self.page.keyboard.press("ControlOrMeta+Enter")
        self.assertEqual(await self.page.evaluate("window.submissions||0"), 0)

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


if __name__ == "__main__":
    unittest.main()

"""传媒文章边界及真实 Chromium 受控页面测试；不连接真实发布平台。"""
import base64
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from utils.articles.browser import (
    PreparationError, PreparedDocument, launch_article_browser, paste_rich_html,
)
from utils.articles.publishers import PUBLISHER_ADAPTERS


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jDlsAAAAASUVORK5CYII=")
HOSTS = {"yidian": "img.yidianzixun.com", "dayu": "image.uc.cn",
         "netease": "nimg.ws.126.net", "kuaichuan": "p0.ssl.qhimg.com"}


class PublisherOptionBoundaryTests(unittest.IsolatedAsyncioTestCase):
    """不需要浏览器即可检查输入契约，不以模拟DOM证明线上可用。"""

    async def test_required_cover_fails_before_touching_the_page(self):
        for platform in ("yidian", "netease", "kuaichuan"):
            adapter = PUBLISHER_ADAPTERS[platform]({"title": "文章标题"}, None)
            with self.subTest(platform=platform), self.assertRaisesRegex(PreparationError, "需要封面"):
                await adapter.apply_options(MagicMock(), MagicMock())

    async def test_meaningful_unsupported_option_is_rejected(self):
        adapter = PUBLISHER_ADAPTERS["dayu"]({"title": "文章标题", "options": {"original": True}}, None)
        with self.assertRaisesRegex(PreparationError, "不支持"):
            await adapter.apply_options(MagicMock(), MagicMock())

    async def test_legacy_empty_options_remain_compatible(self):
        adapter = PUBLISHER_ADAPTERS["dayu"]({"title": "文章标题", "options": {
            "ai_generated": False, "summary": "", "original": False}}, None)
        await adapter.apply_options(MagicMock(), MagicMock())

    async def test_original_requires_a_boolean(self):
        adapter = PUBLISHER_ADAPTERS["netease"](
            {"title": "文章标题", "options": {"original": "false"}}, Path("cover.png"))
        with self.assertRaisesRegex(PreparationError, "布尔"):
            await adapter.apply_options(MagicMock(), MagicMock())


@unittest.skipUnless(os.environ.get("OMNIPOST_BROWSER_TESTS") == "1", "受控浏览器用例需显式启用")
class PublisherBrowserTests(unittest.IsolatedAsyncioTestCase):
    """官方域名上的请求全部由fixture拦截；图片仅代表受控上传结果。"""

    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        import conf
        self.directory = TemporaryDirectory()
        self.cover = Path(self.directory.name) / "cover.png"
        self.cover.write_bytes(PNG)
        self.runtime = await async_playwright().start()
        self.browser = await launch_article_browser(self.runtime, True, getattr(conf, "LOCAL_CHROME_PATH", ""))
        self.context = await self.browser.new_context(viewport={"width": 1200, "height": 900})
        self.page = await self.context.new_page()

    async def asyncTearDown(self):
        await self.context.close()
        await self.browser.close()
        await self.runtime.stop()
        self.directory.cleanup()

    async def fixture(self, platform, *, options=None, tags=None, cover=True, cover_mode="inline",
                      old_body="", redirect_url=""):
        adapter = PUBLISHER_ADAPTERS[platform](
            {"title": "完整文章测试标题", "options": options or {}, "tags": tags or []},
            self.cover if cover else None)
        title = {
            "yidian": '<input class="post-title" maxlength="64">',
            "dayu": '<input id="title" maxlength="50">',
            "netease": '<textarea placeholder="请输入标题 (5~64个字)" maxlength="64"></textarea>',
            "kuaichuan": '<textarea placeholder="请输入标题" maxlength="40"></textarea>',
        }[platform]
        body = {
            "yidian": '<div class="editor-content" contenteditable="true"></div>',
            "dayu": '<iframe id="ueditor_0" src="/fixture-frame"></iframe>',
            "netease": '<div class="public-DraftEditor-content" contenteditable="true"><div data-contents="true"></div></div>',
            "kuaichuan": '<div contenteditable="true"></div>',
        }[platform]
        if old_body and platform != "dayu":
            body = body.replace('contenteditable="true">', 'contenteditable="true">' + old_body)
        cover_control = ('<input id="cover-file" type="file" accept="image/*" style="display:none" '
                         'onchange="uploadCover()">')
        if cover_mode == "dialog":
            cover_control = '<button onclick="document.getElementById(\'crop\').showModal()">上传封面</button>'
        elif cover_mode == "chooser":
            cover_control = '<button onclick="document.getElementById(\'external-cover-file\').click()">上传封面</button>'
        content = """<!doctype html><html><head><meta charset="utf-8"><style>
            [contenteditable]{min-height:120px}iframe{height:180px}fieldset{min-height:80px}
            </style></head><body>""" + title + body + """
            <input id="unrelated-upload" type="file" onchange="window.wrongUpload=true">
            <input id="external-cover-file" type="file" style="display:none" onchange="uploadCover()">
            <fieldset id="cover-region"><legend>文章封面</legend>""" + cover_control + """
                <img id="cover-preview" alt="文章封面"></fieldset>
            <label>个人观点<input id="statement" type="checkbox"></label>
            <label>声明原创<input id="original" type="checkbox"></label>
            <label>标签<input id="tags"></label>
            <button id="publish" onclick="window.events.push('clicked');const notice=document.createElement('div');notice.setAttribute('role','alert');notice.textContent='提交成功';document.body.appendChild(notice)">发布</button>
            <dialog id="crop" aria-label="封面裁剪">
                <input type="file" accept="image/*" onchange="const reader=new FileReader();reader.onload=()=>document.getElementById('crop-preview').src=reader.result;reader.readAsDataURL(this.files[0])">
                <img id="crop-preview"><button onclick="uploadCover();document.getElementById('crop').close()">完成</button>
            </dialog>
            <script>window.events=[];window.wrongUpload=false;
                function uploadCover(){document.getElementById('cover-preview').src='https://""" + HOSTS[platform] + """/uploaded.png';}
            </script></body></html>"""
        if platform != "netease":
            # 与公开脚本一致：三个传媒后台的发布控件是无 button role 的 div。
            content = content.replace('<button id="publish"',
                '<div class="button_publish item editor-btn editor-main-btn" id="publish"')
            content = content.replace('>发布</button>', '>发布</div>')

        async def serve(route):
            if redirect_url and route.request.url == adapter.editor_url.split("#", 1)[0]:
                # 独立导航继续由 context route 拦截；HTTP重定向链不交给真实网络。
                await route.fulfill(content_type="text/html", body=(
                    '<html><head><script>location.replace(' + json.dumps(redirect_url) + ')</script></head></html>'))
            elif route.request.url.endswith("uploaded.png"):
                await route.fulfill(body=PNG, content_type="image/png")
            elif route.request.url.endswith("/fixture-frame"):
                await route.fulfill(content_type="text/html; charset=utf-8", body=(
                    '<html><body contenteditable="true" style="min-height:140px">' + old_body + '</body></html>'))
            else:
                await route.fulfill(content_type="text/html; charset=utf-8", body=content)
        await self.context.route("**/*", serve)
        editor = await adapter.open_editor(self.page)
        return adapter, editor

    async def test_all_editors_preserve_title_body_and_platform_cover(self):
        for platform in PUBLISHER_ADAPTERS:
            with self.subTest(platform=platform):
                await self.context.unroute("**/*")
                adapter, editor = await self.fixture(platform)
                await adapter.fill_title(self.page)
                await adapter.verify_title(self.page)
                html = "<p>第一段<strong>加粗正文</strong></p><p>第二段完整正文</p>"
                document = PreparedDocument(html, html, "", [], [], [])
                await paste_rich_html(self.page, editor, document)
                self.assertIn("第二段完整正文", await editor.inner_text())
                self.assertEqual(await editor.locator("strong,b").inner_text(), "加粗正文")
                await adapter.apply_options(self.page, editor)
                await adapter.verify_options(self.page, editor)
                self.assertFalse(await self.page.evaluate("window.wrongUpload"))
                self.assertEqual(await self.page.locator("#statement").is_checked(), False)
                self.assertEqual(await self.page.locator("#original").is_checked(), False)
                await adapter.verify_title(self.page)
                async def boundary():
                    await self.page.evaluate("window.events.push('saved')")
                await adapter.submit(self.page, boundary)
                result = await adapter.read_result(self.page)
                self.assertEqual(result["status"], "submitted")
                self.assertEqual(await self.page.evaluate("window.events"), ["saved", "clicked"])

    async def test_dayu_uses_the_actual_iframe_document(self):
        adapter, editor = await self.fixture("dayu", cover=False)
        await editor.fill("框架内正文")
        self.assertEqual(await self.page.frame_locator("#ueditor_0").locator("body").inner_text(), "框架内正文")
        self.assertNotIn("框架内正文", await self.page.locator("body").inner_text())
        await adapter.apply_options(self.page, editor)

    async def test_semantic_cover_dialog_upload_and_crop_are_read_back(self):
        adapter, editor = await self.fixture("yidian", cover_mode="dialog")
        await adapter.apply_options(self.page, editor)
        await adapter.verify_options(self.page, editor)
        self.assertFalse(await self.page.locator("#crop").is_visible())
        self.assertTrue((await self.page.locator("#cover-preview").get_attribute("src")).endswith("uploaded.png"))

    async def test_cover_opener_native_file_chooser_uploads_only_the_cover(self):
        adapter, editor = await self.fixture("kuaichuan", cover_mode="chooser")
        await adapter.apply_options(self.page, editor)
        await adapter.verify_options(self.page, editor)
        self.assertFalse(await self.page.evaluate("window.wrongUpload"))

    async def test_redirect_to_lookalike_editor_is_rejected_before_any_write(self):
        with self.assertRaisesRegex(PreparationError, "离开官方文章编辑器"):
            await self.fixture("yidian", redirect_url="https://lookalike.test/#/Writing/articleEditor")
        self.assertEqual(await self.page.locator(".post-title").input_value(), "")

    async def test_wrong_official_route_cannot_be_used_as_an_article_editor(self):
        with self.assertRaisesRegex(PreparationError, "离开官方文章编辑器"):
            await self.fixture("yidian", redirect_url="https://mp.yidianzixun.com/other-product#/Writing/articleEditor")

    async def test_nonempty_restored_draft_is_preserved_including_iframe(self):
        for platform in ("yidian", "dayu"):
            with self.subTest(platform=platform):
                await self.context.unroute("**/*")
                with self.assertRaisesRegex(PreparationError, "阻止覆盖"):
                    await self.fixture(platform, old_body="<p>之前的草稿必须保留</p>")
                editor = (self.page.frame_locator("#ueditor_0").locator("body") if platform == "dayu"
                          else self.page.locator(".editor-content"))
                self.assertIn("之前的草稿必须保留", await editor.inner_text())

    async def test_explicit_statement_original_and_tags_are_read_back(self):
        adapter, editor = await self.fixture("netease", options={"statement": "个人观点", "original": True}, tags=["科技", "写作"])
        await adapter.apply_options(self.page, editor)
        await adapter.verify_options(self.page, editor)
        self.assertTrue(await self.page.locator("#statement").is_checked())
        self.assertTrue(await self.page.locator("#original").is_checked())
        await self.page.locator("#original").uncheck()
        with self.assertRaisesRegex(PreparationError, "原创设置读回"):
            await adapter.verify_options(self.page, editor)

    async def test_explicit_false_original_unchecks_preexisting_value(self):
        adapter, editor = await self.fixture("kuaichuan", options={"original": False})
        await self.page.locator("#original").check()
        await adapter.apply_options(self.page, editor)
        await adapter.verify_options(self.page, editor)
        self.assertFalse(await self.page.locator("#original").is_checked())

    async def test_nonmatching_statement_and_plain_body_tags_block(self):
        adapter, editor = await self.fixture("dayu", options={"statement": "未提供的声明"}, cover=False)
        with self.assertRaisesRegex(PreparationError, "唯一.*声明"):
            await adapter.apply_options(self.page, editor)
        adapter.options = {}
        adapter.tags = ["科技"]
        await editor.fill("#科技#")
        with self.assertRaisesRegex(PreparationError, "原生标签读回"):
            await adapter.verify_options(self.page, editor)
        self.assertEqual(await self.page.evaluate("window.events"), [])

    async def test_unlabelled_and_ambiguous_cover_uploads_are_rejected(self):
        adapter, editor = await self.fixture("yidian")
        await self.page.locator("#cover-region legend").evaluate("el=>el.remove()")
        with self.assertRaisesRegex(PreparationError, "唯一.*封面区域"):
            await adapter.apply_options(self.page, editor)
        await self.page.locator("#cover-region").evaluate("el=>{const legend=document.createElement('legend');legend.textContent='文章封面';el.prepend(legend);el.appendChild(el.querySelector('input').cloneNode());}")
        with self.assertRaisesRegex(PreparationError, "唯一.*上传字段"):
            await adapter.apply_options(self.page, editor)
        self.assertFalse(await self.page.evaluate("window.wrongUpload"))

    async def test_stale_and_local_cover_previews_do_not_count_as_uploads(self):
        adapter, editor = await self.fixture("netease")
        await adapter.apply_options(self.page, editor)
        src = await self.page.locator("#cover-preview").get_attribute("src")
        adapter._cover_before = {src}
        with self.assertRaisesRegex(PreparationError, "新封面"):
            await adapter.verify_options(self.page, editor)
        adapter._cover_before.clear()
        await self.page.locator("#cover-preview").evaluate("(el, encoded)=>el.src='data:image/png;base64,'+encoded", base64.b64encode(PNG).decode())
        with self.assertRaisesRegex(PreparationError, "新封面"):
            await adapter.verify_options(self.page, editor)

    async def test_maxlength_and_duplicate_visible_title_do_not_get_filled(self):
        adapter, editor = await self.fixture("yidian")
        await self.page.locator(".post-title").evaluate("el=>el.maxLength=3")
        with self.assertRaisesRegex(PreparationError, "最多 3"):
            await adapter.fill_title(self.page)
        self.assertEqual(await self.page.locator(".post-title").input_value(), "")
        await self.page.locator(".post-title").evaluate("el=>el.after(el.cloneNode())")
        with self.assertRaisesRegex(PreparationError, "唯一"):
            await adapter.fill_title(self.page)

    async def test_submit_boundary_precedes_single_click_and_duplicate_is_blocked(self):
        adapter, editor = await self.fixture("dayu", cover=False)
        async def boundary():
            await self.page.evaluate("window.events.push('saved')")
        await adapter.submit(self.page, boundary)
        with self.assertRaisesRegex(PreparationError, "已经尝试"):
            await adapter.submit(self.page, boundary)
        self.assertEqual(await self.page.evaluate("window.events"), ["saved", "clicked"])

    async def test_source_backed_div_buttons_submit_once_without_button_role(self):
        for platform in ("yidian", "dayu", "kuaichuan"):
            with self.subTest(platform=platform):
                await self.context.unroute("**/*")
                adapter, editor = await self.fixture(platform)
                self.assertEqual(await self.page.get_by_role("button", name="发布", exact=True).count(), 0)
                self.assertEqual(await self.page.locator("#publish").evaluate("el=>el.tagName"), "DIV")
                async def boundary():
                    await self.page.evaluate("window.events.push('saved')")
                await adapter.submit(self.page, boundary)
                with self.assertRaisesRegex(PreparationError, "已经尝试"):
                    await adapter.submit(self.page, boundary)
                self.assertEqual(await self.page.evaluate("window.events"), ["saved", "clicked"])

    async def test_div_publish_wrong_name_disabled_or_mixed_candidates_never_submit(self):
        adapter, editor = await self.fixture("kuaichuan")
        callback = MagicMock()
        await self.page.locator("#publish").evaluate("el=>el.textContent='保存草稿'")
        with self.assertRaisesRegex(PreparationError, "唯一"):
            await adapter.submit(self.page, callback)
        await self.page.locator("#publish").evaluate("el=>{el.textContent='发布';el.setAttribute('aria-disabled','true')}")
        with self.assertRaises(PreparationError):
            await adapter.submit(self.page, callback)
        await self.page.locator("#publish").evaluate("el=>{el.removeAttribute('aria-disabled');const duplicate=document.createElement('button');duplicate.textContent='发布';el.after(duplicate)}")
        with self.assertRaisesRegex(PreparationError, "唯一"):
            await adapter.submit(self.page, callback)
        callback.assert_not_called()
        self.assertEqual(await self.page.evaluate("window.events"), [])

    async def test_boundary_failure_and_ambiguous_publish_never_click(self):
        adapter, editor = await self.fixture("dayu", cover=False)
        def boundary():
            raise RuntimeError("数据库写入失败")
        with self.assertRaisesRegex(RuntimeError, "数据库"):
            await adapter.submit(self.page, boundary)
        await self.page.locator("#publish").evaluate("el=>el.after(el.cloneNode(true))")
        with self.assertRaisesRegex(PreparationError, "唯一"):
            await adapter.submit(self.page, boundary)
        self.assertEqual(await self.page.evaluate("window.events"), [])

    async def test_receipt_text_inside_editor_does_not_prove_submission(self):
        adapter, editor = await self.fixture("kuaichuan")
        await editor.fill("发布成功")
        self.assertEqual((await adapter.read_result(self.page))["status"], "unknown")

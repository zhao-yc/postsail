"""新增社区文章的边界与受控浏览器测试；不登录、不请求真实发布平台。"""
import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from utils.articles.browser import PreparationError
from utils.articles.community import (
    COMMUNITY_ADAPTERS, AcFunArticleAdapter, CSDNArticleAdapter,
    DoubanArticleAdapter, JianshuArticleAdapter, XueqiuArticleAdapter,
)


def snapshot(platform="xueqiu", **values):
    return {"platform": platform, "title": "测试文章标题完整文本", "tags": [], "options": {}, **values}


def field():
    control = MagicMock()
    control.is_visible = AsyncMock(return_value=True)
    control.is_enabled = AsyncMock(return_value=True)
    control.scroll_into_view_if_needed = AsyncMock()
    control.click = AsyncMock()
    control.evaluate = AsyncMock(return_value="")
    return control


def controls(*items):
    locator = MagicMock()
    locator.count = AsyncMock(return_value=len(items))
    locator.nth.side_effect = lambda index: items[index]
    return locator


class CommunityBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def test_all_five_platforms_have_separate_native_entrypoints(self):
        self.assertEqual(set(COMMUNITY_ADAPTERS), {"acfun", "xueqiu", "douban", "csdn", "jianshu"})
        self.assertEqual(len({adapter.editor_url for adapter in COMMUNITY_ADAPTERS.values()}), 5)

    def test_origin_suffix_and_unrelated_paths_are_rejected(self):
        adapter = XueqiuArticleAdapter(snapshot(), None)
        for url in ["https://mp.xueqiu.com.evil.test/writeV2", "https://evil.test/writeV2",
                    "https://mp.xueqiu.com/u/123", "http://mp.xueqiu.com/writeV2",
                    "https://user:password@mp.xueqiu.com/writeV2", "https://mp.xueqiu.com:444/writeV2"]:
            with self.subTest(url=url), self.assertRaises(PreparationError):
                adapter._check_url(MagicMock(url=url))

    def test_acfun_member_or_video_page_does_not_authorize_article_write(self):
        adapter = AcFunArticleAdapter(snapshot("acfun"), None)
        for url in ["https://www.acfun.cn/member/", "https://www.acfun.cn/member/video-publish"]:
            with self.assertRaisesRegex(PreparationError, "文章投稿"):
                adapter._check_article_url(MagicMock(url=url))
        adapter._check_article_url(MagicMock(url="https://www.acfun.cn/member/article-publish"))

    async def test_existing_body_or_images_are_not_overwritten(self):
        adapter = DoubanArticleAdapter(snapshot("douban"), None)
        editor = MagicMock()
        editor.evaluate = AsyncMock(return_value=True)
        with self.assertRaisesRegex(PreparationError, "避免覆盖"):
            await adapter._protect_existing_draft(editor)

    async def test_persistence_failure_prevents_click(self):
        adapter = XueqiuArticleAdapter(snapshot(), None)
        page = MagicMock(url=adapter.editor_url)
        button = field()
        def failure():
            raise RuntimeError("persistence failed")
        with patch("utils.articles.community._actions", return_value=controls(button)):
            with self.assertRaisesRegex(RuntimeError, "persistence failed"):
                await adapter.submit(page, failure)
        button.click.assert_not_awaited()

    async def test_ambiguous_publish_actions_stop_before_boundary(self):
        adapter = XueqiuArticleAdapter(snapshot(), None)
        page = MagicMock(url=adapter.editor_url)
        first, second = field(), field()
        callback = MagicMock()
        with patch("utils.articles.community._actions", return_value=controls(first, second)):
            with self.assertRaisesRegex(PreparationError, "唯一"):
                await adapter.submit(page, callback)
        callback.assert_not_called()

    async def test_click_failure_is_not_retried(self):
        adapter = XueqiuArticleAdapter(snapshot(), None)
        page = MagicMock(url=adapter.editor_url)
        button = field()
        events = []
        async def fail(**kwargs):
            events.append("click")
            raise RuntimeError("connection lost")
        button.click.side_effect = fail
        with patch("utils.articles.community._actions", return_value=controls(button)):
            with self.assertRaises(RuntimeError):
                await adapter.submit(page, lambda: events.append("persist"))
            with self.assertRaisesRegex(PreparationError, "已经尝试"):
                await adapter.submit(page, lambda: events.append("second"))
        self.assertEqual(events, ["persist", "click"])
        button.click.assert_awaited_once()

    async def test_unsupported_parameter_is_not_silently_dropped(self):
        adapter = XueqiuArticleAdapter(snapshot(options={"create_type": "原创"}), None)
        with self.assertRaisesRegex(PreparationError, "不支持文章选项"):
            await adapter.apply_options(MagicMock(url=adapter.editor_url), MagicMock())

    async def test_acfun_category_is_required(self):
        page = MagicMock(url="https://www.acfun.cn/member/article-publish")
        adapter = AcFunArticleAdapter(snapshot("acfun"), None)
        with self.assertRaisesRegex(PreparationError, "选择分类"):
            await adapter.apply_options(page, MagicMock())

    async def test_jianshu_does_not_discard_cover_or_tags(self):
        for cover, tags, message in [(Path("/tmp/cover.png"), [], "独立封面"), (None, ["标签"], "独立标签")]:
            adapter = JianshuArticleAdapter(snapshot("jianshu", tags=tags), cover)
            with self.assertRaisesRegex(PreparationError, message):
                await adapter.apply_options(MagicMock(), MagicMock())

    def test_jianshu_draft_identity_requires_notebook_and_note(self):
        self.assertEqual(JianshuArticleAdapter._note_id("https://www.jianshu.com/writer#/notebooks/2/notes/3/writing"), ("2", "3"))
        self.assertIsNone(JianshuArticleAdapter._note_id("https://www.jianshu.com/writer#/notebooks/2"))

    async def test_jianshu_navigation_to_another_note_blocks_submit(self):
        adapter = JianshuArticleAdapter(snapshot("jianshu"), None)
        adapter._created_note = ("1", "2")
        with self.assertRaisesRegex(PreparationError, "本次新建稿件"):
            await adapter.submit(MagicMock(url="https://www.jianshu.com/writer#/notebooks/1/notes/3"), MagicMock())

    def route(self, path, payload, method="POST"):
        route = MagicMock()
        route.request.url = "https://bizapi.csdn.net" + path
        route.request.method = method
        route.request.post_data_json = payload
        route.abort = AsyncMock()
        route.fallback = AsyncMock()
        return route

    async def test_csdn_settings_guard_only_allows_explicit_drafts(self):
        cases = [({"status": 2, "pubStatus": "draft"}, True), ({"status": 1}, False),
                 ({"status": 2, "pubStatus": "publish"}, False), ({}, False), (None, False)]
        for payload, allowed in cases:
            with self.subTest(payload=payload):
                adapter = CSDNArticleAdapter(snapshot("csdn"), None)
                route = self.route("/blog-console-api/v3/mdeditor/saveArticle", payload)
                await adapter._guard_settings(route)
                self.assertEqual(route.fallback.await_count, int(allowed))
                self.assertEqual(route.abort.await_count, int(not allowed))

    async def test_csdn_settings_guard_rejects_unknown_write_endpoint(self):
        adapter = CSDNArticleAdapter(snapshot("csdn"), None)
        route = self.route("/blog-console-api/new/publish", {"status": 2})
        await adapter._guard_settings(route)
        route.abort.assert_awaited_once_with("blockedbyclient")
        self.assertTrue(adapter._settings_write_blocked)

    async def test_csdn_settings_guard_does_not_block_image_signature(self):
        adapter = CSDNArticleAdapter(snapshot("csdn"), None)
        route = self.route("/resource-api/v1/image/direct/upload/signature", {})
        await adapter._guard_settings(route)
        route.fallback.assert_awaited_once()

    async def test_csdn_never_submits_without_verified_dialog(self):
        adapter = CSDNArticleAdapter(snapshot("csdn"), None)
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, "设置尚未核对"):
            await adapter.submit(MagicMock(url=adapter.editor_url), callback)
        callback.assert_not_called()

    async def test_csdn_guard_is_installed_once_before_navigation(self):
        adapter = CSDNArticleAdapter(snapshot("csdn"), None)
        page = MagicMock()
        page.route = AsyncMock()
        await adapter.install_preparation_guard(page)
        await adapter.install_preparation_guard(page)
        page.route.assert_awaited_once()
        for url in ["https://new.csdn.net/publish", "http://editor.csdn.net/post", "https://csdn.net/submit"]:
            self.assertRegex(url, adapter._guard_pattern)

    async def test_csdn_failed_boundary_keeps_request_guard_active(self):
        adapter = CSDNArticleAdapter(snapshot("csdn"), None)
        page = MagicMock(url=adapter.editor_url)
        page.unroute = AsyncMock()
        adapter._publish_dialog = MagicMock()
        adapter._body_editor = MagicMock()
        adapter._settings_guard_active = True
        adapter.verify_options = AsyncMock()
        adapter.verify_title = AsyncMock()
        adapter._recheck_body = AsyncMock()
        button = field()
        def fail():
            raise RuntimeError("database unavailable")
        with patch("utils.articles.community._actions", return_value=controls(button)):
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                await adapter.submit(page, fail)
        page.unroute.assert_not_awaited()
        button.click.assert_not_awaited()
        self.assertTrue(adapter._settings_guard_active)

    async def test_private_article_result_never_claims_publication(self):
        adapter = XueqiuArticleAdapter(snapshot(options={"visibility": "仅自己可见"}), None)
        with patch("utils.articles.native.read_result_evidence", AsyncMock(return_value={"status": "published"})):
            result = await adapter.read_result(MagicMock())
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["platform_status"], "仅自己可见")


@unittest.skipUnless(os.environ.get("OMNIPOST_BROWSER_TESTS") == "1", "受控浏览器用例需显式启用")
class CommunityLocalBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        import conf
        from utils.articles.browser import launch_article_browser
        self.runtime = await async_playwright().start()
        try:
            self.browser = await launch_article_browser(self.runtime, True, getattr(conf, "LOCAL_CHROME_PATH", ""))
        except Exception:
            await self.runtime.stop()
            raise
        self.page = await self.browser.new_page()
        self.temp = tempfile.TemporaryDirectory()

    async def asyncTearDown(self):
        await self.browser.close()
        await self.runtime.stop()
        self.temp.cleanup()

    async def fixture(self, html, url):
        async def serve(route):
            await route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html,
                                headers={"Access-Control-Allow-Origin": "*",
                                         "Access-Control-Allow-Headers": "Content-Type",
                                         "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS"})
        await self.page.route("**/*", serve)
        await self.page.goto(url)

    async def test_xueqiu_unique_rich_editor_and_full_title_readback(self):
        adapter = XueqiuArticleAdapter(snapshot(), None)
        await self.fixture('<textarea placeholder="请输入标题"></textarea><div class="ProseMirror" contenteditable="true"><p><br></p></div>', adapter.editor_url)
        editor = await adapter.open_editor(self.page)
        await adapter.fill_title(self.page)
        await adapter.verify_title(self.page)
        self.assertEqual(await editor.get_attribute("class"), "ProseMirror")

    async def test_duplicate_body_editors_and_existing_draft_both_block(self):
        adapter = XueqiuArticleAdapter(snapshot(), None)
        await self.fixture('<div class="ProseMirror" contenteditable="true">旧稿</div><div class="ProseMirror" contenteditable="true">第二篇</div>', adapter.editor_url)
        with self.assertRaisesRegex(PreparationError, "唯一"):
            await adapter.open_editor(self.page)
        await self.page.locator(".ProseMirror").last.evaluate("el=>el.remove()")
        with self.assertRaisesRegex(PreparationError, "避免覆盖"):
            await adapter._protect_existing_draft(await adapter._find_editor(self.page))

    async def test_title_only_draft_is_preserved_on_four_platforms(self):
        fixtures = {
            "xueqiu": '<textarea placeholder="请输入标题">已有的标题</textarea><div class="ProseMirror" contenteditable="true"><p><br></p></div>',
            "douban": '<textarea placeholder="添加标题">已有的标题</textarea><div class="public-DraftEditor-content" contenteditable="true"><p><br></p></div>',
            "csdn": '<input placeholder="请输入文章标题" value="已有的标题"><div class="ql-editor" contenteditable="true"><p><br></p></div>',
            "acfun": '<a href="/member/article-publish">文章投稿</a><input name="title" value="已有的标题"><div class="ql-editor" contenteditable="true"><p><br></p></div>',
        }
        for platform, html in fixtures.items():
            with self.subTest(platform=platform):
                await self.page.unroute("**/*")
                adapter = COMMUNITY_ADAPTERS[platform](snapshot(platform), None)
                await self.fixture(html, adapter.editor_url)
                with self.assertRaisesRegex(PreparationError, "已有草稿标题"):
                    await adapter.open_editor(self.page)
                self.assertEqual(await (await adapter._title_field(self.page)).input_value(), "已有的标题")

    async def test_csdn_native_iframe_editor_is_detected(self):
        adapter = CSDNArticleAdapter(snapshot("csdn"), None)
        await self.fixture('<input placeholder="请输入文章标题"><iframe class="tox-edit-area__iframe" srcdoc="<body contenteditable=true><p><br></p></body>"></iframe>', adapter.editor_url)
        editor = await adapter.open_editor(self.page)
        self.assertEqual(await editor.evaluate("el=>el.tagName"), "BODY")

    async def test_csdn_markdown_is_only_changed_through_native_switch(self):
        adapter = CSDNArticleAdapter(snapshot("csdn"), None)
        await self.fixture('''<input placeholder="请输入文章标题"><div class="CodeMirror">Markdown</div>
            <button onclick="document.querySelector('.CodeMirror').outerHTML='<div class=ql-editor contenteditable=true><p><br></p></div>'">切换为富文本编辑器</button>''', adapter.editor_url)
        editor = await adapter.open_editor(self.page)
        self.assertEqual(await editor.get_attribute("class"), "ql-editor")
        self.assertEqual(await self.page.locator(".CodeMirror").count(), 0)

    async def test_jianshu_creates_new_note_without_touching_old_body(self):
        adapter = JianshuArticleAdapter(snapshot("jianshu"), None)
        await self.fixture('''<input name="title" value="旧稿"><div class="kalamu-area" contenteditable="true">保留旧稿</div>
            <button onclick="window.oldBody=document.querySelector('.kalamu-area').textContent; location.hash='/notebooks/4/notes/6'; document.querySelector('.kalamu-area').innerHTML='<p><br></p>'; document.querySelector('input').value='2026-10-01'">新建文章</button>
            <script>location.hash='/notebooks/4/notes/5'</script>''', adapter.editor_url)
        editor = await adapter.open_editor(self.page)
        self.assertEqual(adapter._created_note, ("4", "6"))
        self.assertEqual(await self.page.evaluate("window.oldBody"), "保留旧稿")
        self.assertEqual((await editor.inner_text()).strip(), "")
        await adapter.fill_title(self.page)
        await adapter.verify_title(self.page)

    async def test_acfun_radio_category_is_verified_as_selected_control(self):
        adapter = AcFunArticleAdapter(snapshot("acfun", options={"category": "生活"}), None)
        await self.fixture('''<div role="group" aria-label="分类">
            <label><input type="radio" name="category">生活</label>
            <label><input type="radio" name="category">资讯</label></div>''', "https://www.acfun.cn/member/article-publish")
        await adapter.apply_options(self.page, MagicMock())
        await adapter.verify_options(self.page, MagicMock())
        await self.page.get_by_role("radio", name="资讯", exact=True).check()
        with self.assertRaisesRegex(PreparationError, "分类未选中"):
            await adapter.verify_options(self.page, MagicMock())

    async def test_acfun_not_declaring_original_does_not_require_source_url(self):
        adapter = AcFunArticleAdapter(snapshot("acfun", options={"category": "生活", "original": False}), None)
        await self.fixture('''<label for="category">分类</label><select id="category"><option>生活</option></select>
            <label><input type="checkbox" checked>声明原创</label>''', "https://www.acfun.cn/member/article-publish")
        await adapter.apply_options(self.page, MagicMock())
        await adapter.verify_options(self.page, MagicMock())
        self.assertFalse(await self.page.get_by_role("checkbox", name="声明原创", exact=True).is_checked())

    async def test_body_with_only_separator_or_empty_table_is_preserved(self):
        adapter = XueqiuArticleAdapter(snapshot(), None)
        await self.fixture('''<textarea placeholder="请输入标题"></textarea>
            <div class="ProseMirror" contenteditable="true" style="min-height:80px"><hr><table><tr><td></td></tr></table></div>''', adapter.editor_url)
        with self.assertRaisesRegex(PreparationError, "避免覆盖"):
            await adapter.open_editor(self.page)
        self.assertEqual(await self.page.locator(".ProseMirror hr").count(), 1)
        self.assertEqual(await self.page.locator(".ProseMirror table").count(), 1)

    async def test_options_are_written_to_controls_and_false_original_is_preserved(self):
        adapter = DoubanArticleAdapter(snapshot("douban", tags=["生活", "读书"], options={"original": False, "visibility": "仅自己可见"}), None)
        await self.fixture('''<label><input type="checkbox" checked>声明原创</label>
            <label for="visibility">可见范围</label><select id="visibility"><option>公开</option><option>仅自己可见</option></select>
            <input name="author_tags"><div class="public-DraftEditor-content" contenteditable="true"><p><br></p></div>''', adapter.editor_url)
        editor = await adapter._find_editor(self.page)
        await adapter.apply_options(self.page, editor)
        await adapter.verify_options(self.page, editor)
        self.assertFalse(await self.page.get_by_role("checkbox").is_checked())
        await self.page.locator('[name="author_tags"]').fill("被截断")
        with self.assertRaisesRegex(PreparationError, "标签读回"):
            await adapter.verify_options(self.page, editor)

    async def test_douban_preview_and_publish_are_separate_actions(self):
        adapter = DoubanArticleAdapter(snapshot("douban"), None)
        await self.fixture('''<a href="#" class="editor-extra-button-preview" onclick="window.events.push('preview'); document.querySelector('button').hidden=false; event.preventDefault()">预览</a>
            <button hidden onclick="window.events.push('publish')">发布日记</button><script>window.events=[]</script>''', adapter.editor_url)
        async def boundary():
            await self.page.evaluate("window.events.push('persist')")
        await adapter.submit(self.page, boundary)
        self.assertEqual(await self.page.evaluate("window.events"), ["preview", "persist", "publish"])

    async def test_csdn_options_and_publish_confirmation_remain_in_dialog(self):
        adapter = CSDNArticleAdapter(snapshot("csdn", tags=["Python"], options={"summary": "完整摘要", "create_type": "原创"}), None)
        await self.fixture('''<input placeholder="请输入文章标题"><div class="ql-editor" contenteditable="true"><p>正文</p></div>
            <button onclick="document.querySelector('dialog').showModal()">发布文章</button>
            <dialog><h2>发布文章</h2><textarea placeholder="请输入摘要"></textarea>
                <label for="type">文章类型</label><select id="type"><option>原创</option><option>转载</option></select>
                <div role="group" aria-label="文章标签"><input placeholder="输入标签" onkeydown="if(event.key==='Enter'){event.preventDefault(); const tag=document.createElement('span'); tag.className='tag'; tag.dataset.tag=this.value; tag.textContent=this.value; tag.appendChild(document.createElement('button')); this.parentElement.appendChild(tag); this.value=''}"></div>
                <button onclick="window.events.push('publish')">确认发布</button></dialog><script>window.events=[]</script>''', adapter.editor_url)
        editor = await adapter._find_editor(self.page)
        adapter._body_editor = editor
        await adapter.fill_title(self.page)
        await adapter.apply_options(self.page, editor)
        await adapter.verify_options(self.page, editor)
        self.assertEqual(await self.page.evaluate("window.events"), [])
        async def boundary():
            await self.page.evaluate("window.events.push('persist')")
        await adapter.submit(self.page, boundary)
        self.assertEqual(await self.page.evaluate("window.events"), ["persist", "publish"])

    async def test_csdn_actual_request_routing_blocks_unknown_writes_before_submit(self):
        adapter = CSDNArticleAdapter(snapshot("csdn"), None)
        await self.fixture("<p>受控请求测试</p>", adapter.editor_url)
        await adapter.install_preparation_guard(self.page)
        # 所有放行请求仍由 fixture 返回本地内容；这里不连接 CSDN。
        result = await self.page.evaluate("""async () => {
            const send = (url, body) => fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
                body:JSON.stringify(body)}).then(r=>r.status).catch(()=> 'blocked');
            return [await send('https://bizapi.csdn.net/blog-console-api/v3/mdeditor/saveArticle', {status:2,pubStatus:'draft'}),
                await send('https://mp.csdn.net/new/publish', {status:1}),
                await send('https://bizapi.csdn.net/resource-api/new/publish', {status:2})];
        }""")
        self.assertEqual(result, [200, "blocked", "blocked"])
        self.assertTrue(adapter._settings_write_blocked)

    async def test_csdn_source_field_is_revealed_before_it_is_filled(self):
        adapter = CSDNArticleAdapter(snapshot("csdn", options={"create_type": "转载", "source_url": "https://example.com/source"}), None)
        await self.fixture('''<button onclick="document.querySelector('dialog').showModal()">发布文章</button>
            <dialog><h2>文章类型</h2><label for="kind">文章类型</label>
                <select id="kind" onchange="document.querySelector('#source-field').hidden=this.value==='原创'"><option>原创</option><option>转载</option></select>
                <div id="source-field" hidden><label for="source">原文链接</label><input id="source"></div>
                <button>确认发布</button></dialog>''', adapter.editor_url)
        await adapter.apply_options(self.page, MagicMock())
        await adapter.verify_options(self.page, MagicMock())
        self.assertEqual(await self.page.locator("#source").input_value(), "https://example.com/source")

    async def test_cover_requires_new_persistent_image_in_cover_region(self):
        adapter = XueqiuArticleAdapter(snapshot(), Path(self.temp.name) / "cover.png")
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=")
        adapter.cover.write_bytes(png)
        await self.fixture('''<div class="cover-container" style="min-height:40px"><input type="file" accept="image/png" onchange="const image=document.createElement('img'); image.src='https://xqimg.imedao.com/new.png'; this.parentElement.appendChild(image)"></div>''', adapter.editor_url)
        await self.page.route("https://xqimg.imedao.com/new.png", lambda route: route.fulfill(status=200, content_type="image/png", body=png))
        with patch.dict("utils.articles.browser.IMAGE_HOST_SUFFIXES", {"xueqiu": ("imedao.com",)}):
            await adapter.apply_options(self.page, MagicMock())
            await adapter.verify_options(self.page, MagicMock())
            adapter._cover_before = {"https://xqimg.imedao.com/new.png"}
            with self.assertRaisesRegex(PreparationError, "新封面"):
                await adapter.verify_options(self.page, MagicMock())


if __name__ == "__main__":
    unittest.main()

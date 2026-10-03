"""图片笔记转换与提交边界；模拟平台控件，不登录也不实际发布。"""
import base64
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from utils.articles.adapter import create_adapter, validate_task
from utils.articles.browser import PreparationError, PreparedDocument
from utils.articles.notes import (
    KuaishouNoteAdapter, TencentNoteAdapter, XiaohongshuNoteAdapter,
    create_note_adapter, prepare_note_document, _note_value,
)


class NoteConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.assets = {}
        for name in ("first", "second", "cover"):
            path = Path(self.temp.name) / (name + ".png")
            path.write_bytes(b"original image")
            self.assets[name] = dict(path=str(path), mime_type="image/png", width=600, height=600)

    def snapshot(self, **changes):
        data = dict(platform="xiaohongshu", title="测试标题", mode="preview", tags=[], options={},
                    content_html='<p>首段</p><img data-asset-id="first"><p>尾段</p><img data-asset-id="second">')
        data.update(changes)
        return data

    def test_plain_text_and_original_images_preserve_order(self):
        document = prepare_note_document(self.snapshot(), self.assets)
        self.assertEqual(document.expected_text, "首段\n尾段")
        self.assertEqual(document.image_paths, [Path(self.assets[name]["path"]) for name in ("first", "second")])
        self.assertEqual(document.generated_files, [])
        self.assertEqual([path.read_bytes() for path in document.image_paths], [b"original image"] * 2)

    def test_cover_is_prepended_only_when_not_already_in_body(self):
        for cover, names in (("cover", ["cover", "first", "second"]), ("second", ["first", "second"])):
            with self.subTest(cover=cover):
                doc = prepare_note_document(self.snapshot(cover_asset_id=cover), self.assets)
                self.assertEqual(doc.image_paths, [Path(self.assets[name]["path"]) for name in names])

    def test_commerce_cover_must_match_first_image_without_reordering_original(self):
        for asset in self.assets.values():
            asset.update(width=800, height=800)
        for platform in ("jd", "taobao"):
            with self.subTest(platform=platform):
                with self.assertRaisesRegex(PreparationError, "首"):
                    prepare_note_document(self.snapshot(platform=platform, cover_asset_id="second"), self.assets)
                document = prepare_note_document(self.snapshot(platform=platform, cover_asset_id="first"), self.assets)
                self.assertEqual(document.image_paths, [Path(self.assets[name]["path"]) for name in ("first", "second")])
                document = prepare_note_document(self.snapshot(platform=platform, cover_asset_id="cover"), self.assets)
                self.assertEqual(document.image_paths[0], Path(self.assets["cover"]["path"]))

    def test_repeated_body_images_are_not_silently_deduplicated(self):
        doc = prepare_note_document(self.snapshot(content_html='<img data-asset-id="first">' * 2), self.assets)
        self.assertEqual(doc.image_paths, [Path(self.assets["first"]["path"])] * 2)

    def test_links_keep_full_targets_and_avoid_duplicate_url_labels(self):
        source = '<p><a href="https://example.org/a">资料</a>；' \
                 '<a href="https://example.org/b"></a>；' \
                 '<a href="https://example.org/c">https://example.org/c</a></p>' \
                 '<img data-asset-id="first">'
        doc = prepare_note_document(self.snapshot(content_html=source), self.assets)
        self.assertEqual(doc.expected_text, "资料（https://example.org/a）；https://example.org/b；https://example.org/c")
        self.assertNotIn("<a", doc.prepared_html)

    def test_rich_structure_requires_explicit_opt_in(self):
        for fragment in ("<h2>标题</h2>", "<p><strong>强调</strong></p>", "<ul><li>条目</li></ul>",
                         "<table><tr><td>单元格</td></tr></table>", "<pre><code>print(1)</code></pre>"):
            with self.subTest(fragment=fragment):
                data = self.snapshot(content_html=fragment + '<img data-asset-id="first">')
                with self.assertRaisesRegex(PreparationError, "纯文本"):
                    prepare_note_document(data, self.assets)
                data["options"] = {"flatten_content": True}
                doc = prepare_note_document(data, self.assets)
                self.assertTrue(doc.expected_text)
                self.assertEqual(len(doc.image_paths), 1)

    def test_flattened_code_keeps_indentation(self):
        doc = prepare_note_document(self.snapshot(options={"flatten_content": True}, content_html=
            '<pre><code>def test():\n    return 1</code></pre><img data-asset-id="first">'), self.assets)
        self.assertEqual(doc.expected_text, "def test():\n    return 1")

    def test_no_images_cannot_become_a_text_only_post(self):
        with self.assertRaisesRegex(PreparationError, "至少需要一张"):
            prepare_note_document(self.snapshot(content_html="<p>没有图片</p>"), self.assets)

    def test_cover_counts_towards_album_limit(self):
        for platform, count in (("xiaohongshu", 18), ("kuaishou", 30), ("tencent", 9)):
            with self.subTest(platform=platform):
                data = self.snapshot(platform=platform, content_html='<img data-asset-id="first">' * count,
                                     cover_asset_id="cover")
                with self.assertRaisesRegex(PreparationError, "相册（含封面）"):
                    prepare_note_document(data, self.assets)
                data["cover_asset_id"] = "first"
                self.assertEqual(len(prepare_note_document(data, self.assets).image_paths), count)

    def test_final_text_limit_includes_urls_title_and_tags(self):
        for data in (
            self.snapshot(content_html='<p>' + "字" * 990 + '<a href="https://example.org/long">资料</a></p><img data-asset-id="first">'),
            self.snapshot(platform="kuaishou", content_html='<p>' + "字" * 499 + '</p><img data-asset-id="first">'),
            self.snapshot(content_html='<p>' + "字" * 999 + '</p><img data-asset-id="first">', tags=["标签"]),
        ):
            with self.subTest(platform=data["platform"]), self.assertRaisesRegex(PreparationError, "转换后正文"):
                prepare_note_document(data, self.assets)

    def test_kuaishou_title_and_textual_tags_are_explicit_in_preview(self):
        doc = prepare_note_document(self.snapshot(platform="kuaishou", tags=["#旅行", "风景", "旅行"]), self.assets)
        self.assertEqual(doc.expected_text, "测试标题\n首段\n尾段\n#旅行 #风景")
        self.assertIn("测试标题<br>", doc.prepared_html)

    def test_task_validation_runs_album_constraints_before_browser(self):
        with self.assertRaisesRegex(PreparationError, "至少需要一张"):
            validate_task(self.snapshot(content_html="<p>正文</p>"), {})

    def test_all_note_platforms_route_to_specific_adapters(self):
        for platform, cls in (("xiaohongshu", XiaohongshuNoteAdapter), ("kuaishou", KuaishouNoteAdapter),
                              ("tencent", TencentNoteAdapter)):
            with self.subTest(platform=platform):
                self.assertIsInstance(create_adapter(self.snapshot(platform=platform), Path("account.json"), None), cls)


def controls(*items):
    locator = MagicMock()
    locator.count = AsyncMock(return_value=len(items))
    locator.nth.side_effect = lambda index: items[index]
    return locator


def button():
    item = MagicMock()
    item.is_visible = AsyncMock(return_value=True)
    item.is_enabled = AsyncMock(return_value=True)
    item.scroll_into_view_if_needed = AsyncMock()
    item.click = AsyncMock()
    return item


class NoteSubmissionTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, **changes):
        data = dict(platform="xiaohongshu", title="测试标题", mode="publish", options={}, tags=[])
        data.update(changes)
        return create_note_adapter(data)

    def page(self):
        page = MagicMock()
        page.wait_for_timeout = AsyncMock()
        page.get_by_text.return_value.filter.return_value.count = AsyncMock(return_value=0)
        return page

    def prepared(self, adapter):
        page = self.page()
        control = button()
        page.get_by_role.return_value = controls(control)
        adapter._note_scope = page
        adapter._note_document = MagicMock()
        adapter.verify_note = AsyncMock()
        return page, control

    async def test_preview_never_reaches_submit_callback(self):
        adapter = self.adapter(mode="preview")
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, "预览任务禁止"):
            await adapter.submit(self.page(), callback)
        callback.assert_not_called()

    async def test_unprepared_note_cannot_submit(self):
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, "尚未完成准备"):
            await self.adapter().submit(self.page(), callback)
        callback.assert_not_called()

    async def test_submit_boundary_precedes_click_and_timeout_is_not_retried(self):
        adapter = self.adapter()
        page, control = self.prepared(adapter)
        events = []
        async def timeout(**kwargs):
            events.append("click")
            raise TimeoutError("connection lost")
        control.click.side_effect = timeout
        with self.assertRaises(TimeoutError):
            await adapter.submit(page, lambda: events.append("boundary"))
        with self.assertRaisesRegex(PreparationError, "已经尝试"):
            await adapter.submit(page, lambda: events.append("retry"))
        self.assertEqual(events, ["boundary", "click"])
        control.click.assert_awaited_once()

    async def test_boundary_write_failure_never_clicks(self):
        adapter = self.adapter()
        page, control = self.prepared(adapter)
        callback = MagicMock(side_effect=RuntimeError("database unavailable"))
        with self.assertRaises(RuntimeError):
            await adapter.submit(page, callback)
        control.click.assert_not_awaited()

    async def test_ambiguous_publish_buttons_fail_before_boundary(self):
        adapter = self.adapter()
        page, control = self.prepared(adapter)
        page.get_by_role.return_value = controls(control, button())
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, "唯一"):
            await adapter.submit(page, callback)
        callback.assert_not_called()
        control.click.assert_not_awaited()

    async def test_new_blob_or_wrong_host_does_not_prove_upload_completion(self):
        for url in ("blob:https://creator.xiaohongshu.com/photo", "https://evil.test/photo.png"):
            with self.subTest(url=url):
                adapter, page = self.adapter(), self.page()
                adapter._album_images = AsyncMock(return_value=[dict(src=url, ready=True)])
                doc = PreparedDocument("", "", "", [Path("/tmp/a.png")], [], [])
                with self.assertRaisesRegex(PreparationError, "上传完成"):
                    await adapter._wait_uploaded(page, page, doc, 0)
                self.assertEqual(doc.uploaded_urls, [])

    async def test_each_image_is_appended_and_order_cannot_change(self):
        adapter, page = self.adapter(), self.page()
        first, second = "https://img.xhscdn.com/first.png", "https://img.xhscdn.com/second.png"
        adapter._album_images = AsyncMock(return_value=[dict(src=first, ready=True)])
        doc = PreparedDocument("", "", "", [], [], [])
        await adapter._wait_uploaded(page, page, doc, 0)
        adapter._album_images.return_value = [dict(src=second, ready=True), dict(src=first, ready=True)]
        with self.assertRaisesRegex(PreparationError, "顺序异常"):
            await adapter._wait_uploaded(page, page, doc, 1)
        self.assertEqual(doc.uploaded_urls, [first])

    async def test_restored_draft_images_block_before_new_upload(self):
        adapter, page = self.adapter(), self.page()
        adapter._open_note = AsyncMock()
        adapter._scope = AsyncMock(return_value=page)
        adapter._install_preview_guard = AsyncMock()
        adapter._album_images = AsyncMock(return_value=[dict(src="https://img.xhscdn.com/old.png", ready=True)])
        adapter._upload_one = AsyncMock()
        doc = PreparedDocument("", "", "正文", [Path("/tmp/new.png")], [], [])
        with patch("utils.articles.notes.prepare_note_document", return_value=doc):
            with self.assertRaisesRegex(PreparationError, "恢复的草稿"):
                await adapter.prepare_note(page, {})
        adapter._upload_one.assert_not_awaited()

    async def test_final_readback_rejects_truncation_extra_image_or_reordering(self):
        urls = ["https://img.xhscdn.com/first.png", "https://img.xhscdn.com/second.png"]
        adapter, page = self.adapter(), self.page()
        adapter._note_scope = page
        adapter._note_editor = MagicMock()
        adapter._note_editor.evaluate = AsyncMock(return_value={"value": "完整正文\n末段"})
        adapter.verify_title = AsyncMock()
        adapter._note_document = PreparedDocument("", "", "完整正文\n末段", [], [], [], urls)
        adapter._album_images = AsyncMock(return_value=[dict(src=url, ready=True) for url in urls])
        await adapter.verify_note(page)
        adapter._note_editor.evaluate.return_value = {"value": "完整正文"}
        with self.assertRaisesRegex(PreparationError, "完整正文"):
            await adapter.verify_note(page)
        adapter._note_editor.evaluate.return_value = {"value": "完整正文\n末段"}
        for sources in (list(reversed(urls)), urls + ["blob:https://creator.xiaohongshu.com/extra"]):
            adapter._album_images.return_value = [dict(src=url, ready=True) for url in sources]
            with self.assertRaisesRegex(PreparationError, "数量或顺序"):
                await adapter.verify_note(page)


@unittest.skipUnless(os.environ.get("OMNIPOST_BROWSER_TESTS") == "1", "需显式开启本地浏览器测试")
class NoteBrowserTests(unittest.IsolatedAsyncioTestCase):
    """本地 DOM 和真实文件选择事件：网络全部截获，不访问发布平台。"""

    async def asyncSetUp(self):
        import conf
        from playwright.async_api import async_playwright
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.playwright = await async_playwright().start()
        options = {"headless": True}
        if getattr(conf, "LOCAL_CHROME_PATH", ""):
            options["executable_path"] = conf.LOCAL_CHROME_PATH
        self.browser = await self.playwright.chromium.launch(**options)
        self.context = await self.browser.new_context()
        await self.context.route("**/*", lambda route: route.abort())
        self.page = await self.context.new_page()
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jDlsAAAAASUVORK5CYII=")
        await self.page.route("https://img.xhscdn.com/**", lambda route: route.fulfill(body=png, content_type="image/png"))
        self.assets = {}
        for name in ("first", "second"):
            path = Path(self.temp.name) / (name + ".png")
            path.write_bytes(png)
            self.assets[name] = dict(path=str(path), mime_type="image/png", width=1, height=1)
        await self.page.set_content('''<!doctype html><html><body>
            <input type="file" accept="image/png" multiple hidden>
            <section id="album"></section><input placeholder="填写标题">
            <div contenteditable="true"><p data-placeholder="输入正文描述">旧的文字</p></div>
            <button id="publish">发布</button><script>
            window.submits=0;document.querySelector('#publish').onclick=()=>window.submits++;
            document.querySelector('input[type=file]').onchange=event=>{
                for(const file of event.target.files){
                    const img=document.createElement('img');img.width=80;img.height=80;
                    img.src='https://img.xhscdn.com/'+file.name;
                    document.querySelector('#album').appendChild(img);
                }
            };</script></body></html>''')

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    def adapter(self, mode="publish"):
        adapter = create_note_adapter(dict(platform="xiaohongshu", title="完整标题", mode=mode,
            content_html='<p>首段<a href="https://example.org">资料</a></p><img data-asset-id="first">'
                         '<p>末段</p><img data-asset-id="second">', options={}, tags=[]))
        # 仅替换导航；生产的上传、图片轮询、正文填写、读回及提交边界全部照常执行。
        adapter._open_note = AsyncMock()
        return adapter

    async def test_full_album_preparation_and_single_submit_against_real_dom(self):
        adapter = self.adapter()
        editor, document = await adapter.prepare_note(self.page, self.assets)
        self.assertEqual(await _note_value(editor), "首段资料（https://example.org）\n末段")
        self.assertEqual(await self.page.get_by_placeholder("填写标题").input_value(), "完整标题")
        self.assertEqual(document.uploaded_urls, ["https://img.xhscdn.com/first.png", "https://img.xhscdn.com/second.png"])
        marks = []
        await adapter.submit(self.page, lambda: marks.append(True))
        with self.assertRaisesRegex(PreparationError, "已经尝试"):
            await adapter.submit(self.page, lambda: marks.append(False))
        self.assertEqual(marks, [True])
        self.assertEqual(await self.page.evaluate("window.submits"), 1)

    async def test_actual_dom_reordering_blocks_submission(self):
        adapter = self.adapter()
        await adapter.prepare_note(self.page, self.assets)
        await self.page.locator('#album').evaluate('el=>el.appendChild(el.firstChild)')
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, "顺序发生变化"):
            await adapter.submit(self.page, callback)
        callback.assert_not_called()
        self.assertEqual(await self.page.evaluate("window.submits"), 0)

    async def test_restored_album_in_actual_dom_is_not_discarded_as_ui(self):
        await self.page.locator('#album').evaluate('''el=>{
            const img=document.createElement('img');img.src='https://img.xhscdn.com/old.png';
            img.width=80;img.height=80;el.appendChild(img);
        }''')
        with self.assertRaisesRegex(PreparationError, "恢复的草稿"):
            await self.adapter().prepare_note(self.page, self.assets)
        self.assertEqual(await self.page.locator('#album img').count(), 1)

    async def test_preview_guard_blocks_publish_and_fabiao_but_allows_navigation(self):
        adapter = self.adapter(mode="preview")
        await self.page.locator('body').evaluate('''el=>{
            for(const text of ['发表','发表图文']){
                const button=document.createElement('button');button.textContent=text;
                button.onclick=()=>window.submits++;el.appendChild(button);
            }
        }''')
        await adapter.prepare_note(self.page, self.assets)
        self.assertTrue(await self.page.get_by_role('button', name='发布', exact=True).is_disabled())
        self.assertTrue(await self.page.get_by_role('button', name='发表', exact=True).is_disabled())
        self.assertFalse(await self.page.get_by_role('button', name='发表图文', exact=True).is_disabled())
        await self.page.get_by_role('button', name='发表', exact=True).dispatch_event('click')
        await self.page.keyboard.press('ControlOrMeta+Enter')
        self.assertEqual(await self.page.evaluate('window.submits'), 0)

    async def test_semantic_body_reader_keeps_blank_lines_and_indentation(self):
        editor = self.page.locator('[contenteditable=true]')
        for source, expected in (
            ('<p>首段</p><p>末段</p>', '首段\n末段'),
            ('<p>首段<br><br>末段</p>', '首段\n\n末段'),
            ('<p>def test():</p><p>&nbsp;&nbsp;&nbsp;&nbsp;return 1</p>', 'def test():\n    return 1'),
        ):
            with self.subTest(source=source):
                await editor.evaluate('(el,html)=>el.innerHTML=html', source)
                self.assertEqual((await _note_value(editor)).replace('\xa0', ' '), expected)

    async def test_tencent_receipt_is_read_from_child_frame(self):
        await self.page.evaluate('''()=>{
            const frame=document.createElement('iframe');frame.id='receipt';
            frame.srcdoc='<html><body><div role="alert">发表成功，等待审核</div></body></html>';
            document.body.appendChild(frame);
        }''')
        await self.page.frame_locator('#receipt').get_by_role('alert').wait_for(state='visible')
        adapter = create_note_adapter(dict(platform='tencent', title='测试标题', mode='publish'))
        result = await adapter.read_result(self.page)
        self.assertEqual(result['status'], 'submitted')


if __name__ == "__main__":
    unittest.main()

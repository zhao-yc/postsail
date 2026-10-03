"""淘宝图文的独立准备及一次提交；模拟账号表单，测试不访问发布平台。"""
import base64
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from utils.articles.browser import PreparationError, PreparedDocument
from utils.articles.taobao import (
    TAOBAO_EDITOR_URL, TAOBAO_STATEMENTS, TaobaoNoteAdapter, _is_taobao_frame,
    validate_taobao_snapshot,
)


def snapshot(**changes):
    data = dict(platform="taobao", title="原图标题", mode="publish", tags=[],
                options={"statement": "内容无需标注"},
                content_html='<p>第一段</p><img data-asset-id="first"><p>最后一段</p>')
    data.update(changes)
    return data


class TaobaoValidationTests(unittest.TestCase):
    def setUp(self):
        self.assets = {"first": dict(width=720, height=720)}

    def test_explicit_statement_and_all_image_dimensions_are_required(self):
        for options in ({}, {"statement": None}, {"statement": ""}, {"statement": "unknown"}):
            with self.subTest(options=options), self.assertRaisesRegex(PreparationError, "明确选择"):
                validate_taobao_snapshot(snapshot(options=options), self.assets)
        for statement in TAOBAO_STATEMENTS:
            validate_taobao_snapshot(snapshot(options={"statement": statement}), self.assets)
        self.assets["first"]["height"] = 719
        with self.assertRaisesRegex(PreparationError, "至少 720"):
            validate_taobao_snapshot(snapshot(), self.assets)

    def test_tags_products_and_other_unimplemented_fields_cannot_be_lost(self):
        with self.assertRaisesRegex(PreparationError, "原生内容标签"):
            validate_taobao_snapshot(snapshot(tags=["品牌"]), self.assets)
        for field in ("goods_id", "shopping_cart", "music", "schedule", "brand_tag"):
            with self.subTest(field=field), self.assertRaisesRegex(PreparationError, "尚不支持"):
                validate_taobao_snapshot(snapshot(options={"statement": "内容无需标注", field: "123"}), self.assets)

    def test_selected_cover_must_be_first_image_when_already_in_body(self):
        self.assets["second"] = dict(width=720, height=720)
        with self.assertRaisesRegex(PreparationError, "首位"):
            validate_taobao_snapshot(snapshot(cover_asset_id="second", content_html=
                '<img data-asset-id="first"><img data-asset-id="second">'), self.assets)

    def test_iframe_requires_https_platform_host_and_verified_path(self):
        marker = "/gg_publish/gg-picture"
        self.assertTrue(_is_taobao_frame("https://huodong.taobao.com/wow/z/guang" + marker, marker))
        for url in ("https://evil.test" + marker, "https://taobao.com.evil.test" + marker,
                    "http://huodong.taobao.com" + marker, "https://huodong.taobao.com/gg-video"):
            self.assertFalse(_is_taobao_frame(url, marker))


def control():
    item = MagicMock()
    item.is_visible = AsyncMock(return_value=True)
    item.is_enabled = AsyncMock(return_value=True)
    item.scroll_into_view_if_needed = AsyncMock()
    item.click = AsyncMock()
    return item


def locator(*items):
    result = MagicMock()
    result.count = AsyncMock(return_value=len(items))
    result.nth.side_effect = lambda index: items[index]
    return result


class TaobaoSubmissionTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, **changes):
        return TaobaoNoteAdapter(snapshot(**changes), None)

    def prepared(self, adapter):
        page, button = MagicMock(), control()
        page.frames = []
        page.get_by_role.return_value = locator(button)
        adapter._note_scope, adapter._note_document = page, MagicMock()
        adapter.verify_note = AsyncMock()
        return page, button

    async def test_preview_and_unprepared_cannot_cross_submission_boundary(self):
        for adapter in (self.adapter(mode="preview"), self.adapter()):
            page = MagicMock()
            page.frames = []
            boundary = MagicMock()
            with self.assertRaises(PreparationError):
                await adapter.submit(page, boundary)
            boundary.assert_not_called()

    async def test_callback_before_one_click_even_when_click_times_out(self):
        adapter = self.adapter()
        page, button = self.prepared(adapter)
        events = []
        async def fail(**kwargs):
            events.append("click")
            raise TimeoutError("receipt missing")
        button.click.side_effect = fail
        with self.assertRaises(TimeoutError):
            await adapter.submit(page, lambda: events.append("boundary"))
        with self.assertRaisesRegex(PreparationError, "已经尝试"):
            await adapter.submit(page, lambda: events.append("retry"))
        self.assertEqual(events, ["boundary", "click"])

    async def test_callback_failure_or_ambiguous_control_never_clicks(self):
        adapter = self.adapter()
        page, button = self.prepared(adapter)
        callback = MagicMock(side_effect=RuntimeError("database unavailable"))
        with self.assertRaises(RuntimeError):
            await adapter.submit(page, callback)
        button.click.assert_not_awaited()
        page.get_by_role.return_value = locator(button, control())
        callback.reset_mock()
        with self.assertRaisesRegex(PreparationError, "唯一"):
            await adapter.submit(page, callback)
        callback.assert_not_called()

    async def test_gallery_must_match_this_uploaded_image_and_complete_album_order(self):
        adapter = self.adapter()
        adapter._pending_uploaded_url = "https://img.alicdn.com/new.png"
        page = MagicMock()
        page.wait_for_timeout = AsyncMock()
        page.get_by_text.return_value.filter.return_value.count = AsyncMock(return_value=0)
        document = PreparedDocument("", "", "", [], [], [])
        adapter._album_images = AsyncMock(return_value=[dict(src="https://img.alicdn.com/old.png", ready=True)])
        with self.assertRaisesRegex(PreparationError, "读回不一致"):
            await adapter._wait_uploaded(page, page, document, 0)
        self.assertEqual(document.uploaded_urls, [])
        adapter._album_images.return_value = [dict(src=adapter._pending_uploaded_url, ready=True)]
        await adapter._wait_uploaded(page, page, document, 0)
        self.assertEqual(document.uploaded_urls, [adapter._pending_uploaded_url])
        adapter._album_images.return_value = [dict(src="https://img.alicdn.com/other.png", ready=True)]
        with self.assertRaisesRegex(PreparationError, "顺序异常"):
            await adapter._wait_uploaded(page, page, document, 1)

    async def test_untrusted_blob_or_unloaded_image_never_confirms_upload(self):
        for image in (dict(src="blob:https://huodong.taobao.com/pic", ready=True),
                      dict(src="https://evil.test/pic.png", ready=True),
                      dict(src="https://img.alicdn.com/pic.png", ready=False)):
            adapter = self.adapter()
            adapter._pending_uploaded_url = image["src"]
            adapter._album_images = AsyncMock(return_value=[image])
            page = MagicMock()
            page.wait_for_timeout = AsyncMock()
            page.get_by_text.return_value.filter.return_value.count = AsyncMock(return_value=0)
            with self.subTest(image=image), self.assertRaisesRegex(PreparationError, "读回不一致"):
                await adapter._wait_uploaded(page, page, PreparedDocument("", "", "", [], [], []), 0)

    async def test_new_platform_feedback_is_required_drafts_and_redirects_are_unknown(self):
        adapter = self.adapter()
        adapter._submit_started = True
        adapter._feedback_before = {"发布成功"}
        page, frame = MagicMock(), MagicMock()
        page.frames = [frame]
        page.url = "https://creator.guanghe.taobao.com/page/manage"
        adapter._feedback = AsyncMock(return_value=["发布成功", "草稿保存成功"])
        with patch("utils.articles.taobao.has_visible_challenge", AsyncMock(return_value=False)):
            self.assertEqual((await adapter.read_result(page))["status"], "unknown")
            adapter._feedback.return_value = ["提交成功"]
            self.assertEqual((await adapter.read_result(page))["status"], "submitted")
            adapter._feedback.return_value = ["提交成功", "发布失败"]
            self.assertEqual((await adapter.read_result(page))["status"], "failed")


FORM_URL = "https://huodong.taobao.com/wow/z/guang/gg_publish/gg-picture"
PICKER_URL = "https://huodong.taobao.com/sucai-selector-ng"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1ioAAAAASUVORK5CYII=")
FORM = '''<html><body>
<div id="picture-upload-wrapper"><button class="next-picture-uploader" onclick="openPicker()">上传图片</button></div>
<input placeholder="加个标题让内容更吸引人" maxlength="30">
<div data-cangjie-content="true" contenteditable="true" style="min-height:60px"></div>
<label class="next-radio-wrapper"><input type="radio" name="statement">内容无需标注</label>
<label class="next-radio-wrapper" id="schedule"><input type="radio" name="time"></label><span>定时发布</span>
<button onclick="window.clicks=(window.clicks||0)+1;document.getElementById('feedback').textContent='提交成功'">立即发布</button>
<div class="next-message" id="feedback">草稿保存成功</div>
<script>
function openPicker(){const f=document.createElement('iframe');f.src='https://huodong.taobao.com/sucai-selector-ng';f.id='picker';document.body.append(f)}
function addImage(src){const i=document.createElement('img');i.src=src;i.width=50;i.height=50;document.getElementById('picture-upload-wrapper').append(i);document.getElementById('picker').remove()}
</script></body></html>'''
PICKER = '''<html><body>
<button onclick="document.getElementById('file').click()">本地上传</button>
<input id="file" type="file" accept="image/*" style="display:none" onchange="window.uploadName=this.files[0].name;document.getElementById('done').hidden=false">
<button id="done" hidden onclick="makeCard()">完成</button><div id="cards"></div>
<button onclick="parent.addImage(document.querySelector('label input:checked').parentElement.querySelector('img').src)">确定</button>
<script>function makeCard(){const card=document.createElement('div');const label=document.createElement('label');
const check=document.createElement('input');check.type='checkbox';const img=document.createElement('img');img.src='https://img.alicdn.com/'+window.uploadName;img.width=30;img.height=30;
label.append(check,img,document.createTextNode(window.uploadName));card.append(label);document.getElementById('cards').append(card);}</script>
</body></html>'''


@unittest.skipUnless(os.environ.get("OMNIPOST_BROWSER_TESTS") == "1", "需显式开启本地浏览器测试")
class TaobaoBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import conf
        from playwright.async_api import async_playwright
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True, executable_path=conf.LOCAL_CHROME_PATH or None)
        self.context = await self.browser.new_context()
        async def route(request):
            url = request.request.url
            if url.startswith("https://img.alicdn.com/"):
                await request.fulfill(body=PNG, content_type="image/png")
            elif url == PICKER_URL:
                await request.fulfill(body=PICKER, content_type="text/html; charset=utf-8")
            elif url == FORM_URL:
                await request.fulfill(body=FORM, content_type="text/html; charset=utf-8")
            else:
                await request.fulfill(body='<iframe style="width:1000px;height:750px" src="' + FORM_URL + '"></iframe>', content_type="text/html; charset=utf-8")
        await self.context.route("**/*", route)
        self.page = await self.context.new_page()
        self.assets = {}
        for name in ("first", "second"):
            path = Path(self.temp.name) / (name + ".png")
            path.write_bytes(PNG)
            self.assets[name] = dict(path=str(path), mime_type="image/png", width=720, height=720)

    async def asyncTearDown(self):
        await self.context.close()
        await self.browser.close()
        await self.playwright.stop()

    async def test_two_original_images_and_all_text_verified_before_one_submit(self):
        adapter = TaobaoNoteAdapter(snapshot(content_html='<p>第一段</p><img data-asset-id="first">'
            '<p>最后一段</p><img data-asset-id="second">'), None)
        editor, document = await adapter.prepare_note(self.page, self.assets)
        self.assertEqual(document.expected_text, "第一段\n最后一段")
        self.assertEqual(len(document.uploaded_urls), 2)
        self.assertNotEqual(document.uploaded_urls[0], document.uploaded_urls[1])
        self.assertEqual((await adapter.read_result(self.page))["status"], "unknown")
        boundary = MagicMock()
        await adapter.submit(self.page, boundary)
        boundary.assert_called_once()
        self.assertEqual(await adapter._note_scope.evaluate("window.clicks"), 1)
        self.assertEqual((await adapter.read_result(self.page))["status"], "submitted")
        with self.assertRaisesRegex(PreparationError, "已经尝试"):
            await adapter.submit(self.page, boundary)
        self.assertEqual(await adapter._note_scope.evaluate("window.clicks"), 1)

    async def test_preview_guard_blocks_manual_publish_inside_iframe(self):
        adapter = TaobaoNoteAdapter(snapshot(mode="preview"), None)
        await adapter.prepare_note(self.page, self.assets)
        await adapter._note_scope.get_by_role("button", name="立即发布", exact=True).evaluate("el=>el.click()")
        self.assertIsNone(await adapter._note_scope.evaluate("window.clicks"))
        with self.assertRaisesRegex(PreparationError, "预览任务禁止"):
            await adapter.submit(self.page, MagicMock())

    async def test_truncated_body_schedule_required_field_and_statement_mutation_stop(self):
        adapter = TaobaoNoteAdapter(snapshot(), None)
        editor, document = await adapter.prepare_note(self.page, self.assets)
        await editor.fill("第一段")
        with self.assertRaisesRegex(PreparationError, "完整正文"):
            await adapter.verify_note(self.page)
        await editor.fill(document.expected_text)
        await adapter._note_scope.locator("#schedule input").check()
        with self.assertRaisesRegex(PreparationError, "定时发布"):
            await adapter.verify_note(self.page)
        await adapter._note_scope.locator("#schedule input").evaluate("el=>el.checked=false")
        await adapter._note_scope.evaluate("""document.body.insertAdjacentHTML('beforeend',
            '<label class="next-radio-wrapper"><input type="radio" name="adjacent" checked>立即发布</label>'+
            '<label class="next-radio-wrapper"><input type="radio" name="adjacent">定时发布</label>')""")
        await adapter.verify_note(self.page)
        await adapter._note_scope.evaluate("document.body.insertAdjacentHTML('beforeend','<input required>')")
        with self.assertRaisesRegex(PreparationError, "必填字段"):
            await adapter.verify_note(self.page)
        await adapter._note_scope.locator("input[required]").fill("补充")
        await adapter._note_scope.locator('input[name="statement"]').evaluate("el=>el.checked=false")
        with self.assertRaisesRegex(PreparationError, "声明读回"):
            await adapter.verify_note(self.page)

"""京东提交协议与浏览器边界回归；受控页面不代表真实账号发布验收。"""
import base64
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import AsyncMock, MagicMock

from utils.articles.browser import PreparationError, PreparedDocument, launch_article_browser
from utils.articles.jingdong import JingdongArticleAdapter, _publish_request, _submission_id


TITLE = "京东原生文章完整测试标题"
BODY = [{"type": 1, "content": '<p isRichText="true">本次正文</p>'}]
COVER = "https://m.360buyimg.com/ceco/cover.png"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jDlsAAAAASUVORK5CYII=")


def make_adapter(mode="publish"):
    adapter = JingdongArticleAdapter({"title": TITLE, "mode": mode}, Path("cover.png"))
    adapter._description_data = BODY
    adapter._cover_url = COVER
    return adapter


def payload(**changes):
    data = {"title": TITLE, "style": 0, "descriptionStr": json.dumps(BODY), "indexImage": [COVER], "tags": []}
    return data | changes


class JingdongProtocolTests(unittest.IsolatedAsyncioTestCase):
    def test_native_form_envelope_is_required(self):
        request = SimpleNamespace(url="https://api.m.jd.com/articleSavePublish", method="POST",
                                  post_data=urlencode({"functionId": "articleSavePublish", "body": json.dumps(payload())}))
        self.assertEqual(_publish_request(request), (True, payload()))
        request.post_data = json.dumps(payload())
        self.assertEqual(_publish_request(request), (True, None))
        request.url = "https://api.m.jd.com/articleSaveDraft"
        self.assertEqual(_publish_request(request), (False, None))
        request.url = "https://evil.test/articleSavePublish"
        self.assertEqual(_publish_request(request), (False, None))

    def test_only_explicit_success_with_real_id_is_a_receipt(self):
        for body in ({"success": True, "data": "123"}, {"result_code": 0, "result": 123},
                     {"resultCode": "0", "data": "123"}, {"busiCode": "0", "data": "123"}):
            self.assertEqual(_submission_id(body), "123")
        for body in ({"data": "123"}, {"success": True, "data": True}, {"success": True, "data": 0},
                     {"success": True, "code": False, "data": "123"},
                     {"success": True, "code": 403, "data": "123"}, {"success": False, "resultCode": "0", "data": 123},
                     {"success": True, "data": {"id": "123"}}, {"success": True, "data": "draft-123"}):
            with self.subTest(body=body):
                self.assertIsNone(_submission_id(body))

    def test_same_title_other_body_wrong_style_cover_and_tags_are_rejected(self):
        adapter = make_adapter()
        self.assertTrue(adapter._matches_submission(payload()))
        for changes in ({"descriptionStr": '[{"type":1,"content":"另一篇正文"}]'}, {"style": False},
                        {"style": 3}, {"id": "old-draft"}, {"indexImage": []}, {"indexImage": ["https://m.360buyimg.com/other"]},
                        {"tags": [{"name": "别的标签"}]}, {"title": "另一个标题"}):
            with self.subTest(changes=changes):
                self.assertFalse(adapter._matches_submission(payload(**changes)))

    def test_serializer_rejects_cards_inline_images_and_active_content(self):
        adapter = make_adapter()
        self.assertIn("本次正文", adapter._serialized_html(BODY))
        for data in ([{"type": 3, "content": "card"}], [{"type": True, "content": "wrong type"}],
                     [{"type": 2, "content": "blob:local"}], [{"type": 2, "content": "https://evil.test/image"}],
                     [{"type": 1, "content": '<p><img src="https://m.360buyimg.com/other"></p>'}],
                     [{"type": 1, "content": '<p onclick="publish()">text</p>'}]):
            with self.subTest(data=data), self.assertRaises(PreparationError):
                adapter._serialized_html(data)

    async def test_options_fail_before_upload_for_missing_cover_or_freetext_tags(self):
        adapter = JingdongArticleAdapter({"title": TITLE}, None)
        with self.assertRaisesRegex(PreparationError, "需要封面"):
            await adapter.apply_options(MagicMock(), MagicMock())
        adapter = JingdongArticleAdapter({"title": TITLE, "tags": ["普通话题"]}, Path("cover.png"))
        with self.assertRaisesRegex(PreparationError, "自由话题"):
            await adapter.apply_options(MagicMock(), MagicMock())

    async def test_serializer_must_match_task_not_just_dom_and_own_payload(self):
        adapter = make_adapter()
        document = PreparedDocument("<p>保留&lt;foo&gt;文字</p>", "<p>保留&lt;foo&gt;文字</p>", "保留<foo>文字", [], [], [])
        adapter._read_native = AsyncMock(return_value={"html": "<p>保留&lt;foo&gt;文字</p>", "data": [{"type": 1, "content": "<p>保留文字</p>"}]})
        with self.assertRaisesRegex(PreparationError, "本次内容不一致"):
            await adapter.verify_body(MagicMock(), MagicMock(), document)

    async def test_serializer_must_preserve_image_between_its_paragraphs(self):
        adapter = make_adapter()
        image = "https://m.360buyimg.com/ceco/body.png"
        document = PreparedDocument("", "<p>前OMNIPOSTIMAGE0000END后</p>", "前后", [Path("image")],
                                    ["OMNIPOSTIMAGE0000END"], [], [image])
        adapter._read_native = AsyncMock(return_value={"html": "<p>前后</p>", "data": [
            {"type": 1, "content": "<p>前后</p>"}, {"type": 2, "content": image}]})
        with self.assertRaisesRegex(PreparationError, "位置发生变化"):
            await adapter.verify_body(MagicMock(), MagicMock(), document)

    async def test_braft_atomic_placeholder_is_not_mistaken_for_article_text(self):
        adapter = make_adapter()
        image = "https://m.360buyimg.com/ceco/body.png"
        data = [{"type": 1, "content": "<p>前a</p>"}, {"type": 2, "content": image},
                {"type": 1, "content": "<p>后a</p>"}]
        document = PreparedDocument("", "<p>前aOMNIPOSTIMAGE0000END后a</p>", "前a后a", [Path("image")],
                                    ["OMNIPOSTIMAGE0000END"], [], [image])
        adapter._read_native = AsyncMock(return_value={"text": "前a\na\n后a", "data": data,
                                                       "html": '<p>前a</p><img src="' + image + '"><p>后a</p>'})
        adapter.verify_rich_document = AsyncMock()
        await adapter.verify_body(MagicMock(), MagicMock(), document)
        self.assertEqual(adapter._description_data, data)


@unittest.skipUnless(os.environ.get("OMNIPOST_BROWSER_TESTS") == "1", "受控浏览器用例需显式启用")
class JingdongBrowserBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        import conf
        self.runtime = await async_playwright().start()
        self.browser = await launch_article_browser(self.runtime, True, getattr(conf, "LOCAL_CHROME_PATH", ""))
        self.context = await self.browser.new_context(service_workers="block")
        self.page = await self.context.new_page()
        self.network_calls = []
        self.response = {"success": True, "data": "321"}

        async def fixture(route):
            if urlparse_host(route.request.url) == "api.m.jd.com":
                self.network_calls.append(route.request.url)
                await route.fulfill(content_type="application/json", body=json.dumps(self.response))
            elif route.request.url.endswith(".png"):
                await route.fulfill(content_type="image/png", body=PNG)
            else:
                await route.fulfill(content_type="text/html; charset=utf-8", body='''<!doctype html><html><body>
                  <div class="dr-publish-article-wrapper" data-spm-c="c00009560">
                    <div class="dr-create-form"><input id="title"><div id="module-richtextNew"><div id="richtext-editor-box">
                    <div class="public-DraftEditor-content" contenteditable="true" style="height:100px"></div></div></div></div>
                    <div class="article-imageArea"><div class="dr-upload-image-component" id="covers"></div></div>
                    <div class="page-footer"><button data-spm-click="publishArticleSubmit">发布</button>
                    <button data-spm-click="publishArticleDraft">保存草稿</button></div>
                  </div></body></html>''')
        await self.context.route("**/*", fixture)

    async def asyncTearDown(self):
        await self.context.close()
        await self.browser.close()
        await self.runtime.stop()

    async def request(self, endpoint="articleSavePublish", data=None):
        return await self.page.evaluate("""async ({endpoint,data})=>{try{const response=await fetch('https://api.m.jd.com/'+endpoint,
            {method:'POST',body:new URLSearchParams({functionId:endpoint,body:JSON.stringify(data)})});return response.ok;}catch{return false;}}""",
            {"endpoint": endpoint, "data": data or payload()})

    async def test_preview_blocks_publish_and_draft_before_navigation(self):
        adapter = make_adapter("preview")
        await adapter.install_preparation_guard(self.page)
        await self.page.goto(adapter.editor_url)
        self.assertFalse(await self.request())
        self.assertFalse(await self.request("articleSaveDraft"))
        self.assertEqual(self.network_calls, [])

    async def test_publish_requires_boundary_matching_task_and_only_one_request(self):
        adapter = make_adapter()
        await adapter.install_preparation_guard(self.page)
        await self.page.goto(adapter.editor_url)
        self.assertFalse(await self.request())
        await adapter._mark_submit(lambda: None)
        self.assertFalse(await self.request(data=payload(descriptionStr='[{"type":1,"content":"different"}]')))
        self.assertFalse(await self.request(data=payload(indexImage=[])))
        self.assertTrue(await self.request())
        self.assertFalse(await self.request())
        self.assertEqual(len(self.network_calls), 1)
        result = await adapter.read_result(self.page)
        self.assertEqual((result["status"], result["platform_id"]), ("submitted", "321"))
        self.assertNotIn("url", result)

    async def test_failed_receipt_and_list_navigation_never_prove_publication(self):
        self.response = {"success": False, "data": "321"}
        adapter = make_adapter()
        await adapter.install_preparation_guard(self.page)
        await self.page.goto(adapter.editor_url)
        await adapter._mark_submit(lambda: None)
        await self.request()
        await self.page.goto("https://dr.jd.com/n/content-list.html?style=0")
        self.assertEqual((await adapter.read_result(self.page))["status"], "unknown")

    async def test_draft_success_is_not_article_submission(self):
        adapter = make_adapter()
        await adapter.install_preparation_guard(self.page)
        await self.page.goto(adapter.editor_url)
        await self.request("articleSaveDraft")
        self.assertEqual((await adapter.read_result(self.page))["status"], "unknown")

    async def test_mark_failure_prevents_button_click_and_network(self):
        adapter = make_adapter()
        adapter._document = object()
        adapter.verify_title = AsyncMock()
        adapter.verify_options = AsyncMock()
        adapter.verify_body = AsyncMock()
        await adapter.install_preparation_guard(self.page)
        await self.page.goto(adapter.editor_url)
        await self.page.locator(adapter.publish_selector).evaluate("el=>el.onclick=()=>window.clicked=true")
        def fail():
            raise RuntimeError("cannot persist")
        with self.assertRaisesRegex(RuntimeError, "cannot persist"):
            await adapter.submit(self.page, fail)
        self.assertFalse(await self.page.evaluate("Boolean(window.clicked)"))
        self.assertEqual(self.network_calls, [])

    async def test_existing_draft_is_rejected_before_writing(self):
        adapter = make_adapter()
        adapter._read_native = AsyncMock(return_value={"text": "旧稿正文", "empty": False})
        with self.assertRaisesRegex(PreparationError, "旧稿"):
            await adapter.open_editor(self.page)
        self.assertEqual(await self.page.locator(adapter.title_selector).input_value(), "")

    async def test_cover_requires_its_own_finished_native_file_state(self):
        adapter = make_adapter()
        await self.page.goto(adapter.editor_url)
        # 本地 blob 预览和平台默认占位图均不足以证明真实封面已上传。
        await self.page.evaluate("""({src})=>{const item=document.createElement('div');item.className='file-item';
          item.innerHTML='<img src="'+src+'"><div class="upload-status">上传中</div>';
          const fiber={stateNode:item,memoizedProps:{file:{blobImg:'blob:local'}}};
          const root={child:fiber,stateNode:{}};root.stateNode.current=root;fiber.return=root;
          item.__reactFiber$fixture=fiber;
          document.querySelector('#covers').append(item);} """, {"src": COVER})
        self.assertEqual(await adapter._cover_images(self.page), [{"src": "", "ready": False}])
        await self.page.locator(adapter.cover_items).evaluate("""(el,src)=>{
          el.querySelector('.upload-status').remove();const edit=document.createElement('div');edit.className='image-edit-wrapper';el.append(edit);
          el.__reactFiber$fixture.memoizedProps.file.img=src;}""", COVER)
        self.assertEqual(await adapter._cover_images(self.page), [{"src": COVER, "ready": True}])
        await self.page.locator(adapter.cover_items).evaluate("el=>el.__reactFiber$fixture.memoizedProps.file.error='上传失败'")
        self.assertFalse((await adapter._cover_images(self.page))[0]["ready"])

    async def test_cover_reads_committed_fiber_not_outdated_alternate(self):
        adapter = make_adapter()
        await self.page.goto(adapter.editor_url)
        await self.page.evaluate("""src=>{const item=document.createElement('div');item.className='file-item';
          item.innerHTML='<div class="image-edit-wrapper"></div>';
          const old={stateNode:item,memoizedProps:{file:{blobImg:'blob:old'}}};
          const current={stateNode:item,memoizedProps:{file:{img:src}}};
          const root={stateNode:{},child:current};root.stateNode.current=root;
          old.return=root;current.return=root;old.alternate=current;current.alternate=old;
          item.__reactFiber$fixture=old;document.querySelector('#covers').append(item);} """, COVER)
        self.assertEqual(await adapter._cover_images(self.page), [{"src": COVER, "ready": True}])
        # 旧树即使含成功 URL，也不能掩盖当前树真实上传失败。
        await self.page.locator(adapter.cover_items).evaluate("""el=>{
          const old=el.__reactFiber$fixture,current=old.alternate;
          old.memoizedProps.file.img=current.memoizedProps.file.img;
          current.memoizedProps.file={error:'failed'};}""")
        self.assertFalse((await adapter._cover_images(self.page))[0]["ready"])


def urlparse_host(url):
    from urllib.parse import urlparse
    return urlparse(url).hostname


if __name__ == "__main__":
    unittest.main()

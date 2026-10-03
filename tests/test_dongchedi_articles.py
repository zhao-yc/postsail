"""懂车号协议和受控浏览器边界；不代表真实账号登录、上传或发布验收。"""
import base64
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from utils.articles.browser import PreparationError, PreparedDocument, launch_article_browser
from utils.articles.dongchedi import DongchediArticleAdapter, _publish_request, _submission_id

TITLE = "懂车号原生文章测试标题"
BODY = "<p>本次完整正文</p>"
HORIZONTAL = {"status": 3, "uri": "tos/horizontal", "url": "https://p3.dcarimg.com/cover.png", "width": 800, "height": 600, "ai": False}
VERTICAL = {"status": 3, "uri": "tos/vertical", "url": "https://p3.dcarimg.com/portrait.png", "width": 600, "height": 800, "ai": False}
IMAGE = "https://p3.dcarimg.com/body.png"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jDlsAAAAASUVORK5CYII=")
API = "/motor/content_publish/publish_mp_article/v1"


def adapter(mode="publish"):
    result = DongchediArticleAdapter({"title": TITLE, "mode": mode}, Path("horizontal.png"))
    result._content = BODY
    result._covers = (copy.deepcopy(HORIZONTAL), copy.deepcopy(VERTICAL))
    result._ad_type = 2
    return result


def payload():
    return {"title": TITLE, "content": BODY, "save": 1, "source": 20, "extra": {
        "timer_status": 0, "timer_time": "", "article_ad_type": 2,
        "pgc_feed_covers": [{"url": HORIZONTAL["url"], "uri": HORIZONTAL["uri"], "thumb_width": 800, "thumb_height": 600}],
        "vertical_cover_image": json.dumps({"uri": VERTICAL["uri"], "width": 600, "height": 800, "is_ai_cover": False})}}


def native(**changes):
    return {"inited": True, "submitted": False, "submitting": False,
            "init": {"pgcId": "", "prefillId": "", "assignProofId": 0, "juguangEdit": False, "juguangType": 0},
            "bind": {"is_solicit": False}, "title": "", "html": "", "text": "", "images": [],
            "covers": [], "vertical": None, "cardTypes": [], "claimOrigin": 0, "isOriginalFirst": 0,
            "textUnits": 0, "htmlUnits": 0,
            "timingStatus": 0, "timingTime": "", "coverType": 2, "articleAdType": 2} | changes


class DongchediProtocolTests(unittest.TestCase):
    def test_only_official_article_endpoint_and_json(self):
        request = SimpleNamespace(url="https://mp.dcdapp.com" + API, method="POST", post_data_json=payload())
        self.assertEqual(_publish_request(request), (True, payload()))
        request.url = "https://mp.dcdapp.com/motor/content_publish/publish_mp_article/v2"
        self.assertEqual(_publish_request(request), (True, None))
        request.url = "https://evil.test" + API
        self.assertEqual(_publish_request(request), (False, None))

    def test_exact_native_success_envelope_and_positive_id(self):
        for success in ({"status": 0}, {"status": "success"}, {"message": "success"}):
            self.assertEqual(_submission_id(success | {"data": {"data": {"pgc_id": "123"}}}), "123")
        for response in ({"status": 0, "data": {"pgc_id": "123"}},
                         {"status": False, "data": {"data": {"pgc_id": "123"}}},
                         {"status": 1, "message": "success", "data": {"data": {"pgc_id": "123"}}},
                         {"data": {"data": {"pgc_id": "123"}}},
                         {"status": 0, "data": {"data": {"pgc_id": True}}},
                         {"status": 0, "data": {"data": {"pgc_id": "draft-123"}}}):
            self.assertIsNone(_submission_id(response))

    def test_publish_binds_body_dual_covers_ad_type_and_immediate_mode(self):
        value = adapter()
        self.assertTrue(value._matches_submission(payload()))
        changes = [{"title": "其他稿"}, {"content": "<p>同标题另一篇正文</p>"}, {"save": 0}, {"save": True},
                   {"source": "20"}, {"pgc_id": "123"}, {"proof_id": 123}, {"is_mcn": 1}, {"mp_act_id": "1"}]
        for change in changes:
            self.assertFalse(value._matches_submission(payload() | change))
        for key, changed in (("pgc_feed_covers", []), ("vertical_cover_image", "{}"),
                             ("article_ad_type", 3), ("timer_status", 1), ("timer_status", False), ("timer_time", "tomorrow")):
            request = payload()
            request["extra"][key] = changed
            self.assertFalse(value._matches_submission(request))

    def test_old_draft_and_nonstandard_native_modes_rejected(self):
        value = adapter()
        value._check_new_article(native())
        for changed in ({"inited": False}, {"submitted": True}, {"init": {"pgcId": "123"}},
                        {"bind": {"camp": {"task_id": 1}}}, {"claimOrigin": 1}, {"timingTime": "tomorrow"},
                        {"isMcn": 1}, {"topic": {"act_id": "1"}}):
            with self.assertRaises(PreparationError):
                value._check_new_article(native(**changed))

    def test_cover_constraints_are_applied_before_any_upload(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            horizontal = Path(folder) / "horizontal.png"
            vertical = Path(folder) / "vertical.png"
            Image.new("RGB", (532, 399)).save(horizontal)
            Image.new("RGB", (534, 712)).save(vertical)
            self.assertEqual(adapter()._check_cover_file(horizontal), (532, 399))
            self.assertEqual(adapter()._check_cover_file(vertical, True), (534, 712))
            for size in ((531, 399), (800, 800)):
                Image.new("RGB", size).save(horizontal)
                with self.assertRaises(PreparationError):
                    adapter()._check_cover_file(horizontal)

    def test_native_length_boundaries_use_browser_utf16_counts(self):
        adapter()._check_native_limits({"textUnits": 50000, "htmlUnits": 60000})
        for counts in ({"textUnits": 50001, "htmlUnits": 59999}, {"textUnits": 49999, "htmlUnits": 60001},
                       {"textUnits": True, "htmlUnits": 0}, {}):
            with self.assertRaises(PreparationError):
                adapter()._check_native_limits(counts)


class DongchediPreparationOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_covers_are_uploaded_before_body_then_only_verified(self):
        value = DongchediArticleAdapter({"title": TITLE}, Path("cover.png"))
        uploaded = []
        async def prepare(page, editor):
            uploaded.append((page, editor))
            value._covers = (HORIZONTAL, VERTICAL)
        value.apply_options = prepare
        await value.prepare_editor("page")
        self.assertEqual(uploaded, [("page", None)])
        value.verify_options = AsyncMock()
        await DongchediArticleAdapter.apply_options(value, "page", "editor")
        value.verify_options.assert_awaited_once_with("page", "editor")

    async def test_body_preparation_cannot_silently_replace_selected_cover(self):
        value = adapter()
        value._read_native = AsyncMock(return_value=native(covers=[HORIZONTAL], vertical=VERTICAL))
        value._cover_field = AsyncMock(return_value="field")
        value._verify_cover_image = AsyncMock()
        await value.verify_options("page", "editor")
        self.assertEqual(value._verify_cover_image.await_count, 2)
        value._read_native.return_value = native(covers=[HORIZONTAL | {"uri": "automatic-body-cover"}], vertical=VERTICAL)
        with self.assertRaisesRegex(PreparationError, "双封面"):
            await value.verify_options("page", "editor")


@unittest.skipUnless(os.environ.get("OMNIPOST_BROWSER_TESTS") == "1", "受控浏览器用例需显式启用")
class DongchediBrowserBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        import conf
        self.runtime = await async_playwright().start()
        self.browser = await launch_article_browser(self.runtime, True, getattr(conf, "LOCAL_CHROME_PATH", ""))
        self.context = await self.browser.new_context(service_workers="block")
        self.page = await self.context.new_page()
        self.requests = []
        self.response = {"status": 0, "data": {"data": {"pgc_id": "456"}}}

        async def route(request):
            if "/motor/content_publish/" in request.request.url:
                self.requests.append(request.request.post_data_json)
                return await request.fulfill(content_type="application/json", body=json.dumps(self.response))
            if request.request.url.endswith(".png"):
                return await request.fulfill(content_type="image/png", body=PNG)
            await request.fulfill(content_type="text/html; charset=utf-8", body='''<!doctype html>
              <div class="publish-editor"><textarea placeholder="请输入文章标题（2～30个汉字）"></textarea>
              <div class="syl-editor"><div class="ProseMirror" contenteditable="true" style="height:100px"></div></div></div>
              <div class="article-publish-form"><div id="cover"><div class="form-cell__title">横版封面</div><div><img id="preview"></div></div></div>
              <button id="publish">发布</button>''')
        await self.context.route("**/*", route)

    async def asyncTearDown(self):
        await self.context.close()
        await self.browser.close()
        await self.runtime.stop()

    async def request(self, data=None, endpoint=API):
        return await self.page.evaluate("""async ({data,endpoint})=>{try{return (await fetch(endpoint,
            {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})).ok;
            }catch{return false;}}""", {"data": data if data is not None else payload(), "endpoint": endpoint})

    async def test_preview_blocks_publish_draft_and_commercial(self):
        value = adapter("preview")
        await value.install_preparation_guard(self.page)
        await self.page.goto(value.editor_url)
        for request in (payload(), payload() | {"save": 0}):
            self.assertFalse(await self.request(request))
        self.assertFalse(await self.request(endpoint="/motor/content_publish/publish_mp_article/v2"))
        self.assertEqual(self.requests, [])

    async def test_guard_requires_persisted_boundary_exact_content_and_one_request(self):
        value = adapter()
        await value.install_preparation_guard(self.page)
        await self.page.goto(value.editor_url)
        self.assertFalse(await self.request())
        await value._mark_submit(lambda: None)
        self.assertFalse(await self.request(payload() | {"content": "另一个稿件"}))
        self.assertFalse(await self.request(payload() | {"save": 0}))
        self.assertTrue(await self.request())
        self.assertFalse(await self.request())
        self.assertEqual(len(self.requests), 1)
        result = await value.read_result(self.page)
        self.assertEqual((result["status"], result["platform_id"]), ("submitted", "456"))
        self.assertNotIn("url", result)

    async def test_failure_and_redirect_do_not_prove_submission(self):
        value = adapter()
        self.response = {"status": 1, "data": {"data": {"pgc_id": "456"}}}
        await value.install_preparation_guard(self.page)
        await self.page.goto(value.editor_url)
        await value._mark_submit(lambda: None)
        await self.request()
        await self.page.goto("https://mp.dcdapp.com/profile_v2/content-manage")
        self.assertEqual((await value.read_result(self.page))["status"], "unknown")

    async def test_mark_failure_prevents_native_click(self):
        value = adapter()
        value._document = object()
        value.verify_title = AsyncMock()
        value.verify_options = AsyncMock()
        value.verify_body = AsyncMock()
        await self.page.goto(value.editor_url)
        await self.page.locator('#publish').evaluate('el=>el.onclick=()=>window.clicked=true')
        def fail():
            raise RuntimeError("cannot persist")
        with self.assertRaisesRegex(RuntimeError, "cannot persist"):
            await value.submit(self.page, fail)
        self.assertFalse(await self.page.evaluate('!!window.clicked'))

    async def test_native_publish_is_single_click_and_sync_authorization_is_declined(self):
        value = adapter()
        value._document = object()
        value.verify_title = AsyncMock()
        value.verify_options = AsyncMock()
        value.verify_body = AsyncMock()
        await value.install_preparation_guard(self.page)
        await self.page.goto(value.editor_url)
        await self.page.evaluate('''data=>{window.clicks=0;window.agreed=false;
          document.querySelector('#publish').onclick=()=>{window.clicks++;
            const box=document.createElement('div');box.className='arco-modal';
            box.innerHTML='<div class="arco-modal-title">作品同步授权</div><input type="checkbox"><button id="agree">同意</button><button class="arco-modal-close-icon">关闭</button>';
            document.body.append(box);box.querySelector('#agree').onclick=()=>window.agreed=true;
            box.querySelector('.arco-modal-close-icon').onclick=()=>{box.remove();fetch('/motor/content_publish/publish_mp_article/v1',
              {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});};};}''', payload())
        boundary = []
        await value.submit(self.page, lambda: boundary.append('persisted'))
        self.assertEqual(boundary, ['persisted'])
        self.assertEqual(await self.page.evaluate('window.clicks'), 1)
        self.assertFalse(await self.page.evaluate('window.agreed'))
        self.assertEqual((await value.read_result(self.page))['status'], 'submitted')
        with self.assertRaises(PreparationError):
            await value.submit(self.page, lambda: boundary.append('again'))
        self.assertEqual(await self.page.evaluate('window.clicks'), 1)

    async def test_old_draft_is_not_overwritten(self):
        value = adapter()
        value._read_native = AsyncMock(return_value=native(text="旧稿", title="旧稿标题"))
        with self.assertRaisesRegex(PreparationError, "旧稿"):
            await value.open_editor(self.page)
        self.assertEqual(await self.page.locator(value.title_selector).input_value(), "")

    async def test_serialized_body_must_preserve_text_format_images_and_order(self):
        value = adapter()
        await self.page.goto(value.editor_url)
        document = PreparedDocument("", "<p><strong>前</strong>OMNIPOSTIMAGE0000END后</p>", "前后",
                                    [Path("local.png")], ["OMNIPOSTIMAGE0000END"], [], [IMAGE])
        correct = '<p><strong>前</strong></p><img src="' + IMAGE + '"><p>后</p>'
        await value._check_serialized(self.page, correct, document)
        for wrong in (correct.replace("前", "漏字"), correct.replace("strong", "span"),
                      '<p><strong>前</strong>后</p><img src="' + IMAGE + '">',
                      correct.replace(IMAGE, HORIZONTAL["url"])):
            with self.assertRaises(PreparationError):
                await value._check_serialized(self.page, wrong, document)

    async def test_cover_local_preview_requires_committed_bound_done_object(self):
        value = adapter()
        await self.page.goto(value.editor_url)
        await self.page.evaluate("""({image,png})=>{const img=document.querySelector('#preview');img.src='data:image/png;base64,'+png;
          const host={stateNode:img,memoizedProps:{},return:null};
          const component={memoizedProps:{image},child:host};host.return=component;
          const root={stateNode:{},child:component};root.stateNode.current=root;component.return=root;
          img.__reactFiber$fixture=host;}""", {"image": HORIZONTAL, "png": base64.b64encode(PNG).decode()})
        await self.page.locator('#preview').evaluate('img=>img.decode()')
        await value._verify_cover_image(self.page, self.page.locator('#cover'), HORIZONTAL)
        await self.page.locator('#preview').evaluate("img=>img.src='data:image/png;base64,broken'")
        with self.assertRaisesRegex(PreparationError, "绑定"):
            await value._verify_cover_image(self.page, self.page.locator('#cover'), HORIZONTAL)
        await self.page.locator('#preview').evaluate("(img,png)=>{img.src='data:image/png;base64,'+png;return img.decode()}",
                                                 base64.b64encode(PNG).decode())
        await self.page.evaluate("""()=>{const host=document.querySelector('#preview').__reactFiber$fixture;
          const old=host.return;const current={memoizedProps:{image:{...old.memoizedProps.image,status:2}},child:host,return:old.return};
          old.return.child=current;host.return=current;}""")
        with self.assertRaisesRegex(PreparationError, "绑定"):
            await value._verify_cover_image(self.page, self.page.locator('#cover'), HORIZONTAL)

    async def test_cover_field_includes_official_preview_text_but_is_still_unique(self):
        value = adapter()
        await self.page.goto(value.editor_url)
        await self.page.locator('.form-cell__title').evaluate("el=>el.innerHTML='横版封面<span>预览</span>'")
        self.assertEqual(await (await value._cover_field(self.page)).get_attribute('id'), 'cover')
        await self.page.locator('.form-cell__title').evaluate("el=>el.innerHTML='横版封面<span>其他功能</span>'")
        with self.assertRaises(PreparationError):
            await value._cover_field(self.page)

    async def test_native_pending_body_image_cannot_pass(self):
        value = adapter()
        value._read_native = AsyncMock(return_value=native(title=TITLE, images=[{
            "url": IMAGE, "uri": "uri", "naturalWidth": 800, "naturalHeight": 600, "motor_need_upload": True}]))
        document = PreparedDocument("", "OMNIPOSTIMAGE0000END", "", [Path("image")],
                                    ["OMNIPOSTIMAGE0000END"], [], [IMAGE])
        with self.assertRaisesRegex(PreparationError, "持久上传"):
            await value.verify_body(self.page, None, document)

    async def test_visible_image_is_counted_once_beside_hidden_syl_template(self):
        value = adapter()
        await self.page.goto(value.editor_url)
        data = {"url": IMAGE, "uri": "tos/body", "motor_need_upload": False,
                "naturalWidth": 800, "naturalHeight": 600}
        value._read_native = AsyncMock(return_value=native(title=TITLE, images=[data]))
        editor = self.page.locator(value.editor_selector)
        await editor.evaluate('''(el,url)=>{el.innerHTML='<p>之前</p><div __syl_tag="true">'+
          '<templ style="display:none"><div class="pgc-img"><img src="'+url+'"></div></templ>'+
          '<mask><div class="pgc-image"><div class="pgc-img-wrapper"><img src="'+url+'">'+
          '<div class="editor-image-menu">编辑</div></div><div class="pgc-img-caption-wrapper">'+
          '<input class="pgc-img-caption-ipt"><span class="pgc-img-caption-tip">0/50</span>'+
          '<p class="pgc-img-caption"></p></div></div></mask></div><p>之后</p>'; }''', IMAGE)
        await editor.locator('mask img').evaluate('img=>img.decode()')
        state = await value.read_document_state(editor)
        self.assertEqual(state['text'], '之前之后')
        self.assertEqual(state['sequence'], '之前OMNIPOSTIMAGE0000END之后')
        self.assertEqual(state['images'], [{'src': IMAGE, 'ready': True}])
        # 图注属于真实内容，不能以“排除编辑控件”为由丢掉。
        await editor.locator('mask .pgc-img-caption').evaluate("el=>el.textContent='新增图注'")
        self.assertIn('新增图注', (await value.read_document_state(editor))['text'])

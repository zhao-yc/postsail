"""车家号原生文章的受控 Chromium 回归；不连接真实平台或使用账号。"""
import copy
import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from PIL import Image

from utils.articles.adapter import _verify_final_body
from utils.articles.browser import (
    PreparationError, PreparedDocument, insert_body_images, inspect_text,
    launch_article_browser, paste_rich_html,
)
from utils.articles.chejiahao import ChejiahaoArticleAdapter


def image_bytes(size=(560, 420)):
    output = io.BytesIO()
    Image.new("RGB", size, "steelblue").save(output, "PNG")
    return output.getvalue()


class ChejiahaoInputTests(unittest.IsolatedAsyncioTestCase):
    async def test_title_uses_official_weighted_length_without_truncation(self):
        for title in ("abcdef", "五个中文哦", "车" * 31):
            with self.subTest(title=title), self.assertRaisesRegex(PreparationError, "6.*30"):
                await ChejiahaoArticleAdapter({"title": title}, None).fill_title(MagicMock())

    async def test_weighted_title_accepts_english_and_mixed_language_boundaries(self):
        for title in ("a" * 12, "a" * 60, "汽车" + "a" * 8):
            ChejiahaoArticleAdapter({"title": title}, None)._validate_inputs()
        for title in ("a" * 11, "a" * 61):
            with self.assertRaises(PreparationError):
                ChejiahaoArticleAdapter({"title": title}, None)._validate_inputs()

    async def test_unknown_options_and_plain_tags_are_rejected(self):
        for extra in ({"options": {"statement": "原创"}}, {"tags": ["汽车"]},
                      {"options": {"first_publish": "true"}}):
            adapter = ChejiahaoArticleAdapter({"title": "车家号文章测试标题", **extra}, None)
            with self.subTest(extra=extra), self.assertRaises(PreparationError):
                adapter._validate_inputs()

    async def test_legacy_empty_options_are_ignored(self):
        ChejiahaoArticleAdapter({"title": "车家号文章测试标题", "options": {
            "ai_generated": False, "statement": ""}}, None)._validate_inputs()

    async def test_both_cover_assets_required_before_page_is_touched(self):
        with TemporaryDirectory() as directory:
            cover = Path(directory) / "cover.png"
            cover.write_bytes(image_bytes())
            adapter = ChejiahaoArticleAdapter({"title": "车家号文章测试标题", "options": {
                "vertical_cover_asset_id": "uploaded-id-only"}}, cover)
            with self.assertRaisesRegex(PreparationError, "竖版封面"):
                await adapter.apply_options(MagicMock(), MagicMock())

    async def test_cover_dimensions_ratio_and_file_format_are_validated(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "cover.png"
            adapter = ChejiahaoArticleAdapter({"title": "车家号文章测试标题"}, path)
            for size in ((559, 420), (560, 421), (420, 560)):
                path.write_bytes(image_bytes(size))
                with self.subTest(size=size), self.assertRaisesRegex(PreparationError, "不自动裁剪"):
                    adapter._cover_file("horizontal")
            path.write_bytes(image_bytes())
            self.assertEqual(adapter._cover_file("horizontal"), path)


@unittest.skipUnless(os.environ.get("OMNIPOST_BROWSER_TESTS") == "1", "受控浏览器用例需显式启用")
class ChejiahaoBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        import conf
        self.directory = TemporaryDirectory()
        self.cover = Path(self.directory.name) / "cover.png"
        self.vertical = Path(self.directory.name) / "vertical.png"
        self.cover.write_bytes(image_bytes())
        self.vertical.write_bytes(image_bytes((600, 800)))
        self.runtime = await async_playwright().start()
        self.browser = await launch_article_browser(self.runtime, True, getattr(conf, "LOCAL_CHROME_PATH", ""))
        self.context = await self.browser.new_context(viewport={"width": 1200, "height": 1000})
        self.page = await self.context.new_page()
        self.render_page = await self.context.new_page()
        await self.render_page.set_content("<html><body></body></html>")

    async def asyncTearDown(self):
        await self.context.close()
        await self.browser.close()
        await self.runtime.stop()
        self.directory.cleanup()

    async def fixture(self, *, options=None, mode="publish", old_body="", old_title="", duplicate=False,
                      destination=None, receipt="提交成功", label="竖版封面"):
        self.adapter = ChejiahaoArticleAdapter({"title": "车家号文章测试标题", "mode": mode,
            "options": {"vertical_cover_asset_id": "fixture-vertical", "agree_upload_terms": True, **(options or {})}}, self.cover)
        self.adapter.option_assets = {"vertical_cover_asset_id": self.vertical}
        html = r'''<!doctype html><meta charset="utf-8"><style>
        #editor{min-height:140px}.cover{min-height:80px}.cover img{width:80px}
        iframe{height:250px;width:600px}.slot,span{cursor:pointer}.editor-image img{width:80px}
        .editor-image-magnifier{display:none}[role=dialog]{position:fixed;top:20px;left:20px;background:white;z-index:20}
        </style><input placeholder="请输入文章标题（6-30个汉字）" maxlength="30" value="OLDTITLE">
        <div class="editor-inner" data-type="article"><div id="editor" class="editor-input" contenteditable="true" data-lexical-editor="true">OLDBODY</div></div>
        <label>原创<input id="isOriginal" type="checkbox" checked></label>
        <label>首发<input id="isFirst" type="checkbox" checked></label>
        <label>我已阅读并已同意遵守<input id="statementCheck" type="checkbox"></label>
        <span id="unrelated" onclick="window.wrong=true">编辑</span>
        <div id="imageUrls" class="cover UpImageContainer_uploadBox__g2vUQ"><div class="UpImageContainer_leftPart__dO6iI slot" onclick="openCover('imageUrls')">上传</div></div>
        <div id="imgVerticals" class="cover UpImageVericalContainer_uploadBox__ksBoL"><div class="UpImageVericalContainer_leftPart__r8K4Z slot" onclick="openCover('imgVerticals')">上传</div></div>
        <div class="Footer_fixContainer__NYwPE Footer_fixContainerLong__klrNM"><button onclick="publish()">发布</button></div>
        <script>
        window.events=[];window.wrong=false;window.images=0;
        const editor=document.getElementById('editor');
        function nativeNode(node){
          if(node.nodeType===3)return {type:'text',text:node.textContent,format:0};
          const tag=node.tagName.toLowerCase();
          if(node.matches('.editor-image'))return {type:'image',src:node.dataset.src,width:560,height:420,caption:''};
          if(tag==='img')return {type:'image',src:node.src,width:560,height:420,caption:''};
          const children=[...node.childNodes].map(nativeNode),types={p:'paragraph',h2:'heading',ul:'list',ol:'list',li:'listitem',blockquote:'quote',br:'linebreak'};
          if(['strong','b','em','i','u','s'].includes(tag))return {type:'text',text:node.textContent,format:{strong:1,b:1,em:2,i:2,u:8,s:4}[tag]};
          return {type:types[tag]||'paragraph',children,tag,listType:tag==='ol'?'number':'bullet'};
        }
        editor.__lexicalEditor={getEditorState:()=>({toJSON:()=>({root:{type:'root',children:[...editor.childNodes].map(nativeNode)}})})};
        function openCover(which){window.currentCover=which;const dialog=document.createElement('section');
          dialog.setAttribute('role','dialog');dialog.setAttribute('aria-label','展示封面图');
          dialog.innerHTML='<button role="tab">上传图片</button><input type="file" accept=".jpg,.jpeg,.png"><button onclick="chooseCover()">确定</button>';
          dialog.querySelector('input').onchange=()=>{const img=document.createElement('img');img.src='https://n1.autoimg.cn/upload-'+which+'.png';dialog.append(img)};
          document.body.append(dialog);}
        function chooseCover(){document.querySelector('[role=dialog]').remove();const frame=document.createElement('iframe');
          const image=document.createElement('img');image.src='https://n1.autoimg.cn/'+window.currentCover+'.png';
          document.getElementById(window.currentCover).append(image);
          frame.name='mofangIframe';frame.src='https://posterdesign.autohome.com.cn/';document.body.append(frame);}
        function finishCover(){document.querySelector('iframe').remove();}window.addEventListener('message',event=>{if(event.origin==='https://posterdesign.autohome.com.cn'&&event.data==='close')finishCover()});
        async function publish(){window.events.push('click');await fetch('/openapi/content-api/gc/article/publish?publishType=1',{
          method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...{publishType:1,title:document.querySelector('input').value,source:'pc',role:2,coverType:0,isOriginal:Number(document.getElementById('isOriginal').checked),isFirst:Number(document.getElementById('isFirst').checked),imageUrls:['https://n1.autoimg.cn/imageUrls.png'],imgVerticalUrl:'https://n1.autoimg.cn/imgVerticals.png',contentJson:JSON.stringify(editor.__lexicalEditor.getEditorState().toJSON()),content:(()=>{const node=editor.cloneNode(true);node.querySelectorAll('.editor-image').forEach(box=>box.replaceWith(box.querySelector('img').cloneNode()));return node.innerHTML})()},...(window.payloadOverride||{})})});}
        editor.addEventListener('paste',event=>{
          if(event.clipboardData.files.length){event.preventDefault();const url='https://n1.autoimg.cn/body-'+(++window.images)+'.png';
            document.execCommand('insertHTML',false,'<div class="editor-image" contenteditable="false" data-src="'+url+'"><img alt="'+url+'" src="'+url+'"><div class="editor-image-magnifier"><img src="'+url+'"></div><input placeholder="请输入图片描述"><span>0/50</span></div>');}});
        </script>'''
        html = html.replace("OLDTITLE", old_title).replace("OLDBODY", old_body)
        if label != "竖版封面":
            html = html.replace('id="imgVerticals"', 'id="unknownCover"')
        if duplicate:
            html += '<input placeholder="请输入文章标题(6-30个汉字)">'
        frame_html = '''<!doctype html><meta charset="utf-8"><div class="btn-cancel" onclick="parent.postMessage('close','*')">取消</div>'''

        async def serve(route):
            url = route.request.url
            if "/gc/article/publish" in url:
                await route.fulfill(json={"returncode": 0, "result": {"id": 812345} if receipt == "提交成功" else {"draftId": 991}})
            elif url.endswith(".png"):
                await route.fulfill(body=image_bytes(), content_type="image/png")
            elif url.startswith("https://posterdesign.autohome.com.cn/"):
                await route.fulfill(body=frame_html, content_type="text/html; charset=utf-8")
            elif destination and url == self.adapter.editor_url:
                await route.fulfill(body='<script>location.replace("' + destination + '")</script>', content_type="text/html")
            else:
                await route.fulfill(body=html, content_type="text/html; charset=utf-8")
        await self.context.route("**/*", serve)
        self.editor = await self.adapter.open_editor(self.page)

    async def prepare(self, with_images=False):
        await self.adapter.fill_title(self.page)
        await self.adapter.verify_title(self.page)
        html = '<h2>汽车文章小标题</h2><p>第一段<strong>加粗文字</strong></p>'
        if with_images:
            html += '<p>OMNIPOSTIMAGE0000END</p><p>中间段落</p><p>OMNIPOSTIMAGE0001END</p>'
        html += '<p>末尾完整文字参考来源 https://example.com/reference</p>'
        markers = [f"OMNIPOSTIMAGE{i:04d}END" for i in range(2)] if with_images else []
        expected = inspect_text(html)
        for marker in markers:
            expected = expected.replace(marker, "")
        self.document = PreparedDocument(html, html, expected,
            [self.cover, self.vertical] if with_images else [], markers, [])
        await self.adapter.paste_document(self.page, self.editor, self.document)
        if with_images:
            await self.adapter.insert_body_images(self.page, self.editor, self.render_page, self.document)
        await self.adapter.apply_options(self.page, self.editor)
        await self.adapter.verify_options(self.page, self.editor)
        await _verify_final_body(self.editor, self.document, "chejiahao", document_reader=self.adapter.read_document_state, rich_verifier=self.adapter.verify_rich_document)
        await self.adapter.verify_body(self.page, self.editor, self.document)

    async def submit(self):
        async def mark():
            await self.page.evaluate("window.events.push('mark')")
        await self.adapter.submit(self.page, mark)

    async def test_full_article_body_images_two_covers_options_and_single_submit(self):
        await self.fixture(options={"original": True, "first_publish": False})
        await self.prepare(with_images=True)
        self.assertEqual(len(self.document.uploaded_urls), 2)
        self.assertFalse(await self.page.evaluate("window.wrong"))
        self.assertTrue(await self.page.locator("#isOriginal").is_checked())
        self.assertFalse(await self.page.locator("#isFirst").is_checked())
        await self.submit()
        self.assertEqual(await self.page.evaluate("window.events"), ["mark", "click"])
        await self.page.wait_for_timeout(100)
        self.assertEqual((await self.adapter.read_result(self.page))["status"], "submitted")
        with self.assertRaisesRegex(PreparationError, "已经尝试"):
            await self.submit()
        self.assertEqual(await self.page.evaluate("window.events"), ["mark", "click"])

    async def test_omitted_declarations_do_not_claim_original_or_first(self):
        await self.fixture()
        await self.prepare()
        self.assertFalse(await self.page.locator("#isOriginal").is_checked())
        self.assertFalse(await self.page.locator("#isFirst").is_checked())

    async def test_hidden_native_checkboxes_use_their_visible_associated_labels(self):
        await self.fixture()
        await self.page.add_style_tag(content="#isOriginal,#isFirst{display:none}")
        await self.prepare()
        self.assertFalse(await self.page.locator("#isOriginal").is_checked())
        self.assertFalse(await self.page.locator("#isFirst").is_checked())

    async def test_old_body_title_and_media_are_preserved(self):
        for extra in ({"old_body": "用户原稿"}, {"old_title": "用户旧标题"},
                      {"old_body": '<img src="https://n1.autoimg.cn/old.png">'}):
            with self.subTest(extra=extra):
                await self.context.unroute("**/*")
                with self.assertRaisesRegex(PreparationError, "阻止覆盖"):
                    await self.fixture(**extra)

    async def test_duplicate_title_control_is_not_arbitrarily_chosen(self):
        with self.assertRaisesRegex(PreparationError, "唯一"):
            await self.fixture(duplicate=True)

    async def test_route_boundary_rejects_login_old_id_and_other_host(self):
        for destination in ("https://chejiahao.autohome.com.cn/login", self.adapter_url() + "?id=123",
                            "https://evil.example/article/post.html"):
            with self.subTest(destination=destination):
                await self.context.unroute("**/*")
                with self.assertRaisesRegex(PreparationError, "入口|登录"):
                    await self.fixture(destination=destination)

    @staticmethod
    def adapter_url():
        return ChejiahaoArticleAdapter.editor_url

    async def test_missing_vertical_semantics_never_uses_other_edit_button(self):
        with self.assertRaisesRegex(PreparationError, "封面区域"):
            await self.fixture(label="不明区域")
        self.assertFalse(await self.page.evaluate("window.wrong"))
        self.assertEqual(await self.page.evaluate("window.events"), [])

    async def test_cover_replaced_after_preparation_blocks_submission(self):
        await self.fixture()
        await self.prepare()
        await self.page.locator("#imgVerticals img").evaluate("img=>img.src='https://n1.autoimg.cn/different.png'")
        with self.assertRaisesRegex(PreparationError, "封面"):
            await self.submit()
        self.assertEqual(await self.page.evaluate("window.events"), [])

    async def test_body_mutation_and_image_reordering_block_submission(self):
        await self.fixture()
        await self.prepare(with_images=True)
        await self.editor.evaluate("el=>el.prepend(el.querySelector('.editor-image:last-of-type'))")
        with self.assertRaisesRegex(PreparationError, "图片|正文"):
            await self.submit()
        self.assertEqual(await self.page.evaluate("window.events"), [])

    async def test_marker_persistence_failure_never_clicks(self):
        await self.fixture()
        await self.prepare()
        def broken():
            raise RuntimeError("database unavailable")
        with self.assertRaisesRegex(RuntimeError, "database"):
            await self.adapter.submit(self.page, broken)
        self.assertEqual(await self.page.evaluate("window.events"), [])
        self.assertFalse(self.adapter._submit_started)

    async def test_preview_blocks_native_button_publish_and_adapter_submit(self):
        await self.fixture(mode="preview")
        await self.prepare()
        await self.page.locator(self.adapter.publish_selector).dispatch_event("click")
        with self.assertRaisesRegex(PreparationError, "预览"):
            await self.submit()
        self.assertEqual(await self.page.evaluate("window.events"), [])

    async def test_ambiguous_result_and_body_success_words_remain_unknown(self):
        await self.fixture(receipt="处理完成")
        await self.prepare()
        await self.submit()
        self.assertEqual((await self.adapter.read_result(self.page))["status"], "unknown")
        await self.editor.fill("发布成功")
        self.assertEqual((await self.adapter.read_result(self.page))["status"], "unknown")

    async def test_result_before_submission_cannot_report_success(self):
        await self.fixture()
        await self.page.evaluate("publish().catch(()=>{})")
        self.assertEqual((await self.adapter.read_result(self.page))["status"], "unknown")

    async def test_old_success_notice_is_not_a_receipt_for_this_submit(self):
        await self.fixture(receipt="处理完成")
        await self.prepare()
        await self.page.evaluate("""() => {const old=document.createElement('div');
            old.setAttribute('role','alert');old.textContent='提交成功';document.body.append(old)}""")
        await self.submit()
        self.assertEqual((await self.adapter.read_result(self.page))["status"], "unknown")

    async def test_formal_payload_is_bound_to_native_body_covers_and_options(self):
        await self.fixture()
        await self.prepare(with_images=True)
        await self.submit()
        await self.page.wait_for_timeout(100)
        data = self.adapter._formal_request.post_data_json
        self.assertTrue(self.adapter._matches_payload(data))
        cases = [{"title": "其他标题"}, {"content": "其他正文"}, {"contentJson": "{}"},
                 {"draftId": 123}, {"id": 123}, {"publishType": 0}, {"timerStatus": 1},
                 {"imageUrls": ["https://n1.autoimg.cn/old.png"]},
                 {"imgVerticalUrl": "https://n1.autoimg.cn/old.png"},
                 {"isOriginal": 1}, {"isFirst": 1}, {"isNews": 1}]
        for update in cases:
            with self.subTest(update=update):
                try:
                    result = self.adapter._matches_payload({**copy.deepcopy(data), **update})
                except (ValueError, TypeError):
                    result = False
                self.assertFalse(result)

    async def test_native_second_request_and_autosave_are_blocked(self):
        await self.fixture()
        await self.prepare()
        blocked = await self.page.evaluate("fetch('/openapi/content-api/gc/article/publish?publishType=0', {method:'POST',body:'{}'}).then(()=>false,()=>true)")
        self.assertTrue(blocked)
        await self.submit()
        await self.page.wait_for_timeout(100)
        first = self.adapter._formal_request
        self.assertTrue(await self.page.evaluate("publish().then(()=>false,()=>true)"))
        self.assertIs(self.adapter._formal_request, first)
        self.assertEqual((await self.adapter.read_result(self.page))["status"], "submitted")

    async def test_preview_cannot_send_formal_request_directly(self):
        await self.fixture(mode="preview")
        await self.prepare()
        self.assertTrue(await self.page.evaluate("publish().then(()=>false,()=>true)"))
        self.assertIsNone(self.adapter._formal_request)

    async def test_upload_agreement_needs_explicit_option(self):
        await self.fixture(options={"agree_upload_terms": False})
        with self.assertRaisesRegex(PreparationError, "明确同意"):
            await self.prepare()
        self.assertFalse(await self.page.locator("#statementCheck").is_checked())

    async def test_native_state_and_visible_text_must_agree(self):
        await self.fixture()
        await self.prepare()
        await self.editor.evaluate("el=>{const state=el.__lexicalEditor.getEditorState().toJSON();el.__lexicalEditor={getEditorState:()=>({toJSON:()=>state})};el.append('多余正文')}")
        with self.assertRaisesRegex(PreparationError, "原生文章状态"):
            await self.submit()

    async def test_ordinary_links_are_not_silently_dropped(self):
        await self.fixture()
        html = '<p>正文需要保留<a href="https://example.com">这个链接</a></p>'
        document = PreparedDocument(html, html, inspect_text(html), [], [], [])
        with self.assertRaisesRegex(PreparationError, "转为文字"):
            await self.adapter.paste_document(self.page, self.editor, document)

    async def test_native_body_weighted_length_is_enforced(self):
        await self.fixture()
        for text, valid in (("a" * 19, False), ("a" * 20, True), ("正" * 9, False), ("正" * 10, True)):
            with self.subTest(text=text):
                await self.editor.fill(text)
                document = PreparedDocument(text, text, text, [], [], [])
                if valid:
                    await self.adapter.verify_body(self.page, self.editor, document)
                else:
                    with self.assertRaisesRegex(PreparationError, "10–100000"):
                        await self.adapter.verify_body(self.page, self.editor, document)

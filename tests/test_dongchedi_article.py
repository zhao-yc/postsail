"""懂车号受控验证；所有网页和图片均被本地 fixture 截获，不访问真实账号。"""
import base64
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from utils.articles.browser import PreparationError, install_preview_guard
from utils.articles.dongchedi import DongchediArticleAdapter


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jr1sAAAAASUVORK5CYII=')
URL = DongchediArticleAdapter.editor_url
FIXTURE = '''<!doctype html><html><body>
<textarea placeholder="请输入标题" maxlength="30"></textarea>
<div class="article-content" contenteditable="true"><p>原始正文</p></div>
<div class="cover-area"><div class="fake-upload-trigger" onclick="showLocal()">选择封面</div></div>
<button id="draft" onclick="events.push('draft')">保存草稿</button>
<button class="publish-btn" onclick="events.push('entry');showPublish()">预览并发布</button>
<script>
window.events=[];
window.saveCover=()=>{
 const img=document.createElement('img');img.src='https://p3-dcd.byteimg.com/new-cover.png';
 document.querySelector('.cover-area').appendChild(img);
};
window.onCover=()=>saveCover();
window.showLocal=()=>{
 const li=document.createElement('li');li.innerText='本地上传';
 document.body.appendChild(li);li.onclick=()=>{
  li.remove();const region=document.createElement('div');region.className='xigua-upload-poster-trigger';
  region.innerHTML='<input type="file" accept="image/png">';document.body.appendChild(region);
  region.querySelector('input').onchange=()=>onCover();
 };
};
window.showPublish=()=>{
 const dialog=document.createElement('div');dialog.setAttribute('role','dialog');
 dialog.innerHTML='<h2>文章发布确认</h2><button id="confirm">确认发布</button><button>取消</button>';
 document.body.appendChild(dialog);document.querySelector('#confirm').onclick=()=>{
  events.push('publish');dialog.remove();const receipt=document.createElement('div');
  receipt.setAttribute('role','alert');receipt.innerText='发布成功';document.body.appendChild(receipt);
 };
};
</script></body></html>'''


class DongchediBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, **changes):
        return DongchediArticleAdapter({'platform': 'dongchedi', 'title': '汽车测试文章',
                                        'mode': 'publish', **changes}, None)

    async def test_preview_submit_has_no_browser_or_callback_side_effects(self):
        page, callback = MagicMock(), MagicMock()
        with self.assertRaisesRegex(PreparationError, '预览模式禁止'):
            await self.adapter(mode='preview').submit(page, callback)
        callback.assert_not_called()
        self.assertEqual(page.mock_calls, [])

    async def test_unknown_declaration_and_tags_rejected_before_browser_actions(self):
        for changes in ({'options': {'statement': '包含AI创作'}}, {'tags': ['汽车']},
                        {'options': {'summary': '不能静默丢弃的摘要'}}):
            page = MagicMock()
            with self.subTest(changes=changes), self.assertRaises(PreparationError):
                await self.adapter(**changes).open_editor(page)
            self.assertEqual(page.mock_calls, [])

    async def test_cover_is_required_before_browser_upload(self):
        page = MagicMock()
        with self.assertRaisesRegex(PreparationError, '需要封面'):
            await self.adapter().apply_options(page, None)
        self.assertEqual(page.mock_calls, [])

    async def test_click_exception_never_retries_or_changes_button(self):
        adapter = self.adapter()
        adapter._check_editor_location = AsyncMock()
        button = MagicMock()
        button.scroll_into_view_if_needed = AsyncMock()
        button.click = AsyncMock(side_effect=RuntimeError('点击后页面关闭'))
        callback = MagicMock()
        with patch('utils.articles.dongchedi._unique', new=AsyncMock(return_value=button)):
            with self.assertRaisesRegex(RuntimeError, '页面关闭'):
                await adapter.submit(MagicMock(), callback)
            with self.assertRaisesRegex(PreparationError, '已经尝试'):
                await adapter.submit(MagicMock(), callback)
        callback.assert_called_once()
        button.click.assert_awaited_once()

    async def test_no_receipt_is_accepted_before_boundary(self):
        page = MagicMock()
        self.assertEqual((await self.adapter().read_result(page))['status'], 'unknown')
        self.assertEqual(page.mock_calls, [])


@unittest.skipUnless(os.environ.get('OMNIPOST_BROWSER_TESTS') == '1', '本地浏览器用例需显式启用')
class DongchediBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        import conf
        self.directory = TemporaryDirectory()
        self.cover = Path(self.directory.name) / 'cover.png'
        self.cover.write_bytes(PNG)
        self.runtime = await async_playwright().start()
        options = {'headless': True}
        executable = getattr(conf, 'LOCAL_CHROME_PATH', '')
        if executable:
            options['executable_path'] = executable
        self.browser = await self.runtime.chromium.launch(**options)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        self.fixture = FIXTURE

        async def serve(route):
            if route.request.url.endswith('.png'):
                await route.fulfill(body=PNG, content_type='image/png')
            else:
                await route.fulfill(body=self.fixture, content_type='text/html; charset=utf-8')
        await self.context.route('**/*', serve)
        await self.page.goto(URL)

    async def asyncTearDown(self):
        await self.context.close()
        await self.browser.close()
        await self.runtime.stop()
        self.directory.cleanup()

    def adapter(self, **changes):
        return DongchediArticleAdapter({'platform': 'dongchedi', 'title': '汽车测试文章',
                                        'mode': 'publish', **changes}, self.cover)

    async def boundary(self):
        await self.page.evaluate("events.push('boundary')")

    async def test_direct_editor_title_and_real_cover_are_prepared_without_submit(self):
        adapter = self.adapter()
        editor = await adapter.open_editor(self.page)
        self.assertEqual(await editor.inner_text(), '原始正文')
        await adapter.fill_title(self.page)
        await adapter.verify_title(self.page)
        await editor.fill('完整汽车正文')
        await adapter.apply_options(self.page, editor)
        await adapter.verify_options(self.page, editor)
        self.assertEqual(await self.page.locator('textarea').input_value(), '汽车测试文章')
        self.assertEqual(await editor.inner_text(), '完整汽车正文')
        self.assertEqual(await self.page.evaluate('events'), [])
        self.assertFalse(adapter._submit_started)

    async def test_ueditor_iframe_body_is_used_when_no_direct_editor_exists(self):
        self.fixture = FIXTURE.replace('<div class="article-content" contenteditable="true"><p>原始正文</p></div>',
            '<iframe id="ueditor_0" srcdoc="&lt;body contenteditable=\'true\'&gt;框架正文&lt;/body&gt;"></iframe>')
        editor = await self.adapter().open_editor(self.page)
        self.assertEqual(await editor.inner_text(), '框架正文')
        await editor.fill('框架内完整正文')
        self.assertEqual(await editor.inner_text(), '框架内完整正文')

    async def test_login_or_draft_redirect_is_rejected_before_editing(self):
        for target in ('https://mp.dcdapp.com/login', URL + '?article_id=123'):
            self.fixture = FIXTURE + '<script>history.replaceState(null,"",' + json.dumps(target) + ')</script>'
            with self.subTest(target=target), self.assertRaises(PreparationError):
                await self.adapter().open_editor(self.page)
            self.assertEqual(await self.page.locator('textarea').input_value(), '')

    async def test_multiple_title_or_editor_fields_are_not_guessed(self):
        for extra in ('<textarea placeholder="文章摘要"></textarea>', '<div contenteditable="true">另一个编辑器</div>'):
            self.fixture = FIXTURE + extra
            with self.subTest(extra=extra), self.assertRaisesRegex(PreparationError, '唯一'):
                await self.adapter().open_editor(self.page)

    async def test_page_declared_title_limit_does_not_truncate(self):
        await self.page.locator('textarea').evaluate("el=>el.maxLength=3")
        with self.assertRaisesRegex(PreparationError, '最多 3 字'):
            await self.adapter().fill_title(self.page)
        self.assertEqual(await self.page.locator('textarea').input_value(), '')

    async def test_cover_crop_confirmation_is_scoped_and_single(self):
        await self.page.evaluate('''() => { window.onCover=()=>{
          const dialog=document.createElement('div');dialog.setAttribute('role','dialog');
          dialog.innerHTML='<h2>裁剪封面</h2><div class="clip-btn-content">应用裁剪</div><button>确定</button>';
          document.body.appendChild(dialog);
          dialog.querySelector('.clip-btn-content').onclick=()=>events.push('clip');
          dialog.querySelector('button').onclick=()=>{
            events.push('cover');dialog.remove();saveCover();
          };
        }; document.body.insertAdjacentHTML('beforeend','<button onclick="events.push(\\'wrong\\')">确定</button>'); }''')
        adapter = self.adapter()
        await adapter.apply_options(self.page, None)
        await adapter.verify_options(self.page, None)
        self.assertEqual(await self.page.evaluate('events'), ['clip', 'cover'])

    async def test_cover_readback_rejects_body_images_blobs_and_foreign_hosts(self):
        adapter = self.adapter()
        await self.page.locator('.article-content').evaluate(
            "el=>el.insertAdjacentHTML('beforeend','<img src=\"https://p3-dcd.byteimg.com/body.png\">')")
        with self.assertRaisesRegex(PreparationError, '新封面'):
            await adapter.verify_options(self.page, None)
        for source in ('data:image/png;base64,' + base64.b64encode(PNG).decode(),
                       'https://p3-dcd.byteimg.com.attacker.example/cover.png'):
            await self.page.locator('.cover-area').evaluate('''(el,src)=>{
                el.querySelectorAll('img').forEach(img=>img.remove());const img=document.createElement('img');
                img.src=src;el.appendChild(img);
            }''', source)
            with self.subTest(source=source[:40]), self.assertRaisesRegex(PreparationError, '新封面'):
                await adapter.verify_options(self.page, None)

    async def test_boundary_precedes_entry_and_final_confirmation_once(self):
        adapter = self.adapter()
        await adapter.submit(self.page, self.boundary)
        self.assertEqual(await self.page.evaluate('events'), ['boundary', 'entry', 'publish'])
        self.assertEqual((await adapter.read_result(self.page))['status'], 'submitted')
        with self.assertRaisesRegex(PreparationError, '已经尝试'):
            await adapter.submit(self.page, self.boundary)

    async def test_failed_boundary_or_ambiguous_button_prevents_click(self):
        async def fail():
            raise RuntimeError('写入失败')
        with self.assertRaisesRegex(RuntimeError, '写入失败'):
            await self.adapter().submit(self.page, fail)
        await self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<button class=publish-btn>预览并发布</button>')")
        with self.assertRaisesRegex(PreparationError, '唯一'):
            await self.adapter().submit(self.page, self.boundary)
        self.assertEqual(await self.page.evaluate('events'), [])

    async def test_preview_guard_blocks_preview_and_publish_entry(self):
        await install_preview_guard(self.page)
        await self.page.locator('.publish-btn').evaluate('el=>el.click()')
        self.assertEqual(await self.page.evaluate('events'), [])

    async def test_challenge_before_entry_prevents_callback_and_click(self):
        await self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<div role=dialog>请完成安全验证</div>')")
        with self.assertRaisesRegex(PreparationError, '安全验证'):
            await self.adapter().submit(self.page, self.boundary)
        self.assertEqual(await self.page.evaluate('events'), [])

    async def test_challenge_after_entry_never_clicks_final_confirmation(self):
        await self.page.evaluate('''() => {window.showPublish=()=>document.body.insertAdjacentHTML('beforeend',
            '<div role="dialog">请完成安全验证<button>确认发布</button></div>');}''')
        adapter = self.adapter()
        await adapter.submit(self.page, self.boundary)
        self.assertEqual(await self.page.evaluate('events'), ['boundary', 'entry'])
        self.assertEqual((await adapter.read_result(self.page))['status'], 'needs_action')

    async def test_draft_toast_body_text_and_management_url_are_not_receipts(self):
        adapter = self.adapter()
        adapter._submit_started = True
        await self.page.locator('.article-content').fill('发布成功')
        await self.page.evaluate('''() => {history.replaceState(null,'','/profile_v2/content/manage');
          document.body.insertAdjacentHTML('beforeend','<div role="alert">草稿保存成功</div>');}''')
        self.assertEqual((await adapter.read_result(self.page))['status'], 'unknown')
        await self.page.locator('[role=alert]').evaluate("el=>el.innerText='发布成功后可在列表中查看'")
        self.assertEqual((await adapter.read_result(self.page))['status'], 'unknown')

    async def test_foreign_page_feedback_cannot_claim_success(self):
        adapter = self.adapter()
        adapter._submit_started = True
        self.fixture = '<div role="alert">发布成功</div>'
        await self.page.goto('https://mp.dcdapp.com.attacker.example/result')
        self.assertEqual((await adapter.read_result(self.page))['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()

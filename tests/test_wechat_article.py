"""微信公众号受控页面验收：不登录、不访问真实平台、不执行真实发表。"""
import base64
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

from utils.articles.adapter import _verify_final_body
from utils.articles.browser import PreparationError, prepare_and_paste_document
from utils.articles.wechat import WechatArticleAdapter


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jr1sAAAAASUVORK5CYII=')
FIXTURE = '''<!doctype html><html><body>
    <textarea id="title" maxlength="64"></textarea>
    <input id="author" maxlength="8"><textarea id="js_description" maxlength="120"></textarea>
    <div class="rich_media_content"><div class="ProseMirror" contenteditable="true"><p><br></p></div></div>
    <div id="js_cover_area"><input type="file" accept="image/png"></div>
    <button id="js_submit" onclick="events.push('draft')">保存草稿</button>
    <button id="publish" onclick="events.push('entry');showConfirm()">发表</button>
    <script>
      window.events=[];
      document.querySelector('input[type=file]').onchange=()=>{
        const img=document.createElement('img');img.src='https://mmbiz.qpic.cn/new-cover.png';
        document.querySelector('#js_cover_area').appendChild(img);
      };
      window.showConfirm=()=>{
        const dialog=document.createElement('div');dialog.setAttribute('role','dialog');
        dialog.innerHTML='<p>确认发表此文章</p><button id="confirm">确认发表</button><button>取消</button>';
        document.body.appendChild(dialog);
        document.querySelector('#confirm').onclick=()=>{
          events.push('publish');dialog.remove();
          const receipt=document.createElement('div');receipt.setAttribute('role','alert');
          receipt.innerText='发表成功';document.body.appendChild(receipt);
        };
      };
    </script></body></html>'''


class WechatArticleBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, **values):
        return WechatArticleAdapter(dict(platform='wechat', title='测试文章', **values), None)

    async def test_preview_submit_rejected_without_browser_or_callback(self):
        page, callback = MagicMock(), MagicMock()
        with self.assertRaisesRegex(PreparationError, '预览模式禁止'):
            await self.adapter(mode='preview').submit(page, callback)
        callback.assert_not_called()
        self.assertEqual(page.mock_calls, [])

    async def test_missing_cover_rejected_before_browser_actions(self):
        page = MagicMock()
        with self.assertRaisesRegex(PreparationError, '需要封面'):
            await self.adapter().apply_options(page, MagicMock())
        self.assertEqual(page.mock_calls, [])

    async def test_unsupported_options_or_tags_rejected_before_browser_actions(self):
        for values in ({'options': {'category': '科技'}}, {'tags': ['科技']}):
            page = MagicMock()
            with self.assertRaises(PreparationError):
                await self.adapter(**values).apply_options(page, MagicMock())
            self.assertEqual(page.mock_calls, [])

    async def test_editor_navigation_errors_do_not_expose_session_token(self):
        page = MagicMock()
        page.goto = AsyncMock(side_effect=[None, RuntimeError('Request failed: token=123456')])
        page.wait_for_url = AsyncMock()
        page.url = "https://mp.weixin.qq.com/cgi-bin/home?token=123456"
        page.locator.return_value.evaluate_all = AsyncMock(return_value=[])
        with self.assertRaisesRegex(PreparationError, '编辑器加载失败') as raised:
            await self.adapter().open_editor(page)
        self.assertNotIn('123456', str(raised.exception))


@unittest.skipUnless(os.environ.get("OMNIPOST_BROWSER_TESTS") == "1", "本地浏览器用例需显式启用")
class WechatArticleBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        import conf
        self.directory = TemporaryDirectory()
        self.cover = Path(self.directory.name) / 'cover.png'
        self.cover.write_bytes(PNG)
        self.runtime = await async_playwright().start()
        options = {"headless": True}
        executable = getattr(conf, 'LOCAL_CHROME_PATH', '')
        if executable:
            options['executable_path'] = executable
        self.browser = await self.runtime.chromium.launch(**options)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        self.visited = []
        self.home = 'https://mp.weixin.qq.com/cgi-bin/home?t=home/index&token=123456'

        async def serve(route):
            url = route.request.url
            self.visited.append(url)
            if url == 'https://mp.weixin.qq.com/':
                await route.fulfill(body='<script>history.replaceState(null,"",' + json.dumps(self.home) + ')</script>' + FIXTURE, content_type='text/html; charset=utf-8')
            elif url.endswith('.png'):
                await route.fulfill(body=PNG, content_type='image/png')
            else:
                await route.fulfill(body=FIXTURE, content_type='text/html; charset=utf-8')
        await self.context.route('**/*', serve)
        await self.page.goto('https://mp.weixin.qq.com/cgi-bin/appmsg?token=123456')

    async def asyncTearDown(self):
        await self.context.close()
        await self.browser.close()
        await self.runtime.stop()
        self.directory.cleanup()

    def adapter(self, **values):
        return WechatArticleAdapter(dict(platform='wechat', title='测试文章', mode='publish', **values), self.cover)

    async def boundary(self):
        await self.page.evaluate("events.push('boundary')")

    async def test_home_token_opens_fresh_editor_with_exact_fields(self):
        adapter = self.adapter(options={'author': '测试作者', 'summary': '精确摘要'})
        editor = await adapter.open_editor(self.page)
        query = parse_qs(urlparse(self.page.url).query)
        self.assertEqual(query['token'], ['123456'])
        self.assertEqual(query['type'], ['77'])
        self.assertEqual(query['isNew'], ['1'])
        self.assertNotIn('appmsgid', query)
        self.assertFalse((await editor.inner_text()).strip())
        await adapter.fill_title(self.page)
        await adapter.verify_title(self.page)
        render_page = await self.context.new_page()
        document = await prepare_and_paste_document(
            self.page, editor, render_page,
            '<h2>完整文章</h2><p>这是<strong>保留粗体</strong>的正文。</p>'
            '<ul><li>第一点</li><li>第二点</li></ul>',
            {}, Path(self.directory.name), 'sans-serif')
        await adapter.apply_options(self.page, editor)
        await adapter.verify_options(self.page, editor)
        await _verify_final_body(editor, document, 'wechat')
        self.assertEqual(await self.page.locator('#author').input_value(), '测试作者')
        self.assertEqual(await self.page.locator('#js_description').input_value(), '精确摘要')
        self.assertFalse(adapter._submit_started)
        self.assertEqual(await self.page.evaluate('events'), [])

    async def test_invalid_token_or_host_cannot_enter_editor(self):
        for target in ('https://mp.weixin.qq.com/cgi-bin/home?token=0',
                       'https://mp.weixin.qq.com/cgi-bin/home?token=123&token=456'):
            self.home = target
            with self.assertRaisesRegex(PreparationError, '登录会话'):
                await self.adapter().open_editor(self.page)
            self.assertEqual(self.page.url, target)

    async def test_existing_draft_redirect_cannot_overwrite_content(self):
        async def redirect_to_draft(route):
            await route.fulfill(body=FIXTURE.replace('<p><br></p>', '<p>原始正文</p>') + '<script>history.replaceState(null,"","/cgi-bin/appmsg?appmsgid=987&token=123456")</script>',
                                content_type='text/html; charset=utf-8')
        await self.page.route('**/cgi-bin/appmsg?*', redirect_to_draft)
        with self.assertRaisesRegex(PreparationError, '已有草稿'):
            await self.adapter().open_editor(self.page)
        self.assertEqual(await self.page.locator('.ProseMirror').inner_text(), '原始正文')

    async def test_fresh_url_with_existing_title_body_or_image_never_overwrites(self):
        for content in (
                FIXTURE.replace('<textarea id="title" maxlength="64"></textarea>', '<textarea id="title" maxlength="64">旧标题</textarea>'),
                FIXTURE.replace('<p><br></p>', '<p>原始正文</p>'),
                FIXTURE.replace('<p><br></p>', '<img src="https://mmbiz.qpic.cn/old.png">')):
            async def existing(route):
                await route.fulfill(body=content, content_type='text/html; charset=utf-8')
            await self.page.route('**/cgi-bin/appmsg?*', existing)
            with self.assertRaisesRegex(PreparationError, '已有标题或正文'):
                await self.adapter().open_editor(self.page)
            self.assertEqual(await self.page.evaluate('events'), [])
            await self.page.unroute('**/cgi-bin/appmsg?*', existing)

    async def test_ueditor_uses_actual_frame_and_preserves_existing_body(self):
        modern = '<div class="rich_media_content"><div class="ProseMirror" contenteditable="true"><p><br></p></div></div>'
        for body in ('', '原始正文'):
            fixture = FIXTURE.replace(modern, '<div class="edui-editor-iframeholder"><iframe srcdoc=\'<body contenteditable="true">' + body + '</body>\'></iframe></div>')
            async def framed(route):
                await route.fulfill(body=fixture, content_type='text/html; charset=utf-8')
            await self.page.route('**/cgi-bin/appmsg?*', framed)
            if body:
                with self.assertRaisesRegex(PreparationError, '已有标题或正文'):
                    await self.adapter().open_editor(self.page)
                self.assertEqual(await self.page.frame_locator('iframe').locator('body').inner_text(), body)
            else:
                editor = await self.adapter().open_editor(self.page)
                await editor.fill('完整原生框架正文')
                self.assertEqual(await self.page.frame_locator('iframe').locator('body').inner_text(), '完整原生框架正文')
            await self.page.unroute('**/cgi-bin/appmsg?*', framed)

    async def test_preview_open_guards_publication_and_allows_draft_control(self):
        adapter = WechatArticleAdapter(dict(platform='wechat', title='测试文章', mode='preview'), self.cover)
        await adapter.open_editor(self.page)
        self.assertFalse(await self.page.locator('#publish').is_enabled())
        await self.page.locator('#publish').dispatch_event('click')
        await self.page.locator('#js_submit').click()
        self.assertEqual(await self.page.evaluate('events'), ['draft'])
        self.assertEqual(await self.page.locator('[role=dialog]').count(), 0)

    async def test_stale_success_feedback_cannot_prove_current_publication(self):
        await self.page.evaluate("() => { document.body.insertAdjacentHTML('beforeend','<div role=alert>发表成功</div>'); window.showConfirm=()=>document.body.insertAdjacentHTML('beforeend','<div role=dialog>请扫码确认发表</div>'); }")
        adapter = self.adapter()
        await adapter.submit(self.page, self.boundary)
        await self.page.locator('[role=dialog]').evaluate('el=>el.remove()')
        self.assertEqual((await adapter.read_result(self.page))['status'], 'unknown')
        self.assertEqual(await self.page.evaluate('events'), ['boundary', 'entry'])

    async def test_foreign_origin_cannot_publish_or_supply_feedback(self):
        await self.page.goto('https://example.com/cgi-bin/appmsg?token=123456')
        adapter, callback = self.adapter(), MagicMock()
        with self.assertRaisesRegex(PreparationError, '原生文章编辑器'):
            await adapter.submit(self.page, callback)
        callback.assert_not_called()
        adapter._submit_started = True
        await self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<div role=alert>发表成功</div>')")
        self.assertEqual((await adapter.read_result(self.page))['status'], 'unknown')

        async def foreign_confirmation(route):
            await route.fulfill(body=FIXTURE + '<script>showConfirm()</script>', content_type='text/html; charset=utf-8')
        await self.page.route('https://example.com/confirm', foreign_confirmation)
        await self.page.goto('https://mp.weixin.qq.com/cgi-bin/appmsg?token=123456')
        await self.page.locator('#publish').evaluate("el=>el.onclick=()=>{location.href='https://example.com/confirm'}")
        adapter, callback = self.adapter(), MagicMock()
        await adapter.submit(self.page, callback)
        callback.assert_called_once()
        self.assertEqual(await self.page.evaluate('events'), [])
        self.assertEqual((await adapter.read_result(self.page))['status'], 'unknown')


    async def test_only_draft_controls_cannot_satisfy_publish(self):
        await self.page.evaluate("document.querySelector('#publish').remove()")
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, '发表按钮'):
            await self.adapter().submit(self.page, callback)
        callback.assert_not_called()
        self.assertEqual(await self.page.evaluate('events'), [])

    async def test_publish_boundary_precedes_both_single_clicks(self):
        adapter = self.adapter()
        await adapter.submit(self.page, self.boundary)
        self.assertEqual(await self.page.evaluate('events'), ['boundary', 'entry', 'publish'])
        self.assertEqual((await adapter.read_result(self.page))['status'], 'submitted')
        with self.assertRaisesRegex(PreparationError, '已经尝试'):
            await adapter.submit(self.page, self.boundary)
        self.assertEqual(await self.page.evaluate('events'), ['boundary', 'entry', 'publish'])

    async def test_failed_boundary_does_not_click(self):
        async def fail():
            raise RuntimeError('保存边界失败')
        adapter = self.adapter()
        with self.assertRaisesRegex(RuntimeError, '保存边界失败'):
            await adapter.submit(self.page, fail)
        self.assertFalse(adapter._submit_started)
        self.assertEqual(await self.page.evaluate('events'), [])

    async def test_preview_cannot_publish_even_when_submit_called_directly(self):
        adapter = WechatArticleAdapter(dict(platform='wechat', title='测试文章', mode='preview'), self.cover)
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, '预览模式禁止'):
            await adapter.submit(self.page, callback)
        callback.assert_not_called()
        self.assertEqual(await self.page.evaluate('events'), [])

    async def test_duplicate_publish_buttons_stop_before_boundary(self):
        await self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<button>发表</button>')")
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, '唯一'):
            await self.adapter().submit(self.page, callback)
        callback.assert_not_called()
        self.assertEqual(await self.page.evaluate('events'), [])

    async def test_qr_challenge_prevents_submit_and_returns_needs_action(self):
        await self.page.evaluate("document.body.insertAdjacentHTML('beforeend','<div role=dialog>请管理员扫码验证</div>')")
        adapter = self.adapter()
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, '扫码或安全验证'):
            await adapter.submit(self.page, callback)
        callback.assert_not_called()
        self.assertEqual((await adapter.read_result(self.page))['status'], 'needs_action')

    async def test_qr_after_entry_does_not_confirm_or_retry(self):
        await self.page.evaluate("() => { window.showConfirm=()=>document.body.insertAdjacentHTML('beforeend','<div role=dialog>请扫码确认发表<button>确认发表</button></div>'); }")
        adapter = self.adapter()
        await adapter.submit(self.page, self.boundary)
        self.assertEqual(await self.page.evaluate('events'), ['boundary', 'entry'])
        self.assertEqual((await adapter.read_result(self.page))['status'], 'needs_action')

    async def test_draft_id_and_save_messages_never_count_as_publication(self):
        adapter = self.adapter()
        adapter._submit_started = True
        for message in ('保存成功', '草稿保存成功', '发表成功后请到列表查看'):
            await self.page.goto('https://mp.weixin.qq.com/cgi-bin/appmsg?appmsgid=123456&token=123456')
            await self.page.evaluate("text=>document.body.insertAdjacentHTML('beforeend','<div role=alert>'+text+'</div>')", message)
            result = await adapter.read_result(self.page)
            self.assertEqual(result['status'], 'unknown')
            self.assertNotIn('platform_id', result)

    async def test_body_feedback_and_scan_words_are_not_platform_evidence(self):
        adapter = self.adapter()
        adapter._submit_started = True
        await self.page.locator('.ProseMirror').fill('扫码安全验证：发表成功')
        await self.page.locator('.ProseMirror').evaluate("el=>el.insertAdjacentHTML('beforeend','<div role=alert>发表成功</div><div role=dialog>管理员扫码</div>')")
        self.assertEqual((await adapter.read_result(self.page))['status'], 'unknown')

    async def test_author_truncation_is_detected(self):
        adapter = self.adapter(options={'author': '原始作者'})
        await self.page.locator('#author').fill('作者')
        with self.assertRaisesRegex(PreparationError, '作者读回不一致'):
            await adapter.verify_options(self.page, self.page.locator('.ProseMirror'))

    async def test_unsupported_options_and_tags_fail_before_upload(self):
        for options in ({'tags': ['话题']}, {'options': {'statement': '声明'}}):
            adapter = self.adapter(**options)
            with self.assertRaises(PreparationError):
                await adapter.apply_options(self.page, self.page.locator('.ProseMirror'))
            self.assertEqual(await self.page.locator('#js_cover_area img').count(), 0)

    async def test_body_image_or_local_cover_preview_cannot_prove_cover_upload(self):
        adapter = self.adapter()
        await self.page.locator('.ProseMirror').evaluate("el=>el.insertAdjacentHTML('beforeend','<img src=https://mmbiz.qpic.cn/body.png>')")
        with self.assertRaisesRegex(PreparationError, '新封面上传完成'):
            await adapter.verify_options(self.page, self.page.locator('.ProseMirror'))
        await self.page.locator('#js_cover_area').evaluate("el=>el.insertAdjacentHTML('beforeend','<img src=\"data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jr1sAAAAASUVORK5CYII=\">')")
        with self.assertRaisesRegex(PreparationError, '新封面上传完成'):
            await adapter.verify_options(self.page, self.page.locator('.ProseMirror'))

    async def test_stale_cover_does_not_count_as_current_upload(self):
        adapter = self.adapter()
        adapter._cover_before = {'https://mmbiz.qpic.cn/old.png'}
        await self.page.locator('#js_cover_area').evaluate("el=>el.insertAdjacentHTML('beforeend','<img src=https://mmbiz.qpic.cn/old.png>')")
        await self.page.locator('#js_cover_area img').evaluate('img=>img.decode()')
        with self.assertRaisesRegex(PreparationError, '新封面上传完成'):
            await adapter.verify_options(self.page, self.page.locator('.ProseMirror'))

    async def test_public_article_requires_expected_title_and_no_preview_credentials(self):
        adapter = self.adapter()
        adapter._submit_started = True
        for url, title, expected in (
                ('https://mp.weixin.qq.com/s/abcdefghijklmn', '测试文章', 'published'),
                ('https://mp.weixin.qq.com/s/abcdefghijklmn?tempkey=example', '测试文章', 'unknown'),
                ('https://mp.weixin.qq.com/s/abcdefghijklmn', '另一篇文章', 'unknown')):
            await self.page.goto(url)
            await self.page.evaluate("title=>document.body.insertAdjacentHTML('beforeend','<h1 id=activity-name>'+title+'</h1>')", title)
            self.assertEqual((await adapter.read_result(self.page))['status'], expected)


if __name__ == '__main__':
    unittest.main()

"""京东图文的可重复边界验证；默认不启动浏览器、不连接平台。"""
import base64
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

from utils.articles.browser import PreparationError
from utils.articles.jd import JDNoteAdapter, parse_product_links


def controls(*items):
    locator = MagicMock()
    locator.count = AsyncMock(return_value=len(items))
    locator.nth.side_effect = lambda index: items[index]
    return locator


def field(value='发布'):
    item = MagicMock()
    item.is_visible = AsyncMock(return_value=True)
    item.is_enabled = AsyncMock(return_value=True)
    item.scroll_into_view_if_needed = AsyncMock()
    item.click = AsyncMock()
    item.inner_text = AsyncMock(return_value=value)
    item.get_attribute = AsyncMock(return_value=None)
    item.fill = AsyncMock()
    return item


class JDArticleBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def adapter(self, **values):
        adapter = JDNoteAdapter(dict(platform='jd', title='京东图文测试文章', mode='publish', **values), None)
        adapter._validate_options()
        return adapter

    def ready(self, button=None):
        adapter = self.adapter()
        adapter._note_document = object()
        adapter.verify_note = AsyncMock()
        adapter._feedback_texts = AsyncMock(return_value=[])
        adapter._note_scope = MagicMock()
        button = button or field()
        adapter._note_scope.locator.return_value = controls(button)
        return adapter, button

    def test_product_links_are_exact_jd_skus_and_deduplicated(self):
        self.assertEqual(parse_product_links('123,https://item.jd.com/456.html?sku=1\n123'), ['123', '456'])
        self.assertEqual(parse_product_links(''), [])
        for value in ('https://item.jd.com.evil.test/123.html', 'https://evil.test/123.html',
                      'https://item.jd.com@evil.test/123.html', 'javascript:123', 'https://item.jd.com/0.html',
                      'https://u.jd.com/abc', ['123']):
            with self.subTest(value=value), self.assertRaises(PreparationError):
                parse_product_links(value)
        with self.assertRaisesRegex(PreparationError, '10'):
            parse_product_links(','.join(str(i) for i in range(1, 12)))

    async def test_preview_cannot_call_boundary_or_click(self):
        adapter, button = self.ready()
        adapter.snapshot['mode'] = 'preview'
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, '预览任务禁止'):
            await adapter.submit(MagicMock(), callback)
        callback.assert_not_called()
        button.click.assert_not_awaited()

    async def test_selected_cover_cannot_be_silently_replaced_by_first_body_image(self):
        with TemporaryDirectory() as directory:
            first, second = Path(directory) / 'first.png', Path(directory) / 'second.png'
            first.write_bytes(PNG)
            second.write_bytes(PNG)
            snapshot = dict(platform='jd', title='京东图文测试文章', mode='preview', cover_asset_id='b',
                            content_html='<p>正文<img data-asset-id="a"><img data-asset-id="b"></p>')
            assets = {'a': dict(path=str(first), mime_type='image/png'),
                      'b': dict(path=str(second), mime_type='image/png')}
            adapter = JDNoteAdapter(snapshot, second)
            adapter._open_note = AsyncMock()
            with self.assertRaisesRegex(PreparationError, '首图'):
                await adapter.prepare_note(MagicMock(), assets)
            adapter._open_note.assert_not_awaited()

    async def test_submit_requires_prepared_album(self):
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, '尚未完成准备'):
            await self.adapter().submit(MagicMock(), callback)
        callback.assert_not_called()

    async def test_boundary_precedes_click_and_failed_click_is_not_retried(self):
        adapter, button = self.ready()
        events = []
        async def boundary():
            events.append('boundary')
        async def failed_click(**kwargs):
            events.append('click')
            raise RuntimeError('网络断开')
        button.click.side_effect = failed_click
        with self.assertRaisesRegex(RuntimeError, '网络断开'):
            await adapter.submit(MagicMock(), boundary)
        with self.assertRaisesRegex(PreparationError, '已经尝试'):
            await adapter.submit(MagicMock(), boundary)
        self.assertEqual(events, ['boundary', 'click'])
        button.click.assert_awaited_once()

    async def test_boundary_failure_prevents_platform_click(self):
        adapter, button = self.ready()
        def fail():
            raise RuntimeError('数据库失败')
        with self.assertRaisesRegex(RuntimeError, '数据库失败'):
            await adapter.submit(MagicMock(), fail)
        button.click.assert_not_awaited()
        self.assertFalse(adapter._submit_started)

    async def test_duplicate_or_draft_button_fails_before_boundary(self):
        for candidates in ((field(), field()), (field('保存草稿'),)):
            adapter, _ = self.ready()
            adapter._note_scope.locator.return_value = controls(*candidates)
            callback = MagicMock()
            with self.assertRaises(PreparationError):
                await adapter.submit(MagicMock(), callback)
            callback.assert_not_called()
            for button in candidates:
                button.click.assert_not_awaited()

    async def test_source_title_minimum_and_current_maximum_are_enforced(self):
        adapter = self.adapter()
        title = field()
        title.get_attribute.side_effect = lambda key: {'placeholder': '添加一个亮眼的标题吧，5~6个字', 'maxlength': '6'}.get(key)
        adapter._title_field = AsyncMock(return_value=title)
        with self.assertRaisesRegex(PreparationError, '5～6'):
            await adapter.fill_title(MagicMock())
        title.fill.assert_not_awaited()

    async def test_unknown_option_cannot_be_ignored(self):
        with self.assertRaisesRegex(PreparationError, '不支持的选项'):
            self.adapter(options={'publish_text': '微博文案'})

    async def test_cover_generation_needs_new_uploaded_url(self):
        adapter = self.adapter()
        adapter._cover_before = {'https://m.360buyimg.com/ceco/placeholder.png'}
        page = MagicMock()
        page.wait_for_timeout = AsyncMock()
        for url in ('blob:local-cover', 'https://m.360buyimg.com/ceco/placeholder.png', 'https://evil.test/cover.png'):
            adapter._cover_images = AsyncMock(return_value=[dict(src=url, ready=True)])
            with self.assertRaisesRegex(PreparationError, '首图封面尚未生成'):
                await adapter._wait_generated_cover(page, MagicMock())
        adapter._cover_images = AsyncMock(return_value=[dict(src='https://m.360buyimg.com/ceco/new.png', ready=True)])
        await adapter._wait_generated_cover(page, MagicMock())

    async def test_product_readback_mismatch_prevents_submit(self):
        adapter = self.adapter(options={'product_links': '123'})
        adapter._note_scope = MagicMock()
        adapter._selected_products = AsyncMock(return_value=[dict(sku='456', valid=True)])
        with patch('utils.articles.notes.NoteAdapter.verify_note', new=AsyncMock()):
            with self.assertRaisesRegex(PreparationError, '关联商品数量'):
                await adapter.verify_note(MagicMock())

    async def test_only_actual_submission_receipts_count(self):
        adapter = self.adapter()
        page = MagicMock()
        locator = MagicMock()
        locator.evaluate_all = AsyncMock()
        page.locator.return_value = locator
        with patch('utils.articles.jd.has_visible_challenge', new=AsyncMock(return_value=False)):
            locator.evaluate_all.return_value = ['发布成功，等待审核！']
            self.assertEqual((await adapter.read_result(page))['status'], 'unknown')
            adapter._submit_started = True
            for text in ('保存草稿成功！', '发布成功后请到列表查看', '内容列表'):
                locator.evaluate_all.return_value = [text]
                self.assertEqual((await adapter.read_result(page))['status'], 'unknown')
            locator.evaluate_all.return_value = ['发布成功，等待审核！']
            result = await adapter.read_result(page)
            self.assertEqual(result['status'], 'submitted')
            self.assertNotIn('platform_url', result)

    async def test_feedback_visible_before_submit_does_not_confirm_new_publication(self):
        adapter, _ = self.ready()
        adapter._feedback_texts.return_value = ['发布成功，等待审核！']
        await adapter.submit(MagicMock(), MagicMock())
        with patch('utils.articles.jd.has_visible_challenge', new=AsyncMock(return_value=False)):
            self.assertEqual((await adapter.read_result(MagicMock()))['status'], 'unknown')

    async def test_challenge_requires_action_without_success(self):
        with patch('utils.articles.jd.has_visible_challenge', new=AsyncMock(return_value=True)):
            page = MagicMock()
            page.locator.return_value.evaluate_all = AsyncMock(return_value=[])
            self.assertEqual((await self.adapter().read_result(page))['status'], 'needs_action')


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jr1sAAAAASUVORK5CYII=')


@unittest.skipUnless(os.environ.get('OMNIPOST_BROWSER_TESTS') == '1', '本地浏览器用例需显式启用')
class JDArticleBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from playwright.async_api import async_playwright
        import conf
        self.directory = TemporaryDirectory()
        self.runtime = await async_playwright().start()
        launch = dict(headless=True)
        if getattr(conf, 'LOCAL_CHROME_PATH', ''):
            launch['executable_path'] = conf.LOCAL_CHROME_PATH
        self.browser = await self.runtime.chromium.launch(**launch)
        self.context = await self.browser.new_context()
        self.page = await self.context.new_page()
        self.fixture_html = '<html><body><div class="dr-publish-graphic-wrapper" style="min-height:30px"></div></body></html>'
        async def fixture(route):
            if route.request.url.endswith('.png'):
                await route.fulfill(body=PNG, content_type='image/png')
            else:
                await route.fulfill(body=self.fixture_html, content_type='text/html; charset=utf-8')
        await self.context.route('**/*', fixture)
        await self.page.goto('https://dr.jd.com/n/publish-graphic.html')
        self.adapter = JDNoteAdapter(dict(platform='jd', title='京东图文测试文章', mode='publish'), None)
        self.adapter._validate_options()
        self.scope = await self.adapter._scope(self.page)

    async def asyncTearDown(self):
        await self.context.close()
        await self.browser.close()
        await self.runtime.stop()
        self.directory.cleanup()

    async def test_prepare_two_images_title_body_and_generated_cover(self):
        self.fixture_html = """<html><body><div class="dr-publish-graphic-wrapper">
            <input id="title" maxlength="20" placeholder="添加一个亮眼的标题吧，5~20个字">
            <textarea id="description" maxlength="1000"></textarea>
            <button data-spm-click="onClickLeftSelectFile" onclick="upload.click()">上传图片</button>
            <input type="file" id="upload" style="display:none" accept="image/png">
            <div class="dr-upload-image-component"><button class="file-item btn-upload" onclick="upload.click()">添加</button></div>
            <div class="dr-cover-edit-wrapper"><img class="cover-image" src="https://m.360buyimg.com/placeholder.png"></div>
            <button data-spm="onFormValidateByPublish">发布</button>
            </div><script>
            window._gdata={user:{id:'123',pin:'fixture'}};
            let count=0;
            upload.onchange=()=>{
                count++;
                const item=document.createElement('div');item.className='file-item';
                const src='https://m.360buyimg.com/server'+count+'.png';
                item.innerHTML='<img src="'+src+'">';
                item.__reactFiber$fixture={return:{memoizedProps:{file:{img:src}}}};
                document.querySelector('.dr-upload-image-component').appendChild(item);
                document.querySelector('.cover-image').src='https://m.360buyimg.com/cover.png';
            };
            </script></body></html>"""
        paths = [Path(self.directory.name) / (name + '.png') for name in ('first', 'second')]
        for path in paths:
            path.write_bytes(PNG)
        self.adapter.snapshot['content_html'] = '<p>完整正文</p><p><img data-asset-id="a"><img data-asset-id="b"></p>'
        assets = {key: dict(path=str(path), mime_type='image/png') for key, path in zip(('a', 'b'), paths)}
        editor, document = await self.adapter.prepare_note(self.page, assets)
        self.assertEqual(await editor.input_value(), '完整正文')
        self.assertEqual(await self.page.locator('#title').input_value(), '京东图文测试文章')
        self.assertEqual(document.uploaded_urls, ['https://m.360buyimg.com/server1.png', 'https://m.360buyimg.com/server2.png'])
        self.assertFalse(self.adapter._submit_started)
        await self.adapter.verify_note(self.page)

    async def test_album_uses_uploaded_model_and_excludes_product_images(self):
        await self.scope.evaluate("""el => {
            el.innerHTML='<div class="dr-upload-image-component"><div class="file-item"><img src="https://m.360buyimg.com/local.png"></div></div>'+
              '<div class="publish-related-info-wrapper"><img src="https://m.360buyimg.com/product.png"></div>';
            const item=el.querySelector('.file-item');
            item.__reactFiber$fixture={return:{memoizedProps:{file:{img:'//m.360buyimg.com/server.png'}}}};
        }""")
        await self.scope.locator('.file-item img').evaluate('img=>img.decode()')
        images = await self.adapter._album_images(self.scope)
        self.assertEqual(images, [dict(src='https://m.360buyimg.com/server.png', ready=True)])
        await self.scope.locator('.file-item').evaluate("el=>el.insertAdjacentHTML('beforeend','<div class=upload-status>上传中</div>')")
        self.assertFalse((await self.adapter._album_images(self.scope))[0]['ready'])

    async def test_plain_remote_thumbnail_cannot_substitute_for_upload_model(self):
        await self.scope.evaluate("el=>el.innerHTML='<div class=dr-upload-image-component><div class=file-item><img src=https://m.360buyimg.com/local.png></div></div>'")
        await self.scope.locator('img').evaluate('img=>img.decode()')
        self.assertEqual(await self.adapter._album_images(self.scope), [dict(src='', ready=False)])

    async def test_sku_candidate_text_does_not_count_as_selected_product(self):
        await self.scope.evaluate("""el => {
            el.innerHTML='<div class=publish-related-info-wrapper><div class=goods-area>SKU 123</div></div>';
        }""")
        self.assertEqual(await self.adapter._selected_products(self.scope), [dict(sku='', valid=False)])
        await self.scope.locator('.goods-area').evaluate("el=>{el.__reactFiber$fixture={return:{memoizedProps:{item:{skuId:'123',isValid:1,enableAddSku:1}}}}}")
        self.assertEqual(await self.adapter._selected_products(self.scope), [dict(sku='123', valid=True)])

    async def test_body_status_words_cannot_forge_receipt(self):
        self.adapter._submit_started = True
        await self.scope.evaluate("el=>el.innerHTML='<div contenteditable=true><div role=alert>发布成功，等待审核！</div></div>'")
        self.assertEqual((await self.adapter.read_result(self.page))['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()

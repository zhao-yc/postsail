"""千帆商家笔记测试：独立商家身份、精确商品与单次发布边界。"""
import base64
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock

from utils.articles.browser import PreparationError
from utils.articles.notes import create_note_adapter
from utils.articles.xiaohongshu_merchant import (
    MERCHANT_PUBLISH_URL, XiaohongshuMerchantAdapter, product_id_from_text,
    read_merchant_store_name, require_merchant_origin,
)


PRODUCT_ID = "66cc671ee6fff40001091111"


def snapshot(**changes):
    data = dict(platform="xiaohongshu_merchant", title="商家完整标题", mode="publish", tags=[],
                options={"product_id": PRODUCT_ID, "shop_name": "测试店铺"},
                content_html='<p>商品介绍</p><img data-asset-id="first"><p>详细说明</p>'
                             '<img data-asset-id="second">')
    data.update(changes)
    return data


def controls(*items):
    group = MagicMock()
    group.count = AsyncMock(return_value=len(items))
    group.nth.side_effect = lambda index: items[index]
    return group


def field(value, visible=True):
    item = MagicMock()
    item.is_visible = AsyncMock(return_value=visible)
    item.inner_text = AsyncMock(return_value=value)
    return item


class MerchantValidationTests(unittest.TestCase):
    def test_adapter_is_registered_as_distinct_merchant_platform(self):
        self.assertIsInstance(create_note_adapter(snapshot()), XiaohongshuMerchantAdapter)
        self.assertEqual(XiaohongshuMerchantAdapter.editor_url, MERCHANT_PUBLISH_URL)
        self.assertNotIn("creator.xiaohongshu.com", XiaohongshuMerchantAdapter.editor_url)

    def test_merchant_origin_excludes_personal_login_and_similar_hosts(self):
        require_merchant_origin(MERCHANT_PUBLISH_URL)
        for url in (
            "https://creator.xiaohongshu.com/publish/publish", "https://www.xiaohongshu.com/explore",
            "https://customer.xiaohongshu.com/login", "https://ark.xiaohongshu.com/ark/login",
            "https://ark.xiaohongshu.com.evil.test/app-note/publish", "http://ark.xiaohongshu.com/app-note/publish",
            "https://user@ark.xiaohongshu.com/app-note/publish", "https://ark.xiaohongshu.com:444/app-note/publish",
            "https://ark.xiaohongshu.com:invalid/app-note/publish",
        ):
            with self.subTest(url=url), self.assertRaises(PreparationError):
                require_merchant_origin(url)

    def test_options_require_exact_shop_and_product(self):
        for options in ({}, {"shop_name": "测试店铺"}, {"product_id": PRODUCT_ID},
                        {"product_id": "word other", "shop_name": "测试店铺"},
                        {"product_id": PRODUCT_ID, "shop_name": " 测试店铺 "},
                        {"product_id": PRODUCT_ID, "shop_name": "测试店铺", "auto_select": True},
                        {"product_id": PRODUCT_ID, "shop_name": "测试店铺", "flatten_content": "true"}):
            with self.subTest(options=options), self.assertRaises(PreparationError):
                XiaohongshuMerchantAdapter(snapshot(options=options), None)._validate_options()
        XiaohongshuMerchantAdapter(snapshot(), None)._validate_options()

    def test_product_card_requires_labeled_complete_id(self):
        for text in (f"商品：{PRODUCT_ID}", f"商品 ID: {PRODUCT_ID}", f"5 商品：{PRODUCT_ID}"):
            self.assertEqual(product_id_from_text(text), PRODUCT_ID)
        for text in (f"标题中提到{PRODUCT_ID}", f"商品：{PRODUCT_ID} 其他说明", "商品：", PRODUCT_ID):
            self.assertIsNone(product_id_from_text(text))
        self.assertNotEqual(product_id_from_text(f"商品：{PRODUCT_ID}0"), PRODUCT_ID)


class MerchantIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_personal_page_is_rejected_before_reading_merchant_dom(self):
        page = MagicMock(url="https://creator.xiaohongshu.com/publish/publish")
        with self.assertRaises(PreparationError):
            await read_merchant_store_name(page, "测试店铺")
        page.locator.assert_not_called()

    async def test_store_name_must_be_unique_nonempty_and_match(self):
        page = MagicMock(url=MERCHANT_PUBLISH_URL)
        page.locator.return_value = controls(field("测试店铺"))
        self.assertEqual(await read_merchant_store_name(page, "测试店铺"), "测试店铺")
        for values in ([], [""], ["别的店铺"], ["测试店铺", "测试店铺"]):
            page.locator.return_value = controls(*(field(value) for value in values))
            with self.subTest(values=values), self.assertRaises(PreparationError):
                await read_merchant_store_name(page, "测试店铺")

    async def test_product_search_does_not_accept_prefix_or_duplicate(self):
        adapter = XiaohongshuMerchantAdapter(snapshot(), None)
        page = MagicMock()
        page.wait_for_timeout = AsyncMock()
        card = MagicMock()
        adapter._product_cards = AsyncMock(return_value=[(card, PRODUCT_ID + "0")])
        with self.assertRaisesRegex(PreparationError, "准确商品"):
            await adapter._wait_for_product(page)
        adapter._product_cards.return_value = [(card, PRODUCT_ID), (card, PRODUCT_ID)]
        with self.assertRaisesRegex(PreparationError, "多个相同商品"):
            await adapter._wait_for_product(page)
        adapter._product_cards.return_value = [(card, PRODUCT_ID)]
        self.assertIs(await adapter._wait_for_product(page), card)

    async def test_missing_required_options_stops_before_navigation(self):
        page = MagicMock()
        page.goto = AsyncMock()
        with self.assertRaisesRegex(PreparationError, "商品 ID"):
            await XiaohongshuMerchantAdapter(snapshot(options={}), None)._open_note(page)
        page.goto.assert_not_awaited()

    async def test_preview_never_invokes_submit_boundary(self):
        adapter = XiaohongshuMerchantAdapter(snapshot(mode="preview"), None)
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, "预览任务禁止"):
            await adapter.submit(MagicMock(), callback)
        callback.assert_not_called()


_MERCHANT_HTML = '''<!doctype html><html><body>
<header><span class="store-name">测试店铺</span></header>
<section id="search"><input placeholder="请输入商品ID/商品名称查询">
<div class="cell-note-item"><span class="item-title">测试商品</span>
<span class="item-desc">商品：PRODUCT_ID</span><button id="start">去发笔记</button></div></section>
<button id="manual" style="display:none">手动创作</button>
<section class="container" id="edit" style="display:none">
<div class="header"><button id="image-tab">上传图文</button></div>
<div class="upload-wrapper"><input type="file" accept="image/png" multiple hidden></div>
<div class="cell-note-item" id="selected"><img width="60" height="60" src="https://img.xhscdn.com/product.png">
<span class="item-desc">商品：PRODUCT_ID</span></div><section id="album"></section>
<input placeholder="填写标题，可能会有更多赞哦～"><textarea id="post-textarea"></textarea>
<button id="publish">发布</button></section><script>
window.submits=0;window.actions=[];
document.querySelector('#start').onclick=()=>{
    window.actions.push('product');document.querySelector('#search').style.display='none';
    document.querySelector('#manual').style.display='block';
};
document.querySelector('#manual').onclick=()=>{
    window.actions.push('manual');document.querySelector('#manual').style.display='none';
    document.querySelector('#edit').style.display='block';
};
document.querySelector('#image-tab').onclick=()=>window.actions.push('image');
document.querySelector('input[type=file]').onchange=event=>{
    for(const file of event.target.files){
        const img=document.createElement('img');img.width=80;img.height=80;
        img.src='https://img.xhscdn.com/'+file.name;document.querySelector('#album').appendChild(img);
    }
};
document.querySelector('#publish').onclick=()=>{window.submits++;window.actions.push('publish');};
</script></body></html>'''.replace("PRODUCT_ID", PRODUCT_ID)


@unittest.skipUnless(os.environ.get("OMNIPOST_BROWSER_TESTS") == "1", "需显式开启本地浏览器测试")
class MerchantBrowserTests(unittest.IsolatedAsyncioTestCase):
    """复现公开控件路径；所有页面及图片均使用本地响应，不登录外部平台。"""

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
        await self.page.route(MERCHANT_PUBLISH_URL, lambda route: route.fulfill(
            body=_MERCHANT_HTML, content_type="text/html; charset=utf-8"))
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jDlsAAAAASUVORK5CYII=")
        await self.page.route("https://img.xhscdn.com/**", lambda route: route.fulfill(body=png, content_type="image/png"))
        self.assets = {}
        for name in ("first", "second"):
            path = Path(self.temp.name) / (name + ".png")
            path.write_bytes(png)
            self.assets[name] = dict(path=str(path), mime_type="image/png", width=1, height=1)

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def test_merchant_product_flow_verifies_original_album_and_single_submission(self):
        adapter = XiaohongshuMerchantAdapter(snapshot(), None)
        editor, document = await adapter.prepare_note(self.page, self.assets)
        self.assertEqual(await editor.input_value(), "商品介绍\n详细说明")
        self.assertEqual(document.uploaded_urls,
                         ["https://img.xhscdn.com/first.png", "https://img.xhscdn.com/second.png"])
        self.assertEqual(await self.page.evaluate("window.actions"), ["product", "manual", "image"])
        marks = []
        await adapter.submit(self.page, lambda: marks.append("boundary"))
        with self.assertRaisesRegex(PreparationError, "已经尝试"):
            await adapter.submit(self.page, lambda: marks.append("retry"))
        self.assertEqual(marks, ["boundary"])
        self.assertEqual(await self.page.evaluate("window.submits"), 1)

    async def test_changed_shop_blocks_before_submit(self):
        adapter = XiaohongshuMerchantAdapter(snapshot(), None)
        await adapter.prepare_note(self.page, self.assets)
        await self.page.locator('.store-name').evaluate("el=>el.textContent='另一家店铺'")
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, "店铺名称不一致"):
            await adapter.submit(self.page, callback)
        callback.assert_not_called()
        self.assertEqual(await self.page.evaluate("window.submits"), 0)

    async def test_changed_product_or_unbound_search_card_blocks_before_submit(self):
        adapter = XiaohongshuMerchantAdapter(snapshot(), None)
        await adapter.prepare_note(self.page, self.assets)
        field = self.page.locator('#selected .item-desc')
        await field.evaluate("el=>el.textContent+='0'")
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, "准确商品 ID"):
            await adapter.submit(self.page, callback)
        await field.evaluate('(el,id)=>el.textContent="商品："+id', PRODUCT_ID)
        await self.page.locator('#selected').evaluate("el=>el.insertAdjacentHTML('beforeend','<button>去发笔记</button>')")
        with self.assertRaisesRegex(PreparationError, "搜索候选商品"):
            await adapter.submit(self.page, callback)
        callback.assert_not_called()
        self.assertEqual(await self.page.evaluate("window.submits"), 0)

    async def test_album_order_change_is_rejected(self):
        adapter = XiaohongshuMerchantAdapter(snapshot(), None)
        await adapter.prepare_note(self.page, self.assets)
        await self.page.locator('#album').evaluate('el=>el.appendChild(el.firstChild)')
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, "顺序发生变化"):
            await adapter.submit(self.page, callback)
        callback.assert_not_called()

    async def test_product_thumbnail_does_not_hide_a_restored_note_album(self):
        old_album = _MERCHANT_HTML.replace('<section id="album"></section>',
            '<section id="album"><img width="80" height="80" src="https://img.xhscdn.com/old-note.png"></section>')
        await self.page.route(MERCHANT_PUBLISH_URL, lambda route: route.fulfill(
            body=old_album, content_type="text/html; charset=utf-8"))
        adapter = XiaohongshuMerchantAdapter(snapshot(), None)
        with self.assertRaisesRegex(PreparationError, "恢复的草稿"):
            await adapter.prepare_note(self.page, self.assets)
        self.assertEqual(await self.page.locator('#album img').count(), 1)
        self.assertEqual(await self.page.locator('input[type=file]').evaluate('el=>el.files.length'), 0)
        self.assertEqual(await self.page.evaluate("window.submits"), 0)

    async def test_preview_navigation_works_but_publish_stays_blocked(self):
        adapter = XiaohongshuMerchantAdapter(snapshot(mode="preview"), None)
        await adapter.prepare_note(self.page, self.assets)
        self.assertTrue(await self.page.get_by_role('button', name='发布', exact=True).is_disabled())
        await self.page.get_by_role('button', name='发布', exact=True).dispatch_event('click')
        await self.page.keyboard.press('ControlOrMeta+Enter')
        self.assertEqual(await self.page.evaluate("window.submits"), 0)
        self.assertEqual(await self.page.evaluate("window.actions"), ["product", "manual", "image"])

    async def test_submission_timeout_has_one_callback_and_one_click(self):
        adapter = XiaohongshuMerchantAdapter(snapshot(), None)
        await adapter.prepare_note(self.page, self.assets)
        # 浏览器接收到点击后返回错误；不能因为按钮仍在就再次发布。
        button = MagicMock()
        button.is_visible = AsyncMock(return_value=True)
        button.is_enabled = AsyncMock(return_value=True)
        button.scroll_into_view_if_needed = AsyncMock()
        button.click = AsyncMock(side_effect=TimeoutError("already sent"))
        scope = MagicMock()
        scope.get_by_role.return_value = controls(button)
        adapter._note_scope = scope
        adapter.verify_note = AsyncMock()
        marks = []
        with self.assertRaises(TimeoutError):
            await adapter.submit(self.page, lambda: marks.append("boundary"))
        with self.assertRaisesRegex(PreparationError, "已经尝试"):
            await adapter.submit(self.page, lambda: marks.append("retry"))
        self.assertEqual(marks, ["boundary"])
        button.click.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()

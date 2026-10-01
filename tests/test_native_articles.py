"""原生文章适配器边界测试，受控控件不登录、不连接发布平台。"""
import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from utils.articles.browser import PreparationError
from utils.articles.native import create_native_adapter


def controls(*items):
    """模拟完整候选集合，以检测隐藏、禁用和重复控件误命中。"""
    locator = MagicMock()
    locator.count = AsyncMock(return_value=len(items))
    locator.nth.side_effect = list(items)
    return locator


def field(value="", visible=True, enabled=True):
    """模拟一个原生控件，事件序列由各测试独立记录。"""
    item = MagicMock()
    item.is_visible = AsyncMock(return_value=visible)
    item.is_enabled = AsyncMock(return_value=enabled)
    item.scroll_into_view_if_needed = AsyncMock()
    item.click = AsyncMock()
    item.fill = AsyncMock()
    item.evaluate = AsyncMock(return_value=value)
    item.get_attribute = AsyncMock(return_value=None)
    return item


class NativeArticleBoundaryTests(unittest.IsolatedAsyncioTestCase):
    """提交必须持久化在先，歧义或准备错误不能产生平台提交。"""

    def adapter(self, platform="bilibili", **values):
        return create_native_adapter(dict(platform=platform, title="测试文章", **values))

    def page(self, button):
        page = MagicMock()
        page.get_by_role.return_value = controls(button)
        page.wait_for_timeout = AsyncMock()
        return page

    async def test_submit_boundary_precedes_click_and_is_not_retried(self):
        events = []
        button = field()
        async def fail_click(**kwargs):
            events.append("平台点击")
            raise RuntimeError("点击已发送但网络断开")
        button.click.side_effect = fail_click
        page = self.page(button)
        adapter = self.adapter()
        with self.assertRaisesRegex(RuntimeError, "网络断开"):
            await adapter.submit(page, lambda: events.append("持久化"))
        # 按钮再次出现也不能在同一个任务中再次点击。
        page.get_by_role.return_value = controls(button)
        with self.assertRaisesRegex(PreparationError, "已经尝试"):
            await adapter.submit(page, lambda: events.append("重复持久化"))
        self.assertEqual(events, ["持久化", "平台点击"])
        button.click.assert_awaited_once()

    async def test_boundary_write_failure_never_clicks(self):
        button = field()
        def reject():
            raise RuntimeError("数据库写入失败")
        with self.assertRaisesRegex(RuntimeError, "数据库写入失败"):
            await self.adapter().submit(self.page(button), reject)
        button.click.assert_not_awaited()

    async def test_ambiguous_visible_publish_buttons_block_before_boundary(self):
        first, second = field(), field()
        page = self.page(first)
        page.get_by_role.return_value = controls(first, second)
        callback = MagicMock()
        with self.assertRaisesRegex(PreparationError, "唯一"):
            await self.adapter().submit(page, callback)
        callback.assert_not_called()
        first.click.assert_not_awaited()
        second.click.assert_not_awaited()

    async def test_hidden_and_disabled_buttons_cannot_be_submitted(self):
        hidden, disabled = field(visible=False), field(enabled=False)
        page = self.page(hidden)
        page.get_by_role.return_value = controls(hidden, disabled)
        callback = MagicMock()
        with self.assertRaises(PreparationError):
            await self.adapter().submit(page, callback)
        callback.assert_not_called()

    async def test_title_maxlength_does_not_silently_truncate(self):
        title = field()
        title.get_attribute.return_value = "3"
        page = MagicMock()
        page.locator.return_value = controls(title)
        with self.assertRaisesRegex(PreparationError, "最多 3"):
            await self.adapter().fill_title(page)
        title.fill.assert_not_awaited()

    async def test_title_readback_mismatch_blocks_preparation(self):
        page = MagicMock()
        page.locator.return_value = controls(field("被平台截断"))
        with self.assertRaisesRegex(PreparationError, "标题读回"):
            await self.adapter().verify_title(page)

    async def test_stale_cover_image_does_not_prove_new_upload(self):
        adapter = create_native_adapter(dict(platform="bilibili", title="测试文章"), Path("/tmp/new.png"))
        adapter._cover_before = {"https://i0.hdslb.com/bfs/article/old.png"}
        adapter._cover_images = AsyncMock(return_value=[dict(src="https://i0.hdslb.com/bfs/article/old.png", ready=True)])
        with self.assertRaisesRegex(PreparationError, "新封面"):
            await adapter.verify_options(MagicMock(), MagicMock())

    async def test_plain_hash_words_do_not_count_as_bilibili_native_topic(self):
        adapter = self.adapter(tags=["测试话题"])
        editor = MagicMock()
        editor.inner_text = AsyncMock(return_value="#测试话题#")
        editor.locator.return_value.evaluate_all = AsyncMock(return_value=[])
        with self.assertRaisesRegex(PreparationError, "原生标签"):
            await adapter.verify_options(MagicMock(), editor)

    async def test_unknown_option_is_not_silently_ignored(self):
        with self.assertRaisesRegex(PreparationError, "不支持的原生文章选项"):
            await self.adapter(options={"scheduled_at": "2027-01-01"}).apply_options(MagicMock(), MagicMock())

    async def test_unsupported_native_topic_is_actionable(self):
        with self.assertRaisesRegex(PreparationError, "移除话题"):
            await self.adapter("weibo", tags=["测试话题"]).apply_options(MagicMock(), MagicMock())

    async def test_douyin_candidate_name_does_not_count_as_selected_native_topic(self):
        adapter = self.adapter("douyin", tags=["测试话题"])
        page = MagicMock()
        page.locator.return_value.all_text_contents = AsyncMock(return_value=[])
        # 页面或正文可以出现同名话题，但没有官方已选 chip 时必须失败。
        page.inner_text = AsyncMock(return_value="测试话题 #测试话题#")
        with self.assertRaisesRegex(PreparationError, "已选原生话题"):
            await adapter.verify_options(page, MagicMock())

    async def test_qiehao_required_declaration_blocks_before_cover_or_submission(self):
        adapter = self.adapter("qiehao")
        page = MagicMock()
        page.get_by_role.return_value = controls(field())
        adapter._upload_cover = AsyncMock()
        with self.assertRaisesRegex(PreparationError, "需要设置内容自主声明"):
            await adapter.apply_options(page, MagicMock())
        adapter._upload_cover.assert_not_awaited()
        self.assertFalse(adapter._submit_started)

    async def test_async_submit_boundary_is_awaited_before_click(self):
        events = []
        button = field()
        async def boundary():
            events.append("已持久化")
        async def click(**kwargs):
            events.append("已点击")
        button.click.side_effect = click
        await self.adapter().submit(self.page(button), boundary)
        self.assertEqual(events, ["已持久化", "已点击"])

    def test_unknown_platform_cannot_fall_back_to_other_native_format(self):
        with self.assertRaisesRegex(PreparationError, "不支持的原生文章平台"):
            self.adapter("unknown")

    def test_explicit_dispatch_returns_distinct_article_entrypoints(self):
        urls = {self.adapter(platform).editor_url for platform in ("douyin", "bilibili", "weibo", "qiehao")}
        self.assertEqual(len(urls), 4)
        self.assertIn("https://creator.douyin.com/creator-micro/content/post/article", urls)
        self.assertNotIn("https://creator.douyin.com/creator-micro/content/upload", urls)


class DouyinCreateReceiptTests(unittest.IsolatedAsyncioTestCase):
    """被动回执须来自本次原生文章创建，解析未结束不能先宣称成功。"""

    def response(self, *, code=0, item_id="1234567890123456789", media_type=43,
                 url="https://creator.douyin.com/web/api/media/aweme/create_v2/?read_aid=2906",
                 method="POST", status=200):
        """构造平台响应与所属请求，避免用任意 HTTP 成功替代文章回执。"""
        response = MagicMock()
        response.url, response.status = url, status
        response.request.method = method
        response.request.post_data_json = {"item": {"common": {"media_type": media_type}}}
        response.json = AsyncMock(return_value={"status_code": code, "item_id": item_id})
        return response

    def fixture(self, response=None):
        """只在模拟点击后广播响应，不发请求、不登录平台。"""
        events, listeners = [], {}
        adapter = create_native_adapter(dict(platform="douyin", title="测试文章"))
        page, button = MagicMock(), field()
        page.get_by_role.return_value = controls(button)
        def on(event, callback):
            events.append("安装监听")
            listeners[event] = callback
        async def click(**kwargs):
            events.append("发布点击")
            if response is not None:
                listeners["response"](response)
        page.on.side_effect = on
        button.click.side_effect = click
        return adapter, page, button, events, listeners

    async def test_listener_precedes_boundary_and_pending_receipt_is_awaited(self):
        response = self.response()
        reading, readable = asyncio.Event(), asyncio.Event()
        async def read_json():
            reading.set()
            await readable.wait()
            return {"status_code": 0, "item_id": "1234567890123456789"}
        response.json.side_effect = read_json
        adapter, page, button, events, listeners = self.fixture(response)
        await adapter.submit(page, lambda: events.append("持久化"))
        operation = asyncio.create_task(adapter.read_result(page))
        try:
            await reading.wait()
            self.assertFalse(operation.done())
            readable.set()
            result = await operation
        finally:
            if not operation.done():
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
        self.assertEqual(events, ["安装监听", "持久化", "发布点击"])
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["platform_id"], "1234567890123456789")
        self.assertNotIn("platform_url", result)
        button.click.assert_awaited_once()
        with self.assertRaisesRegex(PreparationError, "已经尝试"):
            await adapter.submit(page, MagicMock())
        page.on.assert_called_once()
        button.click.assert_awaited_once()

    async def test_boundary_failure_removes_listener_without_clicking(self):
        response = self.response()
        adapter, page, button, events, listeners = self.fixture(response)
        def boundary():
            listeners["response"](response)
            raise RuntimeError("持久化失败")
        with self.assertRaisesRegex(RuntimeError, "持久化失败"):
            await adapter.submit(page, boundary)
        button.click.assert_not_awaited()
        response.json.assert_not_awaited()
        page.remove_listener.assert_called_once_with("response", listeners["response"])

    async def test_other_hosts_methods_paths_and_media_cannot_supply_article_receipt(self):
        variants = [
            {"url": "https://other.example/web/api/media/aweme/create_v2/"},
            {"url": "https://creator.douyin.com/web/api/media/aweme/create_v2/extra"},
            {"url": "https://creator.douyin.com/web/api/media/aweme/update_v2/"},
            {"method": "GET"}, {"media_type": 4}, {"media_type": "43"},
        ]
        for values in variants:
            with self.subTest(values=values):
                response = self.response(**values)
                adapter, page, button, events, listeners = self.fixture(response)
                await adapter.submit(page, MagicMock())
                with patch("utils.articles.native.read_result_evidence", new=AsyncMock(
                        return_value={"status": "unknown"})) as fallback:
                    self.assertEqual((await adapter.read_result(page))["status"], "unknown")
                    fallback.assert_awaited_once()
                response.json.assert_not_awaited()

    async def test_unknown_codes_invalid_ids_and_http_errors_fall_back_to_dom(self):
        variants = [
            {"code": 514}, {"code": 515}, {"code": "0"}, {"code": False},
            {"code": 1}, {"item_id": ""}, {"item_id": "0"}, {"item_id": "123x"},
            {"item_id": 1234567890123456789}, {"status": 500},
        ]
        for values in variants:
            with self.subTest(values=values):
                response = self.response(**values)
                adapter, page, button, events, listeners = self.fixture(response)
                await adapter.submit(page, MagicMock())
                with patch("utils.articles.native.read_result_evidence", new=AsyncMock(
                        return_value={"status": "unknown"})) as fallback:
                    result = await adapter.read_result(page)
                    self.assertEqual(result["status"], "unknown")
                    self.assertNotIn("platform_id", result)
                    fallback.assert_awaited_once()
                button.click.assert_awaited_once()

    async def test_response_parse_failure_does_not_fabricate_success(self):
        response = self.response()
        response.json.side_effect = ValueError("不是 JSON")
        adapter, page, button, events, listeners = self.fixture(response)
        await adapter.submit(page, MagicMock())
        with patch("utils.articles.native.read_result_evidence", new=AsyncMock(
                return_value={"status": "unknown"})):
            self.assertEqual((await adapter.read_result(page))["status"], "unknown")
        button.click.assert_awaited_once()


class DouyinCoverReadinessTests(unittest.IsolatedAsyncioTestCase):
    """真实分辨率先出现时，裁剪生成层仍须就绪才能保存封面。"""

    def fixture(self, *, notices=None):
        """独立模拟文件选择、生成图与保存回执，避免把输入图当作生成图。"""
        adapter = create_native_adapter(dict(platform="douyin", title="测试文章"), Path("/tmp/cover.png"))
        adapter._wait_cover_changed = AsyncMock()
        opener, complete_button = field(), field()
        complete = controls(complete_button)
        complete.wait_for = AsyncMock()
        complete.is_visible = AsyncMock(return_value=bool(notices))
        resolution = MagicMock()
        resolution.wait_for = AsyncMock()
        chooser = MagicMock()
        chooser.set_files = AsyncMock()
        pending = MagicMock()
        pending.value = asyncio.get_running_loop().create_future()
        pending.value.set_result(chooser)
        chooser_context = MagicMock()
        chooser_context.__aenter__ = AsyncMock(return_value=pending)
        chooser_context.__aexit__ = AsyncMock(return_value=False)
        page = MagicMock()
        page.expect_file_chooser.return_value = chooser_context
        page.get_by_text.side_effect = lambda text, **kwargs: (
            controls(opener) if isinstance(text, str) else resolution)
        page.get_by_role.return_value = complete
        page.wait_for_function = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        page.locator.return_value.all_text_contents = AsyncMock(return_value=notices or [])
        return adapter, page, complete_button, resolution, chooser

    async def test_completion_waits_for_generated_layers_and_clicks_only_once(self):
        adapter, page, button, resolution, chooser = self.fixture()
        waiting, ready = asyncio.Event(), asyncio.Event()
        async def wait_for_generated_layers(*args, **kwargs):
            waiting.set()
            await ready.wait()
        page.wait_for_function.side_effect = wait_for_generated_layers
        operation = asyncio.create_task(adapter._upload_cover(page))
        try:
            await waiting.wait()
            # 输入图元数据已就绪，生成背景与文字图仍被控制门阻塞。
            resolution.wait_for.assert_awaited_once()
            chooser.set_files.assert_awaited_once_with("/tmp/cover.png")
            button.click.assert_not_awaited()
            adapter._wait_cover_changed.assert_not_awaited()
            self.assertFalse(operation.done())
            ready.set()
            await operation
        finally:
            if not operation.done():
                operation.cancel()
                await asyncio.gather(operation, return_exceptions=True)
        button.click.assert_awaited_once()
        adapter._wait_cover_changed.assert_awaited_once_with(page)

    async def test_generated_layers_timeout_never_clicks_completion(self):
        adapter, page, button, resolution, chooser = self.fixture()
        page.wait_for_function.side_effect = TimeoutError("生成封面图超时")
        with self.assertRaisesRegex(TimeoutError, "生成封面图超时"):
            await adapter._upload_cover(page)
        resolution.wait_for.assert_awaited_once()
        button.click.assert_not_awaited()
        adapter._wait_cover_changed.assert_not_awaited()

    async def test_upload_failure_toast_is_preparation_error_not_success(self):
        adapter, page, button, resolution, chooser = self.fixture(
            notices=["封面上传失败，请稍后重试"])
        with self.assertRaisesRegex(PreparationError, "抖音提示封面上传失败"):
            await adapter._upload_cover(page)
        page.wait_for_function.assert_awaited_once()
        button.click.assert_awaited_once()
        # 明确失败不能继续拿旧平台封面当成功证据，也不能再次点击完成。
        adapter._wait_cover_changed.assert_not_awaited()
        page.wait_for_timeout.assert_not_awaited()
        self.assertFalse(adapter._submit_started)


class WeiboMultiStepTests(unittest.IsolatedAsyncioTestCase):
    """微博文章下一步与最终短微博发布必须分别验证，不能循环点击。"""

    def adapter(self, **options):
        return create_native_adapter(dict(platform="weibo", title="测试文章", options=options))

    def fixture(self, *, value="测试文案", dialogs=1):
        events = []
        next_button, publish, text = field(), field(), field(value)
        async def next_click(**kwargs):
            events.append("下一步")
        async def final_click(**kwargs):
            events.append("最终发布")
        next_button.click.side_effect = next_click
        publish.click.side_effect = final_click
        dialog = field()
        dialog.get_by_role.side_effect = lambda role, **kwargs: controls(text if role == "textbox" else publish)
        page = MagicMock()
        page.wait_for_timeout = AsyncMock()
        page.get_by_role.return_value = controls(next_button)
        page.locator.return_value = controls(*([dialog] if dialogs else []))
        return page, next_button, publish, text, events

    async def test_multistep_marks_once_and_verifies_short_post_before_final_click(self):
        page, next_button, publish, text, events = self.fixture()
        await self.adapter(publish_text="测试文案").submit(page, lambda: events.append("持久化"))
        self.assertEqual(events, ["持久化", "下一步", "最终发布"])
        text.fill.assert_awaited_once_with("测试文案")
        next_button.click.assert_awaited_once()
        publish.click.assert_awaited_once()

    async def test_empty_short_post_uses_title_and_verifies_it_before_publication(self):
        page, next_button, publish, text, events = self.fixture(value="测试文章")
        await self.adapter(publish_text="").submit(page, lambda: events.append("持久化"))
        text.fill.assert_awaited_once_with("测试文章")
        self.assertEqual(events, ["持久化", "下一步", "最终发布"])

    async def test_missing_dialog_never_falls_back_to_page_publish_button(self):
        page, next_button, publish, text, events = self.fixture(dialogs=0)
        with self.assertRaisesRegex(PreparationError, "最终发布窗口"):
            await self.adapter().submit(page, lambda: events.append("持久化"))
        self.assertEqual(events, ["持久化", "下一步"])
        publish.click.assert_not_awaited()
        self.assertEqual(page.get_by_role.call_count, 1)

    async def test_short_post_readback_failure_blocks_final_submission(self):
        page, next_button, publish, text, events = self.fixture(value="原有短微博")
        with self.assertRaisesRegex(PreparationError, "发布文案读回"):
            await self.adapter(publish_text="测试文案").submit(page, lambda: events.append("持久化"))
        publish.click.assert_not_awaited()

    async def test_next_step_click_failure_never_retries_or_clicks_final_publish(self):
        page, next_button, publish, text, events = self.fixture()
        next_button.click.side_effect = RuntimeError("下一步超时")
        adapter = self.adapter()
        with self.assertRaisesRegex(RuntimeError, "超时"):
            await adapter.submit(page, lambda: events.append("持久化"))
        page.get_by_role.return_value = controls(next_button)
        with self.assertRaisesRegex(PreparationError, "已经尝试"):
            await adapter.submit(page, lambda: events.append("重复持久化"))
        self.assertEqual(events, ["持久化"])
        next_button.click.assert_awaited_once()
        publish.click.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

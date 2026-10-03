"""京东创作者平台的原生图文笔记，不复用文章或视频发布入口。

控件及协议依据（官方公开静态资源，2026-10-03 读取；未登录账号验收）：
https://storage.360buyimg.com/ifloors/talent-platform-new/1790145277602/assets/
  index-CfC4YrbB.js：/n/publish-graphic.html、图文表单及发布/草稿接口；
  index-DkYQO5-I.js：标题、自动首图封面、商品链接导入；
  index-D0qBDxJW.js：关联商品及已选商品组件；
  main-Buzi2ykr.js：UploadImage 的服务端图片地址与本地缩略图模型。
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from utils.articles.browser import PreparationError, is_uploaded_image, has_visible_challenge
from utils.articles.native import _unique
from utils.articles.notes import NoteAdapter, prepare_note_document


# 仅投影官方组件的公开业务字段；只读，不调用 React 回调、不修改应用状态。
# 官方 FileItem 的 DOM src 优先使用 blobImg，上传完成以同一组件的 file.img 为准。
_ALBUM_STATE = """elements => elements.map(el => {
    let fiber = el[Object.keys(el).find(key => key.startsWith('__reactFiber$'))];
    let file = null;
    for (let depth = 0; fiber && depth < 8; depth++, fiber = fiber.return) {
        if (fiber.memoizedProps?.file) { file = fiber.memoizedProps.file; break; }
    }
    const img = el.querySelector('img');
    const src = file?.img || '';
    return {src: src.startsWith('//') ? location.protocol + src : src, ready: !!file && !file.error &&
        !el.querySelector('.upload-status') && !!img?.complete && img.naturalWidth > 0};
})"""
_SKU_STATE = """elements => elements.map(el => {
    let fiber = el[Object.keys(el).find(key => key.startsWith('__reactFiber$'))];
    for (let depth = 0; fiber && depth < 8; depth++, fiber = fiber.return) {
        const props = fiber.memoizedProps;
        const item = props?.itemInfo || props?.item;
        if (item) return {sku: String(item.skuId || item.sku || ''),
            valid: item.isValid !== -1 && item.isValid !== 0 && item.enableAddSku !== 0};
    }
    return {sku: '', valid: false};
})"""
_FEEDBACK = '[data-component-name="Message"],[role="alert"]'
_FEEDBACK_TEXT = """elements => elements.filter(el => {
    if (el.closest('[contenteditable],textarea,.ProseMirror')) return false;
    const rect = el.getBoundingClientRect(), style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
}).map(el => (el.innerText || '').trim())"""


def parse_product_links(value) -> list[str]:
    """只允许明确的京东 SKU 或 PC 商品链接，不取短链、任意站点尾号。"""
    if value in (None, ""):
        return []
    if not isinstance(value, str):
        raise PreparationError("京东商品链接须为文本，每行一个京东商品链接或 SKU")
    ids = []
    for token in re.split(r"[\s,，]+", value.strip()):
        if not token:
            continue
        if re.fullmatch(r"[1-9][0-9]*", token):
            sku = token
        else:
            parsed = urlparse(token)
            matched = re.fullmatch(r"/([1-9][0-9]*)\.html", parsed.path)
            if parsed.scheme != "https" or parsed.netloc != "item.jd.com" or not matched:
                raise PreparationError("京东商品须为 SKU 或 https://item.jd.com/商品编号.html 链接")
            sku = matched.group(1)
        if sku not in ids:
            ids.append(sku)
    if len(ids) > 10:
        raise PreparationError("京东图文最多关联 10 个商品，账号实际额度以平台为准")
    return ids


class JDNoteAdapter(NoteAdapter):
    platform, label = "jd", "京东"
    editor_url = "https://dr.jd.com/n/publish-graphic.html"
    title_selector = 'input#title'
    editor_selector = 'textarea#description'

    def _validate_options(self):
        unsupported = [key for key, value in self.options.items()
                       if key not in {"flatten_content", "product_links"} and value not in (None, "", False)]
        if unsupported:
            raise PreparationError("京东图文不支持的选项：" + "、".join(unsupported))
        self.product_ids = parse_product_links(self.options.get("product_links"))

    async def _scope(self, page):
        return await _unique(page.locator('.dr-publish-graphic-wrapper'), "京东原生图文表单")

    async def _open_note(self, page):
        await super()._open_note(page)
        parsed = urlparse(page.url)
        if parsed.scheme != "https" or parsed.netloc != "dr.jd.com" or parsed.path != "/n/publish-graphic.html":
            raise PreparationError("未进入京东原生图文入口，请重新登录创作者账号并检查图文权限")
        if any(key in parse_qs(parsed.query) for key in ("id", "contentId", "selectSku")):
            raise PreparationError("京东打开了已有内容或预设商品页面，已停止以防覆盖或误关联")
        try:
            await page.locator('.dr-publish-graphic-wrapper').wait_for(state="visible", timeout=20000)
            await page.wait_for_function("Boolean(window._gdata?.user?.id && window._gdata?.user?.pin)", timeout=15000)
        except Exception as exc:
            raise PreparationError("未确认京东创作者登录及图文权限，请在账号管理中重新登录") from exc
        scope = await self._scope(page)
        if re.search(r"\bcreate-banned\b", await scope.get_attribute("class") or ""):
            raise PreparationError("京东当前账号被限制创作，请先在平台处理账号提示")

    async def _album_images(self, scope):
        return await scope.locator('.dr-upload-image-component .file-item:not(.btn-upload)').evaluate_all(_ALBUM_STATE)

    async def _upload_one(self, page, scope, path):
        if not await scope.locator('.dr-upload-image-component .file-item:not(.btn-upload)').count():
            locator = scope.locator('[data-spm-click="onClickLeftSelectFile"]')
        else:
            locator = scope.locator('.dr-upload-image-component .btn-upload')
        opener = await _unique(locator, "京东图文图片上传入口", enabled=True)
        async with page.expect_file_chooser(timeout=10000) as pending:
            await opener.click(timeout=10000)
        chooser = await pending.value
        await chooser.set_files(str(path))

    async def fill_title(self, page):
        field = await self._title_field(page)
        placeholder = await field.get_attribute("placeholder") or ""
        limits = re.search(r"(\d+)\s*[~～]\s*(\d+)\s*个字", placeholder)
        if limits and not int(limits[1]) <= len(self.title) <= int(limits[2]):
            raise PreparationError(f"京东当前图文标题须为 {limits[1]}～{limits[2]} 字，已阻止截断")
        await super().fill_title(page)

    async def _cover_images(self, scope):
        return await scope.locator('.dr-cover-edit-wrapper img.cover-image').evaluate_all("""images => images.map(img => ({
            src: img.currentSrc || img.src, ready: img.complete && img.naturalWidth > 0}))""")

    async def _wait_generated_cover(self, page, scope):
        for _ in range(30):
            images = await self._cover_images(scope)
            if (len(images) == 1 and images[0]['src'] not in self._cover_before
                    and is_uploaded_image(images[0], self.platform)):
                return
            await page.wait_for_timeout(500)
        raise PreparationError("京东首图封面尚未生成或上传完成，已阻止发布")

    async def _selected_products(self, scope):
        return await scope.locator('.publish-related-info-wrapper .goods-area').evaluate_all(_SKU_STATE)

    async def _apply_products(self, page, scope):
        if not self.product_ids:
            return
        if await self._selected_products(scope):
            raise PreparationError("京东表单已有关联商品，请清空后重试，避免关联错误商品")
        add = await _unique(scope.locator('[data-spm-click="publishGoodsAddGood"]'), "京东关联商品入口")
        await add.click(timeout=10000)
        dialogs = page.get_by_role('dialog').filter(has_text='关联商品')
        await dialogs.first.wait_for(state='visible', timeout=15000)
        drawer = await _unique(dialogs, "京东关联商品窗口")
        tab = await _unique(drawer.get_by_role('tab', name='链接导入', exact=True), "京东商品链接导入页签")
        await tab.click(timeout=10000)
        paste = await _unique(drawer.locator('.paste-search-input-content'), "京东商品链接粘贴区")
        links = '\n'.join(f'https://item.jd.com/{sku}.html' for sku in self.product_ids)
        # 触发官方 onPaste 业务路径，不修改 DOM 或调用私有接口。
        await paste.evaluate("""(el, text) => {
            const transfer = new DataTransfer(); transfer.setData('text', text);
            el.dispatchEvent(new ClipboardEvent('paste', {bubbles: true, clipboardData: transfer}));
        }""", links)
        query = await _unique(drawer.locator('[data-spm-click="publishVideoPasteSearchTrigger"]'),
                              "京东商品查询按钮", enabled=True)
        await query.click(timeout=10000)
        for sku in self.product_ids:
            chosen = None
            for _ in range(30):
                cards = drawer.locator('.search-add-goods-container .goods-card')
                states = await cards.evaluate_all(_SKU_STATE)
                matching = [index for index, state in enumerate(states) if state['sku'] == sku and state['valid']]
                if len(matching) == 1:
                    chosen = cards.nth(matching[0])
                    break
                if len(matching) > 1:
                    raise PreparationError("京东商品候选存在重复，已停止自动关联")
                await page.wait_for_timeout(500)
            if chosen is None:
                raise PreparationError(f"京东商品 {sku} 不可关联或查询未完成，请检查商品准入资格")
            checkbox = await _unique(chosen.get_by_role('checkbox'), "京东精确商品选框", enabled=True)
            if not await checkbox.is_checked():
                # 官方点击会先查询商品准入再更新 checked；只点一次并等待读回。
                await checkbox.click(timeout=10000)
            for _ in range(30):
                if await checkbox.is_checked():
                    break
                await page.wait_for_timeout(500)
            else:
                raise PreparationError("京东商品没有成为已选状态，已阻止发布")
        # 此选项会修改商品库；无需它来发表图文，不默认替用户添加。
        also_save = drawer.get_by_label('同时加入我的商品', exact=True)
        if await also_save.count():
            await (await _unique(also_save, "京东同时加入商品库选项")).uncheck()
        confirm = await _unique(drawer.locator('[data-spm-click="publishVideoNewGoodsSelectionAdd"]'),
                                "京东关联商品确认", enabled=True)
        await confirm.click(timeout=10000)
        await drawer.wait_for(state='hidden', timeout=10000)
        for _ in range(20):
            selected = await self._selected_products(scope)
            if [item['sku'] for item in selected] == self.product_ids and all(item['valid'] for item in selected):
                return
            await page.wait_for_timeout(500)
        raise PreparationError("京东关联商品读回不一致，已阻止发布")

    async def prepare_note(self, page, assets):
        self._validate_options()
        document = prepare_note_document(self.snapshot, assets)
        if self.cover and document.image_paths[0] != self.cover:
            raise PreparationError("京东以相册首图生成封面，请将选定封面放在正文首图位置后重试")
        await self._open_note(page)
        scope = await self._scope(page)
        await self._install_preview_guard(page)
        if await self._album_images(scope) or await self._selected_products(scope):
            raise PreparationError("京东页面存在旧图文或关联商品，请先清空后重试")
        self._cover_before = {item['src'] for item in await self._cover_images(scope)}
        for index, path in enumerate(document.image_paths):
            await self._upload_one(page, scope, path)
            await self._wait_uploaded(page, scope, document, index)
        editor = await self._body_editor(scope)
        limit = await editor.get_attribute('maxlength')
        if limit and limit.isdigit() and int(limit) > 0 and len(document.expected_text) > int(limit):
            raise PreparationError(f"京东当前图文正文最多 {limit} 字，已阻止截断")
        await editor.fill(document.expected_text)
        await self.fill_title(scope)
        await self._apply_products(page, scope)
        await self._wait_generated_cover(page, scope)
        self._note_scope, self._note_editor, self._note_document = scope, editor, document
        await self.verify_note(page)
        return editor, document

    async def verify_note(self, page):
        await super().verify_note(page)
        scope = self._note_scope
        selected = await self._selected_products(scope)
        if [item['sku'] for item in selected] != self.product_ids or not all(item['valid'] for item in selected):
            raise PreparationError("京东关联商品数量、顺序或准入状态改变，已阻止发布")
        if not self.product_ids and await scope.locator('label[for="relatedInfo"][class*="required"]').count():
            raise PreparationError("京东当前频道要求关联商品，请填写京东商品链接后重试")
        covers = await self._cover_images(scope)
        if (len(covers) != 1 or covers[0]['src'] in self._cover_before
                or not is_uploaded_image(covers[0], self.platform)):
            raise PreparationError("京东图文封面未完成平台上传，已阻止发布")
        errors = await scope.locator('[role="alert"],[class*="form-item-explain-error"]').all_text_contents()
        errors = [item.strip() for item in errors if item.strip()]
        if errors:
            raise PreparationError("京东表单仍需处理：" + '；'.join(errors))

    async def submit(self, page, on_submit):
        if self.snapshot.get('mode') == 'preview':
            raise PreparationError("京东图文预览任务禁止发布")
        if self._submit_started:
            raise PreparationError("本任务已经尝试提交，请核对京东内容记录，勿重复发布")
        if not getattr(self, '_note_document', None):
            raise PreparationError("京东图文尚未完成准备，已阻止提交")
        await self.verify_note(page)
        button = await _unique(self._note_scope.locator('button[data-spm="onFormValidateByPublish"]'),
                               "京东图文正式发布按钮", enabled=True)
        if (await button.inner_text()).strip() != '发布':
            raise PreparationError("京东正式发布控件名称发生变化，请人工处理")
        await button.scroll_into_view_if_needed()
        self._feedback_before = set(await self._feedback_texts(page))
        await self._mark_submit(on_submit)
        await button.click(timeout=10000)

    async def _feedback_texts(self, page):
        return await page.locator(_FEEDBACK).evaluate_all(_FEEDBACK_TEXT)

    async def read_result(self, page):
        texts = await self._feedback_texts(page)
        if await has_visible_challenge(page, texts):
            return {'status': 'needs_action', 'message': '京东要求安全验证，请核对内容记录后在平台处理'}
        if not self._submit_started:
            return {'status': 'unknown', 'message': '京东尚未正式提交，保存草稿不表示发布成功'}
        for text in texts:
            if text in getattr(self, "_feedback_before", set()):
                continue
            if re.match(r'^(?:图文)?(?:发布失败|提交失败|审核不通过)(?=[。！!，,；;：:\n]|$)', text):
                return {'status': 'failed', 'message': '京东反馈：' + text}
            if re.match(r'^(?:图文)?(?:发布成功|提交成功|等待审核|审核中)(?=[。！!，,；;：:\n]|$)', text):
                return {'status': 'submitted', 'message': '京东已确认提交：' + text, 'platform_status': text}
        return {'status': 'unknown', 'message': '已尝试提交京东图文，尚无明确发布回执；草稿保存或列表跳转不算发布，请勿重复提交'}

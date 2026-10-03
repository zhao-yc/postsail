"""社区平台的原生文章编辑器（未完成真实账号验收）。

可复查的入口和编辑器依据：
* https://github.com/leaper-one/MultiPost-Extension/tree/main/src/sync/article
  xueqiu.ts 的标题、ProseMirror 和封面裁剪；douban.ts 的日记预览入口。
* https://github.com/RyanYipeng/SyncCaster/tree/main/packages/adapters/src
  csdn.ts 的富文本入口与标题；jianshu.ts 的 kalamu/CodeMirror 和新建文章。
* https://github.com/wechatsync/Wechatsync 的豆瓣、雪球与简书适配器。

这些是开源实现证据，不是本站实测。AcFun 和各平台的可选控件使用运行时
语义检测：入口域名/路径、唯一可见控件、完整正文/选项读回缺一不可。
不使用未核实的私有发布接口，也不把草稿或打开确认窗口当作发布成功。
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from utils.articles.browser import PreparationError, is_uploaded_image
from utils.articles.native import NativeArticleAdapter, _unique, _value


def _names(*names):
    return re.compile("^(?:" + "|".join(re.escape(name) for name in names) + ")$")


def _actions(scope, *names):
    """只接受具有交互角色且名称完整匹配的原生控件。"""
    pattern = _names(*names)
    return scope.get_by_role("button", name=pattern).or_(scope.get_by_role("link", name=pattern))


async def _visible(locator):
    return [locator.nth(index) for index in range(await locator.count())
            if await locator.nth(index).is_visible()]


class CommunityArticleAdapter(NativeArticleAdapter):
    """共享唯一控件、草稿保护与选项核验；各平台仍限定独立文章入口。"""

    routes: tuple[tuple[str, str], ...] = ()
    editor_frames = ('.edui-editor-iframeholder iframe, iframe.tox-edit-area__iframe, '
                     'iframe.cke_wysiwyg_frame')
    cover_regions = ('.article-cover, .cover-container, .cover-wrapper, .cover-upload, '
                     '[data-field="cover"], [role="group"][aria-label="封面"], '
                     '[role="group"][aria-label="文章封面"]')
    tag_selector = 'input[name="tags"], input[name="author_tags"]'
    allowed_options = {"summary", "category", "statement"}
    publish_names = ("发布",)
    confirmation_names = ("确认发布", "确定发布", "发布文章", "发布日记")
    allow_default_title = False

    def _check_url(self, page):
        parsed = urlparse(page.url)
        if (parsed.scheme != "https" or parsed.username or parsed.password or
                parsed.port not in (None, 443) or not any(
                    parsed.hostname == host and re.fullmatch(path, parsed.path)
                    for host, path in self.routes)):
            raise PreparationError(f"当前页面不是{self.label}文章编辑器，请检查登录状态或文章权限")

    async def _editor_candidates(self, page):
        candidates = await _visible(page.locator(self.editor_selector))
        for frame_element in await _visible(page.locator(self.editor_frames)):
            frame = await (await frame_element.element_handle()).content_frame()
            if frame is not None:
                candidates.extend(await _visible(frame.locator('body[contenteditable="true"]')))
        return candidates

    async def _find_editor(self, page):
        self._check_url(page)
        matches = await self._editor_candidates(page)
        if len(matches) != 1:
            raise PreparationError(f"未找到唯一的{self.label}原生富文本正文；请检查编辑器类型或平台页面变化")
        editor = matches[0]
        if not await editor.evaluate("el => el.isContentEditable"):
            raise PreparationError(f"{self.label}正文不可编辑，已阻止发布")
        return editor

    async def _wait_editor(self, page):
        # 仅等待异步挂载，不重试任何有副作用的操作。
        for _ in range(40):
            self._check_url(page)
            matches = await self._editor_candidates(page)
            if matches:
                return await self._find_editor(page)
            await page.wait_for_timeout(500)
        raise PreparationError(f"未找到{self.label}富文本正文；请在平台检查文章权限或切换富文本编辑器")

    async def _protect_existing_draft(self, editor, page=None):
        if await editor.evaluate("el => !!((el.innerText || '').trim() || el.querySelector('img,video,audio,iframe,table,object,embed,hr,canvas,svg'))"):
            raise PreparationError(f"{self.label}编辑器已有草稿内容，请先保存并新建文章；已避免覆盖现有草稿")
        if page is not None and not self.allow_default_title:
            title = await _value(await self._title_field(page))
            if title.strip():
                raise PreparationError(f"{self.label}编辑器已有草稿标题，请先保存并新建文章；已避免覆盖现有草稿")

    async def _switch_rich_editor(self, page):
        """只点击页面明示的富文本切换；不修改编辑器 DOM 或向 Markdown 填 HTML。"""
        for _ in range(40):
            self._check_url(page)
            if await self._editor_candidates(page):
                return
            switches = _actions(page, "富文本编辑器", "切换为富文本编辑器", "切换富文本编辑器")
            if await _visible(switches):
                await (await _unique(switches, f"{self.label}富文本切换", enabled=True)).click(timeout=10000)
                self._check_url(page)
                return
            await page.wait_for_timeout(500)

    async def open_editor(self, page):
        await page.goto(self.editor_url, timeout=60000, wait_until="domcontentloaded")
        self._check_url(page)
        editor = await self._wait_editor(page)
        await self._protect_existing_draft(editor, page)
        self._body_editor = editor
        return editor

    async def fill_title(self, page):
        self._check_url(page)
        await super().fill_title(page)

    def _option_scope(self, page):
        return page

    async def _text_field(self, page, label, selector=""):
        scope = self._option_scope(page)
        fields = scope.get_by_role("textbox", name=label, exact=True)
        if selector:
            fields = fields.or_(scope.locator(selector))
        return await _unique(fields, f"{self.label}{label}", enabled=True)

    async def _summary_field(self, page):
        return await self._text_field(page, "摘要", self.summary_selector)

    async def _select_named(self, page, label, value, *, verify=False):
        """优先关联标签的 select/radio，拒绝仅显示文字而未选中的候选项。"""
        scope = self._option_scope(page)
        controls = scope.get_by_role("combobox", name=label, exact=True)
        visible = await _visible(controls)
        if visible:
            field = await _unique(controls, f"{self.label}{label}", enabled=True)
            if await field.evaluate("el => el.tagName") != "SELECT":
                raise PreparationError(f"{self.label}{label}不是可核对的原生下拉框，请人工处理")
            if not verify:
                await field.select_option(label=value)
            if await field.locator("option:checked").all_text_contents() != [value]:
                raise PreparationError(f"{self.label}{label}读回不一致，已阻止发布")
            return
        group = await _unique(scope.get_by_role("group", name=label, exact=True), f"{self.label}{label}选项组")
        field = await _unique(group.get_by_role("radio", name=value, exact=True), f"{self.label}{label}选项", enabled=True)
        if not verify:
            await field.check()
        if not await field.is_checked():
            raise PreparationError(f"{self.label}{label}未选中，已阻止发布")

    async def _original(self, page, *, verify=False):
        selected = self.options.get("original")
        if selected is None:
            return
        fields = self._option_scope(page).get_by_role("checkbox", name=_names("声明原创", "申明原创", "原创"))
        field = await _unique(fields, f"{self.label}原创声明", enabled=True)
        if not verify:
            await field.set_checked(selected)
        if await field.is_checked() != selected:
            raise PreparationError(f"{self.label}原创声明读回不一致，已阻止发布")

    async def apply_options(self, page, editor):
        self._check_url(page)
        unknown = [name for name, value in self.options.items()
                   if name not in self.allowed_options and value not in (None, "", False)]
        if unknown:
            raise PreparationError(f"{self.label}不支持文章选项：" + "、".join(unknown))
        if self.options.get("visibility"):
            await self._select_named(page, "可见范围", self.options["visibility"])
        if self.options.get("create_type"):
            await self._select_named(page, "文章类型", self.options["create_type"])
        # 原文链接通常在选择转载/翻译后才挂载。
        for name, label in (("source_url", "原文链接"),):
            if self.options.get(name):
                await (await self._text_field(page, label)).fill(self.options[name])
        await self._original(page)
        # 统一父类仅接收它能核验的参数，平台专属字段在上面应用。
        original = self.options
        self.options = {key: value for key, value in original.items()
                        if key in {"summary", "category", "statement"}}
        try:
            await super().apply_options(page, editor)
        finally:
            self.options = original

    async def verify_options(self, page, editor):
        self._check_url(page)
        if self.options.get("source_url"):
            if await _value(await self._text_field(page, "原文链接")) != self.options["source_url"]:
                raise PreparationError(f"{self.label}原文链接读回不一致，已阻止发布")
        if self.options.get("visibility"):
            await self._select_named(page, "可见范围", self.options["visibility"], verify=True)
        if self.options.get("create_type"):
            await self._select_named(page, "文章类型", self.options["create_type"], verify=True)
        if self.options.get("category"):
            await self._select_named(page, "分类", self.options["category"], verify=True)
        await self._original(page, verify=True)
        original = self.options
        self.options = {name: value for name, value in original.items() if name != "category"}
        try:
            await super().verify_options(page, editor)
        finally:
            self.options = original

    async def _apply_category(self, page):
        await self._select_named(page, "分类", self.options["category"])

    async def _apply_statement(self, page):
        field = await _unique(self._option_scope(page).get_by_label(self.options["statement"], exact=True),
                              f"{self.label}声明", enabled=True)
        await field.check()

    async def _apply_tags(self, page, editor):
        field = await self._text_field(page, "标签", self.tag_selector)
        # 文本型关键词与可交互 chips 不混为一谈；只有原生字段完整读回才继续。
        await field.fill(" ".join(self.tags))
        await self._verify_tags(page, editor)

    async def _verify_tags(self, page, editor):
        field = await self._text_field(page, "标签", self.tag_selector)
        actual = [tag for tag in re.split(r"[\s,，]+", await _value(field)) if tag]
        if actual != self.tags:
            raise PreparationError(f"{self.label}标签读回不一致，已阻止发布")

    async def _cover_region(self, page):
        # 去掉嵌套同义包装，只留下一个封面区；不把正文图片作为封面。
        parts = self.cover_regions
        selector = f":is({parts}):not(:is({parts}) :is({parts}))"
        return await _unique(self._option_scope(page).locator(selector), f"{self.label}封面区域")

    async def _cover_images(self, page):
        region = await self._cover_region(page)
        return await region.locator("img").evaluate_all("""images => images.map(img => ({
            src: img.src || '', ready: img.complete && img.naturalWidth > 0}))""")

    async def _upload_cover(self, page):
        region = await self._cover_region(page)
        fields = region.locator('input[type="file"]')
        if not await fields.count():
            opener = await _unique(_actions(region, "上传封面", "添加封面", "设置封面", "选择封面"),
                                   f"{self.label}上传封面入口", enabled=True)
            async with page.expect_file_chooser(timeout=10000) as pending:
                await opener.click(timeout=10000)
            await (await pending.value).set_files(str(self.cover))
        else:
            field = await _unique(fields, f"{self.label}封面文件字段", visible=False)
            await field.set_input_files(str(self.cover))
        # 裁剪只处理显式图片裁剪窗口，文章发布确认绝不在此处点击。
        for _ in range(30):
            images = await self._cover_images(page)
            if any(is_uploaded_image(item, self.platform) and item["src"] not in self._cover_before for item in images):
                return
            dialogs = page.get_by_role("dialog").filter(has_text=re.compile("裁剪|剪裁"))
            if await _visible(dialogs):
                dialog = await _unique(dialogs, f"{self.label}封面裁剪窗口")
                await (await _unique(_actions(dialog, "确认裁剪", "完成", "确定"),
                                    f"{self.label}封面裁剪确认", enabled=True)).click(timeout=10000)
                await self._wait_cover_changed(page)
                return
            await page.wait_for_timeout(500)
        raise PreparationError(f"{self.label}封面上传未完成，已阻止发布")

    async def verify_body(self, page, editor, document):
        """保留提交前复核用的正文句柄；不会以填写动作替代实际读回。"""
        from utils.articles.adapter import _verify_final_body
        self._check_url(page)
        await _verify_final_body(editor, document, self.platform, self.tags)
        self._body_editor, self._body_document = editor, document

    async def _recheck_body(self, page):
        document = getattr(self, "_body_document", None)
        if document is not None:
            await self.verify_body(page, self._body_editor, document)

    async def submit(self, page, on_submit):
        self._check_url(page)
        button = await _unique(_actions(self._option_scope(page), *self.publish_names),
                               f"{self.label}文章发布按钮", enabled=True)
        await button.scroll_into_view_if_needed()
        await self._mark_submit(on_submit)
        await button.click(timeout=10000)
        # 某些平台先弹出最终确认。没有明确窗口就交给回执读取，不猜测成功。
        for _ in range(10):
            dialogs = page.get_by_role("dialog").filter(has_text=re.compile("发布|投稿"))
            if await _visible(dialogs):
                dialog = await _unique(dialogs, f"{self.label}文章发布确认窗口")
                confirm = await _unique(_actions(dialog, *self.confirmation_names),
                                        f"{self.label}最终发布确认", enabled=True)
                await confirm.click(timeout=10000)
                return
            await page.wait_for_timeout(200)

    async def read_result(self, page):
        result = await super().read_result(page)
        if self.options.get("visibility") == "仅自己可见" and result.get("status") == "published":
            result = {**result, "status": "submitted", "platform_status": "仅自己可见",
                      "message": "平台已保存仅自己可见的文章，未作为公开文章发布"}
        return result


class AcFunArticleAdapter(CommunityArticleAdapter):
    """从会员中心的真实文章投稿链接导航；不猜测视频投稿入口。"""

    platform, label = "acfun", "AcFun"
    editor_url = "https://www.acfun.cn/member/"
    routes = (("www.acfun.cn", r"/member(?:/.*)?"),)
    title_selector = ('input[placeholder*="文章标题"], textarea[placeholder*="文章标题"], '
                      'input[name="title"], textarea[name="title"], '
                      'input[placeholder="请输入标题"], textarea[placeholder="请输入标题"]')
    editor_selector = ('.ql-editor[contenteditable="true"], .ProseMirror[contenteditable="true"], '
                       '.cke_editable[contenteditable="true"], [contenteditable="true"][aria-label="正文"]')
    summary_selector = 'textarea[name="description"], textarea[placeholder*="摘要"]'
    allowed_options = {"summary", "category", "original", "source_url", "statement"}
    publish_names = ("发布文章", "立即投稿", "投稿", "发布")
    confirmation_names = ("确认发布", "确认投稿", "发布文章", "投稿")

    def _check_article_url(self, page):
        self._check_url(page)
        parsed = urlparse(page.url)
        if not re.search(r"(?:/|^)article(?:[-/]|$)", parsed.path + "/" + parsed.fragment, re.I):
            raise PreparationError("AcFun 当前页面不是文章投稿入口，已阻止写入")

    async def open_editor(self, page):
        await page.goto(self.editor_url, timeout=60000, wait_until="domcontentloaded")
        self._check_url(page)
        links = page.get_by_role("link", name=_names("文章投稿", "发布文章", "投文章"))
        await links.first.wait_for(state="visible", timeout=20000)
        link = await _unique(links, "AcFun 文章投稿入口", enabled=True)
        target = urljoin(page.url, await link.get_attribute("href") or "")
        parsed = urlparse(target)
        if (parsed.scheme != "https" or parsed.hostname != "www.acfun.cn" or
                not parsed.path.startswith("/member/") or
                not re.search(r"article(?:[-/]|$)", parsed.path + "/" + parsed.fragment, re.I)):
            raise PreparationError("AcFun 文章投稿链接发生变化，请人工检查")
        await page.goto(target, timeout=60000, wait_until="domcontentloaded")
        self._check_article_url(page)
        editor = await self._wait_editor(page)
        await self._protect_existing_draft(editor, page)
        self._body_editor = editor
        return editor

    async def apply_options(self, page, editor):
        self._check_article_url(page)
        if not self.options.get("category"):
            raise PreparationError("AcFun 文章需要选择分类，请填写平台显示的完整分类名称")
        await super().apply_options(page, editor)

    async def submit(self, page, on_submit):
        self._check_article_url(page)
        await super().submit(page, on_submit)


class XueqiuArticleAdapter(CommunityArticleAdapter):
    platform, label = "xueqiu", "雪球号"
    editor_url = "https://mp.xueqiu.com/writeV2"
    routes = (("mp.xueqiu.com", r"/(?:writeV2/?|write(?:/draft/[0-9]+)?/?)"),)
    title_selector = 'textarea[placeholder="请输入标题"]'
    editor_selector = 'div.ProseMirror[contenteditable="true"]'
    allowed_options = {"visibility", "statement"}


class DoubanArticleAdapter(CommunityArticleAdapter):
    platform, label = "douban", "豆瓣"
    editor_url = "https://www.douban.com/note/create"
    routes = (("www.douban.com", r"/note/(?:create/?|[0-9]+/edit/?)"),)
    title_selector = 'textarea[placeholder="添加标题"], input[name="note_title"], textarea[name="note_title"]'
    editor_selector = '.public-DraftEditor-content[contenteditable="true"], [contenteditable="true"][data-contents="true"]'
    allowed_options = {"original", "visibility"}
    publish_names = ("发布日记", "发表", "发布")

    async def submit(self, page, on_submit):
        self._check_url(page)
        # 预览链接是公开维护者适配器确认的导航；最终发布另有一次性边界。
        previews = page.locator("a.editor-extra-button-preview")
        if await _visible(previews):
            preview = await _unique(previews, "豆瓣日记预览入口", enabled=True)
            if (await preview.inner_text()).strip() not in {"预览", "预览日记"}:
                raise PreparationError("豆瓣日记预览入口文字变化，请人工核对")
            await preview.click(timeout=10000)
            await page.wait_for_timeout(500)
            self._check_url(page)
        await super().submit(page, on_submit)


class CSDNArticleAdapter(CommunityArticleAdapter):
    platform, label = "csdn", "CSDN"
    editor_url = "https://mp.csdn.net/mp_blog/creation/editor"
    routes = (("mp.csdn.net", r"/mp_blog/creation/editor(?:/[0-9]+)?/?"),
              ("editor.csdn.net", r"/(?:md/?)?"))
    title_selector = ('.article-bar__title input, .article-bar__title textarea, '
                      'input[placeholder*="标题"], textarea[placeholder*="标题"], #txtTitle')
    editor_selector = ('.ProseMirror[contenteditable="true"], .ql-editor[contenteditable="true"], '
                       '.cke_editable[contenteditable="true"], [contenteditable="true"][aria-label="正文"]')
    summary_selector = 'textarea[name="description"], textarea[placeholder*="摘要"]'
    allowed_options = {"summary", "create_type", "source_url", "statement"}
    publish_names = ("发布文章", "确认发布", "发布")
    _guard_pattern = re.compile(r"^https?://(?:[a-zA-Z0-9-]+\.)*csdn\.net(?::[0-9]+)?/.*$", re.I)

    async def open_editor(self, page):
        await page.goto(self.editor_url, timeout=60000, wait_until="domcontentloaded")
        self._check_url(page)
        await self._switch_rich_editor(page)
        editor = await self._wait_editor(page)
        await self._protect_existing_draft(editor, page)
        self._body_editor = editor
        return editor

    def _option_scope(self, page):
        return getattr(self, "_publish_dialog", None) or page

    async def install_preparation_guard(self, page):
        """主流程在导航前安装；发布与预览都先阻止准备阶段的意外正式提交。"""
        if getattr(self, "_settings_guard_active", False):
            return
        self._settings_write_blocked = False
        self._settings_guard_handler = self._guard_settings
        await page.route(self._guard_pattern, self._settings_guard_handler)
        self._settings_guard_active = True

    async def _guard_settings(self, route):
        """打开发布设置时拒绝所有未知写操作；只放过明确草稿和资源上传。"""
        request = route.request
        parsed = urlparse(request.url)
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            await route.fallback()
            return
        if (request.method == "POST" and parsed.hostname == "bizapi.csdn.net" and
                parsed.path == "/resource-api/v1/image/direct/upload/signature"):
            await route.fallback()
            return
        payload = None
        try:
            payload = request.post_data_json
        except Exception:
            pass
        if (parsed.hostname == "bizapi.csdn.net" and parsed.path in {
                "/blog-console-api/v3/mdeditor/saveArticle",
                "/blog-console-api/v3/postedit/saveArticle",
                "/blog-console-api/v1/postedit/saveArticle"} and
                isinstance(payload, dict) and payload.get("status") in (2, "2") and
                payload.get("pubStatus", "draft") == "draft"):
            await route.fallback()
            return
        self._settings_write_blocked = True
        await route.abort("blockedbyclient")

    async def _open_settings(self, page):
        dialogs = page.get_by_role("dialog").filter(has_text=re.compile("文章标签|发布文章|文章类型"))
        await self.install_preparation_guard(page)
        if not await _visible(dialogs):
            button = await _unique(_actions(page, "发布文章"), "CSDN 发布设置入口", enabled=True)
            await button.click(timeout=10000)
            await dialogs.first.wait_for(state="visible", timeout=15000)
        self._publish_dialog = await _unique(dialogs, "CSDN 文章发布设置窗口")
        if getattr(self, "_settings_write_blocked", False):
            raise PreparationError("CSDN 打开设置时尝试了未核实的写请求，已拦截；请人工检查平台变化")

    async def apply_options(self, page, editor):
        self._check_url(page)
        if self.options.get("create_type") in {"转载", "翻译"} and not self.options.get("source_url"):
            raise PreparationError("CSDN 转载或翻译文章需要填写原文链接")
        await self._open_settings(page)
        await super().apply_options(page, editor)

    async def _apply_tags(self, page, editor):
        field = await self._text_field(page, "文章标签", 'input[placeholder*="添加文章标签"], input[placeholder*="输入标签"]')
        for tag in self.tags:
            await field.fill(tag)
            await field.press("Enter")
        await self._verify_tags(page, editor)

    async def _verify_tags(self, page, editor):
        scope = self._option_scope(page)
        group = await _unique(scope.get_by_role("group", name="文章标签", exact=True).or_(
            scope.locator('[data-field="tags"], .article-tags, .tag-list')), "CSDN 已选标签区域")
        # 已选标签需要独立移除控件；输入框值和下拉候选不算提交值。
        selected = await group.locator('[data-tag], .tag, .el-tag').evaluate_all("""nodes => nodes
            .filter(el => el.querySelector('button,[role="button"],.el-tag__close,[aria-label*="删除"]'))
            .map(el => el.getAttribute('data-tag') || Array.from(el.childNodes)
                .filter(node => node.nodeType === Node.TEXT_NODE ||
                    (node.nodeType === Node.ELEMENT_NODE && !node.matches('button,[role="button"],.el-tag__close')))
                .map(node => node.textContent).join('').trim())""")
        if selected != self.tags:
            raise PreparationError("CSDN 已选文章标签读回不一致，已阻止发布")

    async def submit(self, page, on_submit):
        self._check_url(page)
        if not getattr(self, "_publish_dialog", None):
            raise PreparationError("CSDN 发布设置尚未核对，已阻止发布")
        await self.verify_options(page, self._body_editor)
        await self.verify_title(page)
        await self._recheck_body(page)
        button = await _unique(_actions(self._publish_dialog, *self.publish_names), "CSDN 最终发布按钮", enabled=True)
        # 先持久化再撤销本适配器的设置保护；预览任务从不调用这里。
        await self._mark_submit(on_submit)
        if getattr(self, "_settings_guard_active", False):
            await page.unroute(self._guard_pattern, self._settings_guard_handler)
            self._settings_guard_active = False
        await button.click(timeout=10000)


class JianshuArticleAdapter(CommunityArticleAdapter):
    platform, label = "jianshu", "简书"
    editor_url = "https://www.jianshu.com/writer"
    routes = (("www.jianshu.com", r"/writer/?"),)
    title_selector = ('input[name="title"], textarea[name="title"], input[placeholder*="标题"], '
                      'textarea[placeholder*="标题"]')
    editor_selector = '.kalamu-area[contenteditable="true"]'
    allowed_options: set[str] = set()
    allow_default_title = True  # 仅在已经验证新 note ID 后容许平台生成的日期标题。

    @staticmethod
    def _note_id(url):
        parsed = urlparse(url)
        match = re.fullmatch(r"/notebooks/([0-9]+)/notes/([0-9]+)(?:/writing)?/?", parsed.fragment)
        return match.groups() if match else None

    async def open_editor(self, page):
        await page.goto(self.editor_url, timeout=60000, wait_until="domcontentloaded")
        self._check_url(page)
        links = _actions(page, "新建文章", "新建一篇文章")
        await links.first.wait_for(state="visible", timeout=20000)
        before = self._note_id(page.url)
        new = await _unique(links, "简书新建文章入口", enabled=True)
        await new.click(timeout=10000)
        for _ in range(40):
            self._check_url(page)
            current = self._note_id(page.url)
            if current and current != before:
                break
            await page.wait_for_timeout(250)
        else:
            raise PreparationError("简书未确认创建新文章，请先在文集中新建空白稿件；已避免覆盖旧稿")
        self._created_note = current
        await self._switch_rich_editor(page)
        editor = await self._wait_editor(page)
        await self._protect_existing_draft(editor, page)
        self._body_editor = editor
        return editor

    async def _title_field(self, page):
        candidates = page.locator(self.title_selector)
        if not await _visible(candidates):
            # 公开实现确认新版标题位于正文旁边；只接受唯一的原生 text input。
            editor = await self._find_editor(page)
            candidates = editor.locator('xpath=..').locator('input[type="text"]')
        return await _unique(candidates, "简书文章标题", enabled=True)

    async def apply_options(self, page, editor):
        if self.cover:
            raise PreparationError("简书文章不支持独立封面，请将图片放入正文")
        if self.tags:
            raise PreparationError("简书文章没有独立标签参数，请移除标签")
        await super().apply_options(page, editor)

    async def submit(self, page, on_submit):
        if self._note_id(page.url) != getattr(self, "_created_note", None):
            raise PreparationError("简书当前文章与本次新建稿件不一致，已阻止发布")
        await super().submit(page, on_submit)


COMMUNITY_ADAPTERS = {
    "acfun": AcFunArticleAdapter,
    "xueqiu": XueqiuArticleAdapter,
    "douban": DoubanArticleAdapter,
    "csdn": CSDNArticleAdapter,
    "jianshu": JianshuArticleAdapter,
}

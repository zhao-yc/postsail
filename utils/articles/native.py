"""原生文章编辑器适配；控件缺失或读回不一致时停止，绝不改发图片笔记。

核实依据：抖音官方静态脚本中的 /content/post/article 路由；B 站官方
read-editor/assets/index-CEqA4Tr6.js；微博长文官方 PC 教程及公开
baoyu-post-to-weibo/scripts/weibo-article.ts。企鹅号未有登录账号验收，
新 DOM 来自 liuxucai/qq-publish-skill 公开维护者源码；页面不符合时要求人工处理。
企鹅号封面参考官方公开 base_main_2aef9eef.js 的 art-dialog-cover 模板；
创作入口参考 github.com/yjmm10/MediaSync 的 qiehao.ts。
这些依据不能替代真实账号的发布验收。
"""
from __future__ import annotations

import asyncio
import inspect
import re
from pathlib import Path
from urllib.parse import urlparse

from utils.articles.browser import PreparationError, is_uploaded_image, read_result_evidence


async def _unique(locator, label: str, *, enabled: bool = False, visible: bool = True):
    """所有操作先要求唯一控件；不能选第一个相似按钮而误提交。"""
    matches = []
    for index in range(await locator.count()):
        candidate = locator.nth(index)
        if visible and not await candidate.is_visible():
            continue
        if enabled and not await candidate.is_enabled():
            continue
        matches.append(candidate)
    if len(matches) != 1:
        raise PreparationError(f"未找到唯一的{label}；请核对账号权限或平台页面变化")
    return matches[0]


async def _value(field) -> str:
    """读取原生表单值或富文本字段，避免仅看填写操作是否成功。"""
    return await field.evaluate("el => el.value === undefined ? (el.innerText || '') : el.value")


class NativeArticleAdapter:
    """共享安全边界，不共享平台文章形态或泛化正文选择器。"""

    platform = ""
    label = ""
    editor_url = ""
    title_selector = ""
    editor_selector = ""
    cover_selector = ""
    summary_selector = ""
    publish_name = "发布"

    def __init__(self, snapshot: dict, cover: Path | None):
        self.snapshot = snapshot
        self.title = snapshot["title"].strip()
        self.tags = list(dict.fromkeys(str(tag).strip().strip("#")
                                      for tag in snapshot.get("tags", []) if str(tag).strip("# ")))
        self.options = snapshot.get("options") or {}
        self.cover = Path(cover) if cover else None
        self.option_assets: dict[str, Path] = {}
        self._submit_started = False
        self._cover_before: set[str] = set()

    async def open_editor(self, page):
        """打开固定的原生文章入口，只接受已登录且可编辑的正文。"""
        await page.goto(self.editor_url, timeout=60000, wait_until="domcontentloaded")
        # 编辑器资源异步加载，不能把固定短等待后尚未出现的控件认作无文章权限。
        try:
            await page.locator(self.editor_selector).first.wait_for(state="visible", timeout=20000)
        except Exception as exc:
            if re.search(r"/(?:login|passport)(?:[/?.#]|$)", page.url, re.I):
                raise PreparationError(f"{self.label}登录已失效，请重新登录") from exc
            raise PreparationError(f"未找到{self.label}原生文章编辑器，请检查账号文章权限或页面加载情况") from exc
        if re.search(r"/(?:login|passport)(?:[/?.#]|$)", page.url, re.I):
            raise PreparationError(f"{self.label}登录已失效，请重新登录")
        return await _unique(page.locator(self.editor_selector), f"{self.label}原生文章正文编辑器")

    async def _title_field(self, page):
        """平台具体标题控件必须唯一，不能把摘要误当标题。"""
        return await _unique(page.locator(self.title_selector), f"{self.label}文章标题", enabled=True)

    async def fill_title(self, page):
        """填写标题并服从当前页面声明的最大长度，不静默截断。"""
        field = await self._title_field(page)
        limit = await field.get_attribute("maxlength")
        if limit and limit.isdigit() and int(limit) > 0 and len(self.title) > int(limit):
            raise PreparationError(f"{self.label}当前页面标题最多 {limit} 字，已阻止发布")
        await field.fill(self.title)

    async def verify_title(self, page):
        """以页面真实值核对完整标题。"""
        if (await _value(await self._title_field(page))).strip() != self.title:
            raise PreparationError(f"{self.label}标题读回不一致，已阻止发布")

    async def _summary_field(self, page):
        """未提供原生摘要字段的平台不能静默忽略摘要。"""
        if not self.summary_selector:
            raise PreparationError(f"尚未确认{self.label}原生文章摘要控件，请移除摘要或人工设置")
        return await _unique(page.locator(self.summary_selector), f"{self.label}摘要", enabled=True)

    async def apply_options(self, page, editor):
        """逐项设置显式参数；任何未识别的选项都在正式提交前拒绝。"""
        known = {"summary", "category", "publish_text", "statement"}
        if self.platform == "douyin":
            # 链接转换由统一正文准备层完成，此处仍需识别显式平台选项。
            known.add("links_as_text")
        unknown = [key for key, value in self.options.items() if key not in known and value not in (None, "", False)]
        if unknown:
            raise PreparationError("不支持的原生文章选项：" + "、".join(unknown))
        if self.options.get("summary"):
            await (await self._summary_field(page)).fill(self.options["summary"])
        if self.options.get("category"):
            await self._apply_category(page)
        if self.options.get("statement"):
            await self._apply_statement(page)
        if self.options.get("publish_text") and self.platform != "weibo":
            raise PreparationError(f"{self.label}没有微博发布文案选项")
        if self.tags:
            await self._apply_tags(page, editor)
        if self.cover and not getattr(self, "_cover_prepared", False):
            self._cover_before = {item["src"] for item in await self._cover_images(page)}
            await self._upload_cover(page)

    async def verify_options(self, page, editor):
        """确认选项已实际生效，候选项、说明文本和本地预览不能算成功。"""
        if self.options.get("summary"):
            if await _value(await self._summary_field(page)) != self.options["summary"]:
                raise PreparationError(f"{self.label}摘要读回不一致，已阻止发布")
        if self.options.get("category"):
            field = await _unique(page.get_by_label("分类", exact=True), f"{self.label}分类")
            selected = await field.locator("option:checked").all_text_contents()
            if selected != [self.options["category"]]:
                raise PreparationError(f"{self.label}分类读回不一致，已阻止发布")
        if self.options.get("statement"):
            field = await _unique(page.get_by_label(self.options["statement"], exact=True), f"{self.label}声明")
            if not await field.is_checked():
                raise PreparationError(f"{self.label}声明未选中，已阻止发布")
        if self.tags:
            await self._verify_tags(page, editor)
        if self.cover:
            images = await self._cover_images(page)
            if not any(is_uploaded_image(item, self.platform) and item["src"] not in self._cover_before
                       for item in images):
                raise PreparationError(f"未确认{self.label}新封面上传完成，已阻止发布")

    async def _apply_category(self, page):
        """仅操作页面明确标注的原生分类下拉框，不猜默认分类。"""
        field = await _unique(page.get_by_label("分类", exact=True), f"{self.label}分类", enabled=True)
        await field.select_option(label=self.options["category"])

    async def _apply_statement(self, page):
        """声明必须有精确关联的原生复选框或单选框。"""
        field = await _unique(page.get_by_label(self.options["statement"], exact=True), f"{self.label}声明", enabled=True)
        await field.check()

    async def _apply_tags(self, page, editor):
        """没有已核实原生话题操作时要求人工处理，不追加普通井号文本。"""
        raise PreparationError(f"尚未确认{self.label}原生话题控件，请移除话题或在平台人工设置")

    async def _verify_tags(self, page, editor):
        """各平台子类必须提供可读回的原生选中证据。"""
        raise PreparationError(f"未确认{self.label}已选原生话题，已阻止发布")

    async def _cover_images(self, page):
        """只读取平台的封面区域，正文图片不能证明封面上传完成。"""
        if not self.cover_selector:
            return []
        return await page.locator(self.cover_selector).evaluate_all("""images => images.map(img => ({
            src: img.src || '', ready: img.complete && img.naturalWidth > 0}))""")

    async def _upload_cover(self, page):
        """尚无可核实的封面流程时明确失败，不吞异常继续发布。"""
        raise PreparationError(f"尚未确认{self.label}封面上传控件，请在平台人工设置")

    async def _wait_cover_changed(self, page):
        """仅轮询上传结果，不重复上传、裁剪或发布操作。"""
        for _ in range(30):
            images = await self._cover_images(page)
            if any(is_uploaded_image(item, self.platform) and item["src"] not in self._cover_before
                   for item in images):
                return
            await page.wait_for_timeout(500)
        raise PreparationError(f"未确认{self.label}新封面上传完成，已阻止发布")

    async def _mark_submit(self, on_submit):
        """先持久化提交边界；回调失败时按钮绝不能被点击。"""
        if self._submit_started:
            raise PreparationError("本任务已经尝试提交，请先核对平台记录，勿重复提交")
        result = on_submit()
        if inspect.isawaitable(result):
            await result
        self._submit_started = True

    async def submit(self, page, on_submit):
        """唯一发布按钮只点一次；点击报错后也不能重新尝试。"""
        button = await _unique(page.get_by_role("button", name=self.publish_name, exact=True),
                               f"{self.label}发布按钮", enabled=True)
        await button.scroll_into_view_if_needed()
        await self._mark_submit(on_submit)
        await button.click(timeout=10000)

    async def read_result(self, page):
        """交由统一结果读取规则判断，不能把跳转或正文当成发布成功。"""
        return await read_result_evidence(page, self.platform, self.title)


class DouyinArticleAdapter(NativeArticleAdapter):
    """抖音原生文章；独立于现有图片笔记与视频上传入口。"""
    platform, label = "douyin", "抖音"
    editor_url = "https://creator.douyin.com/creator-micro/content/post/article"
    title_selector = 'input[placeholder="请输入文章标题，最多不超过30个字"]'
    editor_selector = 'div.tiptap.ProseMirror[contenteditable="true"][role="textbox"]'
    summary_selector = 'input[placeholder="添加内容摘要或文章精彩部分吸引用户阅读，最多不超过30个字"]'

    async def submit(self, page, on_submit):
        """先监听浏览器真实文章创建回执，再持久化边界并单次点击发布。"""
        if self._submit_started:
            raise PreparationError("本任务已经尝试提交，请先核对平台记录，勿重复提交")
        self._article_receipt = None
        self._article_response_tasks = set()

        async def capture(response):
            """仅解析浏览器收到的响应，不主动请求平台，也不推断审核结果。"""
            try:
                body = await response.json()
                if not isinstance(body, dict) or not 200 <= response.status < 300:
                    return
                code, item_id = body.get("status_code"), body.get("item_id")
                if (type(code) in (int, float) and code == 0 and isinstance(item_id, str)
                        and re.fullmatch(r"[1-9][0-9]*", item_id)):
                    self._article_receipt = {
                        "status": "submitted", "message": "抖音文章创建接口已确认提交，公开状态仍待核对",
                        "platform_id": item_id, "platform_status": "已提交",
                    }
            except Exception:
                # 响应关闭、非 JSON 或未知格式均由页面证据核对，不能凭 HTTP 成功猜测结果。
                return

        def listen(response):
            """精确匹配已越过提交边界的原生文章创建请求，忽略其他作品与草稿。"""
            if not self._submit_started:
                return
            try:
                parsed = urlparse(response.url)
                request = response.request
                payload = request.post_data_json
                if (parsed.scheme != "https" or parsed.netloc != "creator.douyin.com"
                        or parsed.path != "/web/api/media/aweme/create_v2/"
                        or request.method != "POST" or not isinstance(payload, dict)):
                    return
                item = payload.get("item")
                common = item.get("common") if isinstance(item, dict) else None
                if not isinstance(common, dict) or type(common.get("media_type")) is not int or common["media_type"] != 43:
                    return
            except Exception:
                return
            task = asyncio.create_task(capture(response))
            self._article_response_tasks.add(task)
            task.add_done_callback(self._article_response_tasks.discard)

        page.on("response", listen)
        try:
            await super().submit(page, on_submit)
        except Exception:
            if not self._submit_started:
                page.remove_listener("response", listen)
            raise

    async def read_result(self, page):
        """等待已捕获响应解析完成；明确接口回执只表示已提交，不构造公开地址。"""
        pending = set(getattr(self, "_article_response_tasks", ()))
        if pending:
            _, unfinished = await asyncio.wait(pending, timeout=10)
            if unfinished:
                return {"status": "unknown", "message": "正在读取抖音文章提交回执，请勿重复提交"}
        receipt = getattr(self, "_article_receipt", None)
        if receipt:
            return dict(receipt)
        return await super().read_result(page)

    async def prepare_editor(self, page):
        """先设置封面，避免标题触发的预览重绘与封面图层合成互相干扰。"""
        if self.cover:
            self._cover_before = {item["src"] for item in await self._cover_images(page)}
            await self._upload_cover(page)
            self._cover_prepared = True

    async def _upload_cover(self, page):
        """抖音原生文件选择器进入封面编辑，完成按钮只点击一次。"""
        opener = await _unique(page.get_by_text("点击上传封面图", exact=True), "抖音封面上传入口")
        async with page.expect_file_chooser(timeout=10000) as pending:
            await opener.click(timeout=10000)
        chooser = await pending.value
        await chooser.set_files(str(self.cover))
        # 完成按钮先于图片解码出现；须等裁剪器读到真实分辨率，避免过早点击无效。
        resolution = page.get_by_text(re.compile(r"当前分辨率[：:]\s*[1-9]\d*\s*[*×]\s*[1-9]\d*"))
        await resolution.wait_for(state="visible", timeout=30000)
        # 裁剪几何先于背景/文字两层生成；官方完成动作不会等待这两个异步 blob。
        await page.wait_for_function("""async () => {
            const layers = ['.rightPanel-fOyImv .backgroundImage-WrFaqo',
                            '.rightPanel-fOyImv .pasterImage-BpPmMH'];
            for (const selector of layers) {
                const el = document.querySelector(selector);
                if (!el) return false;
                const img = el.tagName === 'IMG' ? el : el.querySelector('img');
                const match = getComputedStyle(el).backgroundImage.match(/url\\(["']?(.*?)["']?\\)/);
                const src = img?.src || match?.[1];
                if (!src || !/^(blob:|data:image\\/)/.test(src)) return false;
                const probe = new Image(); probe.src = src;
                try { await probe.decode(); } catch { return false; }
                if (!probe.naturalWidth || !probe.naturalHeight) return false;
            }
            return true;
        }""", timeout=30000)
        complete = page.get_by_role("button", name="完成", exact=True)
        await complete.wait_for(state="visible", timeout=15000)
        await (await _unique(complete, "抖音封面编辑完成", enabled=True)).click(timeout=10000)
        for _ in range(60):
            if not await complete.is_visible():
                break
            notices = await page.locator('.semi-toast').all_text_contents()
            if any("封面上传失败" in notice for notice in notices):
                raise PreparationError("抖音提示封面上传失败，请检查网络或封面素材后重试预览")
            await page.wait_for_timeout(500)
        else:
            raise PreparationError("抖音封面保存未完成，已阻止发布")
        await self._wait_cover_changed(page)

    async def _cover_images(self, page):
        """官方封面以背景图渲染，只读取含上传封面入口的 mycard 区域。"""
        cards = page.locator('[class^="mycard-"]').filter(
            has=page.get_by_text("点击上传封面图", exact=True))
        return await cards.evaluate_all("""cards => cards.flatMap(card => {
            const images = Array.from(card.querySelectorAll('img')).map(img => ({
                src: img.src, ready: img.complete && img.naturalWidth > 0}));
            for (const el of card.querySelectorAll('[style]')) {
                const background = getComputedStyle(el).backgroundImage;
                const match = background.match(/url\\(["']?(https?:[^"')]+)["']?\\)/);
                if (match) images.push({src: match[1], ready: !card.querySelector('[class^="loadingOverlay-"]')});
            }
            return images;
        })""")

    async def _apply_tags(self, page, editor):
        """按照官方原生话题窗口选择精确候选，最多五个。"""
        if len(self.tags) > 5:
            raise PreparationError("抖音原生文章最多选择5个话题")
        opener = await _unique(page.get_by_text(re.compile(r"^(点击添加话题|修改话题)$")), "抖音原生话题入口")
        await opener.click(timeout=10000)
        dialog_selector = page.locator('[class^="topicsModal-"]:visible')
        await dialog_selector.wait_for(state="visible", timeout=10000)
        dialog = await _unique(dialog_selector, "抖音原生话题窗口")
        search = await _unique(dialog.get_by_placeholder("搜索或输入你想添加的话题", exact=True), "抖音话题搜索")
        for tag in self.tags:
            await search.fill(tag)
            await page.wait_for_timeout(700)
            name = page.locator('[class^="topicName-"]').filter(has_text=re.compile(r"^#\s*" + re.escape(tag) + r"$"))
            candidate = await _unique(dialog.locator('[class^="dropdownItem-"]').filter(has=name), "抖音精确话题候选")
            await candidate.click(timeout=10000)
            selected = await dialog.locator('[class^="selectedTopicText-"]').all_text_contents()
            if tag not in [text.strip().lstrip("#").strip() for text in selected]:
                raise PreparationError(f"抖音话题候选未成为选中项：{tag}")
        confirm = await _unique(dialog.locator('button[class*="confirmButton-"]'), "抖音话题确认添加", enabled=True)
        if not (await confirm.inner_text()).strip().endswith("确认添加"):
            raise PreparationError("抖音话题确认控件已变化，请人工核对")
        await confirm.click(timeout=10000)
        await self._verify_tags(page, editor)

    async def _verify_tags(self, page, editor):
        """使用官方已选话题 chip，候选列表及正文井号文字不算选中。"""
        selected = await page.locator('.topicItem-bPZqC9 > .topicText-IgqBDd').all_text_contents()
        selected = [text.strip().lstrip("#").strip() for text in selected]
        if any(tag not in selected for tag in self.tags):
            raise PreparationError("未确认抖音已选原生话题，已阻止发布")


class BilibiliArticleAdapter(NativeArticleAdapter):
    """B 站当前专栏长图文编辑器，选择器来自官方公开编辑器脚本。"""
    platform, label = "bilibili", "B站"
    editor_url = "https://member.bilibili.com/york/read-editor"
    title_selector = 'textarea[placeholder="请输入标题（建议30字以内）"],input[placeholder="请输入标题（建议30字以内）"]'
    editor_selector = '.editor-container .ProseMirror[contenteditable="true"]'
    cover_selector = '.selected-cover img.cover-image'

    async def _apply_category(self, page):
        """当前官方编辑器固定文章分类，不能伪造可配置分区。"""
        raise PreparationError("B站当前原生专栏编辑器不提供分类选择，请移除分类选项")

    async def _apply_tags(self, page, editor):
        """使用编辑器原生输入规则生成标签节点，随后读取 data-label。"""
        await editor.click()
        await page.keyboard.press("ControlOrMeta+End")
        for tag in self.tags:
            await page.keyboard.insert_text(f" #{tag}# ")
            await page.keyboard.press("Space")
        await self._verify_tags(page, editor)

    async def _verify_tags(self, page, editor):
        """井号文字必须成为官方 topic 节点才算设置成功。"""
        selected = await editor.locator('a[data-type="topic"],span[data-type="topic"]').evaluate_all(
            "elements => elements.map(el => el.getAttribute('data-label'))")
        if any(tag not in selected for tag in self.tags):
            raise PreparationError("未确认B站已选原生标签，已阻止发布")

    async def _upload_cover(self, page):
        """本地上传只操作封面专用文件字段，裁剪确认不是文章发布。"""
        field = await _unique(page.locator('.select-cover input[type="file"][accept=".jpg,.jpeg,.png"],'
                                          '.selected-cover input[type="file"][accept=".jpg,.jpeg,.png"]'),
                              "B站封面上传字段", visible=False)
        await field.set_input_files(str(self.cover))
        dialog = await _unique(page.locator('.vui_dialog:visible').filter(
            has_text="选择封面的截取位置"), "B站封面裁剪窗口")
        confirm = await _unique(dialog.get_by_role("button", name="确定", exact=True),
                                "B站封面裁剪确认", enabled=True)
        await confirm.click(timeout=10000)
        await self._wait_cover_changed(page)


class WeiboArticleAdapter(NativeArticleAdapter):
    """微博头条文章与最终短微博发布分成独立步骤。"""
    platform, label = "weibo", "微博"
    editor_url = "https://card.weibo.com/article/v3/editor"
    title_selector = 'textarea[placeholder="请输入标题"]'
    editor_selector = '.ProseMirror[contenteditable="true"]'
    summary_selector = 'textarea[placeholder="导语（选填）"]'
    cover_selector = '.cover-preview img.cover-img'

    async def open_editor(self, page):
        """先进入草稿列表，明确点击写文章才能返回新文章编辑器。"""
        await page.goto(self.editor_url, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(1200)
        if not await page.locator(self.title_selector).count():
            opener = await _unique(page.get_by_text("写文章", exact=True), "微博写文章入口", enabled=True)
            await opener.click(timeout=10000)
        await page.locator(self.title_selector).wait_for(state="visible", timeout=15000)
        return await _unique(page.locator(self.editor_selector), "微博头条文章正文编辑器")

    async def _upload_cover(self, page):
        """上传后只选本次新增的图片库项，禁止把历史封面认作新封面。"""
        opener = await _unique(page.locator('.cover-empty,.cover-preview'), "微博封面入口")
        await opener.click(timeout=10000)
        await page.locator('.n-dialog:visible').wait_for(state="visible", timeout=10000)
        dialog = await _unique(page.locator('.n-dialog:visible'), "微博封面窗口")
        await (await _unique(dialog.get_by_text("图片库", exact=True), "微博图片库入口")).click()
        before = set(await dialog.locator('.image-list .image-item img').evaluate_all(
            "images => images.map(img => img.src)"))
        field = await _unique(dialog.locator('input[type="file"]'), "微博图片库上传字段", visible=False)
        await field.set_input_files(str(self.cover))
        uploaded = None
        for _ in range(30):
            items = dialog.locator('.image-list .image-item')
            for index in range(await items.count()):
                candidate = items.nth(index)
                state = await candidate.locator('img').evaluate_all("""images => images.map(img => ({
                    src: img.src, ready: img.complete && img.naturalWidth > 0}))""")
                if len(state) == 1 and state[0]['src'] not in before and is_uploaded_image(state[0], self.platform):
                    uploaded = candidate
                    break
            if uploaded is not None:
                break
            await page.wait_for_timeout(500)
        if uploaded is None:
            raise PreparationError("微博新封面未完成平台上传，已阻止发布")
        await uploaded.click(timeout=10000)
        if not re.search(r"\bis-selected\b", await uploaded.get_attribute("class") or ""):
            raise PreparationError("微博封面图片库未选中本次上传的图片")
        await (await _unique(dialog.get_by_role("button", name="下一步", exact=True),
                             "微博封面裁剪入口", enabled=True)).click(timeout=10000)
        await (await _unique(dialog.get_by_role("button", name="确定", exact=True),
                             "微博封面裁剪确认", enabled=True)).click(timeout=10000)
        await self._wait_cover_changed(page)

    async def submit(self, page, on_submit):
        """下一步和最终发布各点一次；边界持久化后任何失败均不得重发。"""
        next_button = await _unique(page.get_by_role("button", name="下一步", exact=True),
                                    "微博文章下一步", enabled=True)
        await next_button.scroll_into_view_if_needed()
        await self._mark_submit(on_submit)
        await next_button.click(timeout=10000)
        await page.wait_for_timeout(700)
        # 官方 PC 流程要求编辑短微博；只接受与最终发布按钮同窗的文本字段。
        dialog = await _unique(page.locator('.n-dialog:visible,[role="dialog"]:visible'), "微博最终发布窗口")
        publish_text = self.options.get("publish_text") or self.title
        field = await _unique(dialog.get_by_role("textbox"), "微博发布文案", enabled=True)
        await field.fill(publish_text)
        if await _value(field) != publish_text:
            raise PreparationError("微博发布文案读回不一致，已阻止最终发布")
        button = await _unique(dialog.get_by_role("button", name="发布", exact=True),
                               "微博最终发布按钮", enabled=True)
        await button.click(timeout=10000)


class QiehaoArticleAdapter(NativeArticleAdapter):
    """企鹅号文章入口；公开页无编辑器，严格要求原生表单语义。"""
    platform, label = "qiehao", "企鹅号"
    editor_url = "https://om.qq.com/main/creation/article"
    cover_selector = '#articlePublish-coverinfo img,#om-art-normal-cover img'

    async def _title_field(self, page):
        """缺少关联标签时要求人工处理，不能把任意输入框填成标题。"""
        modern = page.locator('.omui-articletitle__title1 .omui-inputautogrowing__inner')
        if await modern.count():
            return await _unique(modern, "企鹅号文章标题", enabled=True)
        return await _unique(page.get_by_role("textbox", name="标题", exact=True), "企鹅号文章标题", enabled=True)

    async def open_editor(self, page):
        """仅确认有唯一 UEditor iframe 时返回该框架内可编辑正文。"""
        await page.goto(self.editor_url, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(1200)
        await self._title_field(page)
        modern = page.locator('.ProseMirror[contenteditable="true"]')
        if await modern.count():
            return await _unique(modern, "企鹅号原生文章正文编辑器")
        frame_element = await _unique(page.locator('.edui-editor-iframeholder iframe'), "企鹅号文章 UEditor 框架")
        frame = await (await frame_element.element_handle()).content_frame()
        if frame is None:
            raise PreparationError("企鹅号文章编辑器框架不可读取，请人工核对")
        return await _unique(frame.locator('body[contenteditable="true"]'), "企鹅号原生文章正文编辑器")

    async def _summary_field(self, page):
        """摘要只接受明确的辅助名称，未确认的个人页面不作默认适配。"""
        return await _unique(page.get_by_role("textbox", name="摘要", exact=True), "企鹅号摘要", enabled=True)

    async def apply_options(self, page, editor):
        """需要内容自主声明时在准备阶段提示用户指定，避免进入正式提交才失败。"""
        if not self.options.get("statement"):
            opener = page.get_by_role("button", name="添加内容自主声明", exact=True)
            for index in range(await opener.count()):
                if await opener.nth(index).is_visible():
                    raise PreparationError("企鹅号文章需要设置内容自主声明，请填写对应的平台声明后重试")
        await super().apply_options(page, editor)

    async def _upload_cover(self, page):
        """使用官方封面模板的手动上传与裁剪，不调用文章发布接口。"""
        modern = page.locator('#articlePublish-coverinfo > button.omui-button--add')
        if await modern.count():
            await self._upload_modern_cover(page, modern)
            return
        region = await _unique(page.locator('#om-art-normal-cover'), "企鹅号文章封面区")
        # 按钮必须具有明确封面语义；不从整页任选上传图标。
        opener = await _unique(region.get_by_text(re.compile(r"^(上传封面|设置封面|添加封面|选择封面)$")),
                               "企鹅号封面设置入口")
        await opener.click(timeout=10000)
        await page.locator('.layui-layer:visible .pop-body:has([data-content="crop"])').wait_for(
            state="visible", timeout=10000)
        dialog = await _unique(page.locator('.layui-layer:visible').filter(
            has=page.locator('[data-content="crop"]')), "企鹅号封面上传窗口")
        tab = await _unique(dialog.locator('li[data-id="crop"]'), "企鹅号手动上传页签")
        await tab.click(timeout=10000)
        previous = set(await dialog.locator('[data-content="crop"] [data-action="convas"] > img').evaluate_all(
            "images => images.map(img => img.src)"))
        upload = await _unique(dialog.locator('[data-content="crop"] [data-action="upload"]'),
                               "企鹅号封面图片上传入口")
        async with page.expect_file_chooser(timeout=10000) as pending:
            await upload.click(timeout=10000)
        chooser = await pending.value
        await chooser.set_files(str(self.cover))
        ready = False
        for _ in range(30):
            images = await dialog.locator('[data-content="crop"] [data-action="convas"] > img').evaluate_all(
                """images => images.map(img => ({src: img.src,
                    ready: img.complete && img.naturalWidth > 0}))""")
            if (len(images) == 1 and images[0]["src"] not in previous and
                    is_uploaded_image(images[0], self.platform)):
                ready = True
                break
            await page.wait_for_timeout(500)
        if not ready:
            raise PreparationError("企鹅号封面原图上传尚未完成，已阻止发布")
        confirm = await _unique(dialog.locator('.layui-layer-btn0'), "企鹅号封面裁剪确认", enabled=True)
        if (await confirm.inner_text()).strip() != "确定":
            raise PreparationError("企鹅号封面确认控件文字发生变化，请人工处理")
        await confirm.click(timeout=10000)
        await self._wait_cover_changed(page)

    async def _upload_modern_cover(self, page, opener):
        """新封面控件来自企鹅号作者公开操作记录，按钮确认按文字限域。"""
        await (await _unique(opener, "企鹅号添加文章封面入口", enabled=True)).click(timeout=10000)
        await page.locator('.omui-dialog:visible').wait_for(state="visible", timeout=10000)
        dialog = await _unique(page.locator('.omui-dialog:visible'), "企鹅号文章封面窗口")
        local = await _unique(dialog.locator('li.omui-tab__label').filter(has_text=re.compile(r"^本地上传$")),
                              "企鹅号封面本地上传页签")
        await local.click(timeout=10000)
        upload = await _unique(dialog.locator('.omui-upload-image-trigger > input[type="file"]'),
                               "企鹅号封面上传字段", visible=False)
        await upload.set_input_files(str(self.cover))
        confirm = await _unique(dialog.locator('.omui-dialog-footer').get_by_role(
            "button", name=re.compile(r"^(确认|确定)$")), "企鹅号封面确认", enabled=True)
        await confirm.click(timeout=10000)
        await self._wait_cover_changed(page)

    async def _apply_category(self, page):
        """当前版本分类是原生建议控件，只选择精确匹配候选。"""
        modern = page.locator('#articlePublish-category_id > .omui-suggestion__input > input.omui-suggestion__value')
        if not await modern.count():
            await super()._apply_category(page)
            return
        field = await _unique(modern, "企鹅号分类输入", enabled=True)
        await field.fill(self.options["category"])
        await page.wait_for_timeout(500)
        candidate = await _unique(page.get_by_role("option", name=self.options["category"], exact=True),
                                  "企鹅号精确分类候选", enabled=True)
        await candidate.click(timeout=10000)

    async def _apply_statement(self, page):
        """新编辑器先打开自主声明，再选择用户指定的原生选项。"""
        opener = page.get_by_role("button", name="添加内容自主声明", exact=True)
        if not await opener.count():
            await super()._apply_statement(page)
            return
        await (await _unique(opener, "企鹅号内容自主声明入口", enabled=True)).click(timeout=10000)
        await page.locator('.omui-dialog:visible').wait_for(state="visible", timeout=10000)
        dialog = await _unique(page.locator('.omui-dialog:visible'), "企鹅号内容自主声明窗口")
        selected = await _unique(dialog.get_by_label(self.options["statement"], exact=True),
                                 "企鹅号内容自主声明选项", enabled=True)
        await selected.check()
        if not await selected.is_checked():
            raise PreparationError("企鹅号内容自主声明未选中，已阻止发布")
        confirm = await _unique(dialog.get_by_role("button", name=re.compile(r"^(确认|确定)$")),
                                "企鹅号内容自主声明确认", enabled=True)
        await confirm.click(timeout=10000)
        await dialog.wait_for(state="hidden", timeout=10000)
        self._declaration_expected = self.options["statement"]

    async def verify_options(self, page, editor):
        """新分类和声明单独读取，随后复用封面及其他选项的严格核验。"""
        category = self.options.get("category")
        statement = self.options.get("statement")
        modern = page.locator('#articlePublish-category_id > .omui-suggestion__input > input.omui-suggestion__value')
        if category and await modern.count():
            if await _value(await _unique(modern, "企鹅号已选分类")) != category:
                raise PreparationError("企鹅号分类读回不一致，已阻止发布")
        else:
            category = None
        if statement and getattr(self, "_declaration_expected", None) == statement:
            receipt = page.get_by_text(statement, exact=True)
            receipt = await _unique(receipt, "企鹅号已选内容自主声明")
            if await receipt.evaluate("el => !!el.closest('[contenteditable],.ProseMirror,.omui-dialog')"):
                raise PreparationError("企鹅号尚未确认自主声明已应用到文章，已阻止发布")
        else:
            statement = None
        # 通用核验负责旧版控件；已独立读取的新控件仅在调用期间去重。
        options = self.options
        self.options = {key: value for key, value in options.items()
                        if not (key == "category" and category) and not (key == "statement" and statement)}
        try:
            await super().verify_options(page, editor)
        finally:
            self.options = options

    async def _apply_tags(self, page, editor):
        """企鹅号保存原生关键词字段；页面没有该字段时要求人工设置。"""
        field = await _unique(page.get_by_label("标签", exact=True), "企鹅号文章标签", enabled=True)
        await field.fill(" ".join(self.tags))
        await self._verify_tags(page, editor)

    async def _verify_tags(self, page, editor):
        """原生关键词控件必须完整读回，正文井号文字不作为证据。"""
        field = await _unique(page.get_by_label("标签", exact=True), "企鹅号文章标签")
        selected = [tag for tag in re.split(r"[\s,，]+", await _value(field)) if tag]
        if selected != self.tags:
            raise PreparationError("企鹅号原生标签读回不一致，已阻止发布")


def create_native_adapter(snapshot: dict, cover: Path | None = None) -> NativeArticleAdapter:
    """显式分派原生文章平台，未知平台不得落入通用发布流程。"""
    adapters = {"douyin": DouyinArticleAdapter, "bilibili": BilibiliArticleAdapter,
                "weibo": WeiboArticleAdapter, "qiehao": QiehaoArticleAdapter}
    if snapshot.get("platform") in {"yidian", "dayu", "netease", "kuaichuan"}:
        from utils.articles.publishers import PUBLISHER_ADAPTERS
        adapters.update(PUBLISHER_ADAPTERS)
    elif snapshot.get("platform") in {"acfun", "xueqiu", "douban", "csdn", "jianshu"}:
        from utils.articles.community import COMMUNITY_ADAPTERS
        adapters.update(COMMUNITY_ADAPTERS)
    elif snapshot.get("platform") == "jingdong":
        from utils.articles.jingdong import JingdongArticleAdapter
        adapters["jingdong"] = JingdongArticleAdapter
    elif snapshot.get("platform") == "chejiahao":
        from utils.articles.chejiahao import ChejiahaoArticleAdapter
        adapters["chejiahao"] = ChejiahaoArticleAdapter
    elif snapshot.get("platform") == "yiche":
        from utils.articles.yiche import YicheArticleAdapter
        adapters["yiche"] = YicheArticleAdapter
    elif snapshot.get("platform") == "dongchedi":
        from utils.articles.dongchedi import DongchediArticleAdapter
        adapters["dongchedi"] = DongchediArticleAdapter
    adapter = adapters.get(snapshot.get("platform"))
    if adapter is None:
        raise PreparationError("不支持的原生文章平台：" + str(snapshot.get("platform")))
    return adapter(snapshot, cover)

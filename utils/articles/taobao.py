"""淘宝光合图文：图库上传、原图相册及必填声明的严格读回。

公开控件依据（不代表真实账号验收）：
Jiarenzaigusu/multi-platform-auto-upload-main-DAM-newest，753566cefe5d，
uploader/tmall_article_uploader/main.py：gg-picture、sucai-selector-ng 图片库、
仓颉正文及声明单选框；图片尺寸依据 yixiaoer888/yixiaoer-skill，a2722c6095f5，
skills/yixiaoer/references/platforms/imageText/taobaoguanghe.md。
声明选项依据 DevilJie/social-auto-upload-web-ui，8e33adf0e461，
backend/impl/taobao_guanghe/platform.py。不复用其重试或宽松成功判定。
"""
from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from utils.articles.browser import (
    PreparationError, has_visible_challenge, inspect_content, is_uploaded_image, receipt_status,
)
from utils.articles.native import _unique
from utils.articles.notes import NoteAdapter, prepare_note_document


TAOBAO_STATEMENTS = (
    "内容无需标注", "含AI生成内容", "含虚构演绎内容", "内容为转载",
    "个人观点，仅供参考", "内容含营销信息",
)
TAOBAO_EDITOR_URL = (
    "https://creator.guanghe.taobao.com/page/pubNew/pic?"
    "pub_url=https%3A%2F%2Fhuodong.taobao.com%2Fwow%2Fz%2Fguang%2F"
    "gg_publish%2Fgg-picture%3Fugc_scene%3Dpc_newcreator_pic%26"
    "pageType%3Darticle%26site%3Dguangguang&pub_scene=gg"
)


def validate_taobao_snapshot(snapshot: dict, assets: dict) -> None:
    """平台原生标签与商品不能悄悄丢失，也不能代用户选择内容声明。"""
    options = snapshot.get("options") or {}
    if options.get("statement") not in TAOBAO_STATEMENTS:
        raise PreparationError("淘宝光合必须明确选择创作者声明，请在账号发布设置中选择")
    unsupported = [key for key, value in options.items()
                   if key not in {"flatten_content", "statement"} and value not in (None, "", False)]
    if unsupported:
        raise PreparationError("淘宝光合图文尚不支持选项：" + "、".join(unsupported))
    if snapshot.get("tags"):
        raise PreparationError("淘宝光合原生内容标签尚未适配，请清空话题后重试")
    ids = list(inspect_content(snapshot.get("content_html", "")).asset_ids)
    if snapshot.get("cover_asset_id"):
        if snapshot["cover_asset_id"] in ids and ids[0] != snapshot["cover_asset_id"]:
            raise PreparationError("淘宝光合以首张图片作为封面，请把所选封面放在正文图片首位")
        ids.append(snapshot["cover_asset_id"])
    for asset_id in ids:
        asset = assets.get(asset_id)
        if not asset:
            raise PreparationError(f"图片素材不存在：{asset_id}")
        if int(asset.get("width") or 0) < 720 or int(asset.get("height") or 0) < 720:
            raise PreparationError("淘宝光合每张图文图片宽高均须至少 720 像素")


def _is_taobao_frame(url: str, marker: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "taobao.com" or host.endswith(".taobao.com")) and marker in parsed.path


class TaobaoNoteAdapter(NoteAdapter):
    platform, label = "taobao", "淘宝光合"
    editor_url = TAOBAO_EDITOR_URL
    title_selector = 'input[placeholder="加个标题让内容更吸引人"]'
    editor_selector = 'div[data-cangjie-content="true"][contenteditable="true"]'
    publish_name = "立即发布"

    async def _open_note(self, page):
        await super()._open_note(page)
        if urlparse(page.url).hostname != "creator.guanghe.taobao.com":
            raise PreparationError("淘宝光合未进入创作者后台，请重新登录并检查图文权限")

    async def _frame(self, page, marker, label):
        for _ in range(40):
            frames = [frame for frame in page.frames if _is_taobao_frame(frame.url, marker)]
            if len(frames) == 1:
                return frames[0]
            if len(frames) > 1:
                raise PreparationError(f"淘宝光合存在多个{label}，已阻止发布")
            await page.wait_for_timeout(500)
        raise PreparationError(f"未找到淘宝光合{label}，请检查账号权限或平台页面变化")

    async def _scope(self, page):
        return await self._frame(page, "/gg_publish/gg-picture", "图文编辑器 iframe")

    async def _album_images(self, scope):
        # 只读图文相册；图库历史素材、商品图和导航头像不属于正文。
        # 轮播中的隐藏图片仍须逐张核对，不能只核对当前可见的首图。
        return await scope.locator("#picture-upload-wrapper img").evaluate_all("""images=>images.map(img=>({
            src:img.currentSrc||img.src,ready:img.complete&&img.naturalWidth>0}))""")

    async def _picker_button(self, picker, name):
        return await _unique(picker.get_by_role("button", name=name, exact=True),
                             f"淘宝光合图片库“{name}”按钮", enabled=True)

    async def _upload_picker_file(self, page, picker, path):
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        await picker.get_by_text("本地上传", exact=True).first.wait_for(state="visible", timeout=20000)
        local = await _unique(picker.get_by_text("本地上传", exact=True), "淘宝光合本地上传入口")
        try:
            async with page.expect_file_chooser(timeout=10000) as pending:
                await local.click(timeout=10000)
            chooser = await pending.value
        except PlaywrightTimeoutError:
            # 已核实的另一种界面先打开“上传素材”对话框，再显示导入按钮。
            nested = await _unique(picker.locator("#sucai-tu-upload"), "淘宝光合上传素材控件", enabled=True)
            async with page.expect_file_chooser(timeout=10000) as pending:
                await nested.click(timeout=10000)
            chooser = await pending.value
        await chooser.set_files(str(path))

    async def _uploaded_card(self, page, picker, stem):
        # 原图复制成任务唯一文件名；绝不按“图库第一张”或历史同名图片选择。
        cards = picker.locator("label").filter(has=picker.locator("img")).filter(
            has=picker.locator('input[type="checkbox"],input[type="radio"]'))
        for _ in range(120):
            matches = []
            for index in range(await cards.count()):
                card = cards.nth(index)
                text = await card.evaluate("el => (el.parentElement?.innerText || el.innerText || '')")
                if re.search(r"(?<![\w-])" + re.escape(stem) + r"(?![\w-])", text, re.I):
                    matches.append(card)
            if len(matches) > 1:
                raise PreparationError("淘宝光合图库本次文件名存在多个匹配，已阻止选择图片")
            if matches:
                card = matches[0]
                images = await card.locator("img").evaluate_all("""images=>images.map(img=>({
                    src:img.currentSrc||img.src,ready:img.complete&&img.naturalWidth>0}))""")
                if len(images) == 1 and is_uploaded_image(images[0], self.platform):
                    return card, images[0]["src"]
            await page.wait_for_timeout(500)
        raise PreparationError("淘宝光合图库未确认本次原图上传完成；本地预览不算上传凭据")

    async def _upload_one(self, page, scope, path):
        await scope.locator("#picture-upload-wrapper .next-picture-uploader").first.wait_for(
            state="visible", timeout=20000)
        entry = await _unique(scope.locator("#picture-upload-wrapper .next-picture-uploader"),
                              "淘宝光合图文图片库入口", enabled=True)
        # 来源实测该组件 ::before 拦截命中；仅对唯一、可见的图片入口强制点击。
        await entry.click(force=True, timeout=10000)
        picker = await self._frame(page, "sucai-selector-ng", "图片库 iframe")
        # 不清空不明来源的已有选择：直接停止，防止把历史素材混入相册。
        checked = picker.locator('label:has(img) input:checked')
        if await checked.count():
            raise PreparationError("淘宝光合图片库已有选中素材，请先清空图库选择后重试")
        with TemporaryDirectory(prefix="postsail-taobao-") as directory:
            staged = Path(directory) / ("postsail-" + uuid.uuid4().hex + path.suffix.lower())
            shutil.copy2(path, staged)
            await self._upload_picker_file(page, picker, staged)
            await picker.get_by_role("button", name="完成", exact=True).first.wait_for(state="visible", timeout=120000)
            await (await self._picker_button(picker, "完成")).click(timeout=10000)
            card, url = await self._uploaded_card(page, picker, staged.stem)
        control = await _unique(card.locator('input[type="checkbox"],input[type="radio"]'),
                                "淘宝光合本次图片选择框", visible=False)
        if not await control.is_checked():
            await card.click(timeout=10000)
        if not await control.is_checked() or await checked.count() != 1:
            raise PreparationError("淘宝光合图库未唯一选中本次图片，已阻止发布")
        self._pending_uploaded_url = url
        await (await self._picker_button(picker, "确定")).click(timeout=10000)

    async def _wait_uploaded(self, page, scope, document, index):
        for _ in range(60):
            if await scope.get_by_text(re.compile(r"^(?:图片)?上传(?:失败|出错)")).filter(visible=True).count():
                raise PreparationError("淘宝光合图片上传失败，已阻止发布")
            images = await self._album_images(scope)
            urls = [item["src"] for item in images]
            if len(urls) > index + 1 or urls[:len(document.uploaded_urls)] != document.uploaded_urls:
                raise PreparationError("淘宝光合相册图片数量或顺序异常，已阻止发布")
            expected = document.uploaded_urls + [self._pending_uploaded_url]
            if urls == expected and all(is_uploaded_image(item, self.platform) for item in images):
                document.uploaded_urls.append(urls[-1])
                return
            await page.wait_for_timeout(500)
        raise PreparationError("淘宝光合图库与相册图片读回不一致，已阻止发布")

    async def _statement(self, scope):
        labels = scope.locator("label.next-radio-wrapper").filter(
            has_text=re.compile(r"^\s*" + re.escape(self.options["statement"]) + r"\s*$"))
        label = await _unique(labels, "淘宝光合创作者声明")
        radio = await _unique(label.locator('input[type="radio"]'), "淘宝光合声明单选框", visible=False)
        return label, radio

    async def _verify_form(self, scope):
        _, radio = await self._statement(scope)
        if not await radio.is_checked():
            raise PreparationError("淘宝光合创作者声明读回不一致，已阻止发布")
        extras = await scope.locator("body").evaluate("""body=>{
            const visible=el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height>0;};
            const scheduled=[...body.querySelectorAll('label.next-radio-wrapper')].some(label=>{
                if(!label.querySelector('input:checked'))return false;
                const sibling=label.nextElementSibling;
                const text=(label.innerText||'').trim()||
                    (sibling&&sibling.tagName!=='LABEL'&&!sibling.querySelector('input[type="radio"]')
                        ? (sibling.innerText||'').trim():'');
                return text==='定时发布';});
            const invalid=[...body.querySelectorAll('input:invalid,textarea:invalid,select:invalid')]
                .some(visible);
            const products=[...body.querySelectorAll('a[href]')].some(a=>{
                if(!visible(a))return false;try{const u=new URL(a.href);return (
                    ['item.taobao.com','detail.tmall.com'].includes(u.hostname)&&u.searchParams.has('id'));
                }catch{return false;}});
            return {scheduled,invalid,products};
        }""")
        if extras["scheduled"]:
            raise PreparationError("淘宝光合页面已选择定时发布，请切回立即发布后重试")
        if extras["invalid"]:
            raise PreparationError("淘宝光合页面存在未完成的必填字段，请在平台核对后重试")
        if extras["products"]:
            raise PreparationError("淘宝光合页面已有商品信息，本任务未支持商品关联，请清空后重试")

    async def prepare_note(self, page, assets):
        validate_taobao_snapshot(self.snapshot, assets)
        document = prepare_note_document(self.snapshot, assets)
        await self._open_note(page)
        scope = await self._scope(page)
        await self._install_preview_guard(page)
        if await self._album_images(scope):
            raise PreparationError("淘宝光合页面已有图片，可能存在恢复的草稿；请先清空图文表单后重试")
        await self._protect_existing_text(scope)
        for index, path in enumerate(document.image_paths):
            await self._upload_one(page, scope, path)
            await self._wait_uploaded(page, scope, document, index)
        editor = await self._body_editor(scope)
        await self._protect_existing_text(scope)
        await editor.fill(document.expected_text)
        await self.fill_title(scope)
        label, radio = await self._statement(scope)
        if not await radio.is_checked():
            await label.click(timeout=10000)
        self._note_scope, self._note_editor, self._note_document = scope, editor, document
        await self.verify_note(page)
        return editor, document

    async def verify_note(self, page):
        await super().verify_note(page)
        await self._verify_form(self._note_scope)

    async def _feedback(self, frame):
        return await frame.locator('[role="alert"],.next-message,h1,h2,h3').evaluate_all("""elements=>elements
            .filter(el=>!el.closest('[contenteditable],[data-cangjie-content]'))
            .filter(el=>{const r=el.getBoundingClientRect();const s=getComputedStyle(el);
                return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none';})
            .map(el=>(el.innerText||'').trim())""")

    async def submit(self, page, on_submit):
        if self._submit_started:
            raise PreparationError("本任务已经尝试提交，请先核对平台记录，勿重复提交")
        # 记录提交前的提示，旧提示、正文、草稿和后台跳转均不能证明本次发布。
        self._feedback_before = set()
        for frame in page.frames:
            self._feedback_before.update(await self._feedback(frame))
        await super().submit(page, on_submit)

    async def read_result(self, page):
        if not self._submit_started:
            return {"status": "unknown", "message": "淘宝光合任务尚未提交"}
        statuses = []
        for frame in page.frames:
            feedback = await self._feedback(frame)
            if await has_visible_challenge(frame, feedback):
                return {"status": "needs_action", "message": "淘宝光合要求人工验证，请核对平台记录后处理"}
            statuses.extend(receipt_status(text) for text in feedback
                            if text not in self._feedback_before and text != self.title)
        for term in ("发布失败", "发表失败", "审核不通过", "内容违规", "提交失败"):
            if term in statuses:
                return {"status": "failed", "message": f"平台反馈：{term}", "platform_status": term}
        for term in ("审核中", "等待审核", "发布成功", "发表成功", "提交成功"):
            if term in statuses:
                return {"status": "submitted", "message": f"平台已确认提交：{term}", "platform_status": term}
        return {"status": "unknown", "message": "已尝试提交淘宝光合图文，尚无明确回执；请核对平台记录，勿重复提交"}

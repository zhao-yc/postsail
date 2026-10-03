"""小红书千帆商家商品笔记；不把个人创作者登录当作商家权限。

公开控件依据（未代替真实账号验收）：
https://github.com/gaoming714/ByteScript/blob/c9f8d46a4e453f83d9c1e5a9b8b135fb53b4244b/xiaohongshu0x01.py
源码使用千帆 app-note/publish、.store-name、商品卡和手动创作流程。
本实现要求准确店名及商品 ID；商家身份、所选商品或原图相册无法核实时停止。
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from utils.articles.browser import PreparationError
from utils.articles.native import _unique
from utils.articles.notes import NoteAdapter


MERCHANT_LOGIN_URL = "https://customer.xiaohongshu.com/login?service=https://ark.xiaohongshu.com/ark/home"
MERCHANT_PUBLISH_URL = "https://ark.xiaohongshu.com/app-note/publish"


def require_merchant_origin(url: str) -> None:
    """仅承认千帆后台；个人 creator 页、登录页和相似域名均不构成商家身份。"""
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise PreparationError("千帆商家后台地址无效，请重新登录商家号") from exc
    if (parsed.scheme != "https" or parsed.hostname != "ark.xiaohongshu.com" or
            parsed.username or parsed.password or port not in (None, 443) or
            re.search(r"/(?:login|passport)(?:[/?.#]|$)", parsed.path, re.I)):
        raise PreparationError("未进入小红书千帆商家后台，请使用商家号重新登录；个人创作者会话不能替代")


async def read_merchant_store_name(page, expected: str | None = None) -> str:
    """从商家后台唯一可见店名读取当前店铺，不能从 Cookie 或页面宣传文案推断。"""
    require_merchant_origin(page.url)
    field = await _unique(page.locator(".store-name"), "千帆当前店铺名称")
    value = (await field.inner_text()).strip()
    if not value:
        raise PreparationError("千帆店铺名称为空，请完成商家登录和店铺选择")
    if expected is not None and value != expected:
        raise PreparationError("千帆当前店铺与填写的店铺名称不一致，请切换正确店铺后重试")
    return value


def product_id_from_text(value: str) -> str | None:
    """商品描述字段必须给出完整 ID；短前缀和商品名称不能代替 ID。"""
    match = re.search(r"(?:^|\s)商品\s*(?:ID)?\s*[:：]\s*([A-Za-z0-9_-]+)\s*$", value, re.I)
    return match.group(1) if match else None


class XiaohongshuMerchantAdapter(NoteAdapter):
    """千帆商品笔记使用独立入口，借用已核验的原图上传与单次提交边界。"""

    platform, label = "xiaohongshu_merchant", "小红书商家号"
    editor_url = MERCHANT_PUBLISH_URL
    title_selector = 'input[placeholder="填写标题，可能会有更多赞哦～"]'
    editor_selector = "#post-textarea"
    upload_selector = '.upload-wrapper input[type="file"]'

    def __init__(self, snapshot, cover=None):
        super().__init__(snapshot, cover)

    def _validate_options(self):
        known = {"flatten_content", "product_id", "shop_name"}
        unknown = [key for key, value in self.options.items() if key not in known and value not in (None, "", False)]
        if unknown:
            raise PreparationError("小红书商家笔记尚不支持选项：" + "、".join(unknown))
        product_id = self.options.get("product_id")
        shop_name = self.options.get("shop_name")
        if not isinstance(product_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", product_id):
            raise PreparationError("小红书商家笔记必须填写准确的商品 ID（1-64 位字母、数字、下划线或连字符）")
        if not isinstance(shop_name, str) or not shop_name.strip() or len(shop_name) > 100:
            raise PreparationError("小红书商家笔记必须填写当前店铺的完整名称（1-100 字）")
        if shop_name != shop_name.strip():
            raise PreparationError("店铺名称首尾不能有空白，请填写千帆显示的完整店名")
        if "flatten_content" in self.options and not isinstance(self.options["flatten_content"], bool):
            raise PreparationError("将富文本转换为纯文本必须为布尔值")

    async def _product_cards(self, scope):
        result = []
        cards = scope.locator(".cell-note-item")
        for index in range(await cards.count()):
            card = cards.nth(index)
            if not await card.is_visible():
                continue
            desc = await _unique(card.locator(".item-desc"), "商家笔记商品 ID 字段")
            result.append((card, product_id_from_text(await desc.inner_text())))
        return result

    async def _wait_for_product(self, page):
        expected = self.options["product_id"]
        for _ in range(40):
            cards = await self._product_cards(page)
            matches = [card for card, product_id in cards if product_id == expected]
            if len(matches) > 1:
                raise PreparationError("千帆搜索到多个相同商品 ID，无法确定唯一商品，已阻止发布")
            if len(matches) == 1:
                return matches[0]
            await page.wait_for_timeout(500)
        raise PreparationError("千帆未找到准确商品 ID，请确认该商品属于当前店铺且有发笔记权限")

    async def _optional_button(self, page, name: str):
        locator = page.get_by_role("button", name=name, exact=True)
        visible = [locator.nth(index) for index in range(await locator.count())
                   if await locator.nth(index).is_visible()]
        if len(visible) > 1:
            raise PreparationError(f"商家创作页面出现多个“{name}”按钮，请人工处理后重试")
        if visible:
            if not await visible[0].is_enabled():
                raise PreparationError(f"商家创作页面“{name}”不可用")
            await visible[0].click(timeout=10000)

    async def _open_note(self, page):
        self._validate_options()
        await super()._open_note(page)
        require_merchant_origin(page.url)
        await page.locator(".store-name").first.wait_for(state="visible", timeout=20000)
        await read_merchant_store_name(page, self.options["shop_name"])
        search = await _unique(page.get_by_placeholder("请输入商品ID/商品名称查询", exact=True),
                               "千帆商品搜索框", enabled=True)
        await search.fill(self.options["product_id"])
        await search.press("Enter")
        card = await self._wait_for_product(page)
        start = await _unique(card.get_by_text("去发笔记", exact=True), "目标商品的去发笔记入口", enabled=True)
        await start.click(timeout=10000)
        require_merchant_origin(page.url)
        # 只跳过推荐创作引导；不使用来源脚本的无条件确认和重复发布逻辑。
        await self._optional_button(page, "跳过")
        manual = page.get_by_text("手动创作", exact=True)
        await manual.first.wait_for(state="visible", timeout=20000)
        await (await _unique(manual, "千帆手动创作入口", enabled=True)).click(timeout=10000)
        dialogs = page.locator('[role="dialog"],.d-modal').filter(visible=True)
        creation_dialogs = []
        for index in range(await dialogs.count()):
            dialog = dialogs.nth(index)
            text = await dialog.inner_text()
            # 仅允许明确“手动创作”的确认，不能把未知确定按钮当作导航。
            if "手动创作" in text and not re.search(r"发布|发表|提交|付费|支付", text):
                creation_dialogs.append(dialog)
        if len(creation_dialogs) > 1:
            raise PreparationError("千帆出现多个手动创作确认窗口，请人工处理后重试")
        if creation_dialogs:
            confirm = await _unique(creation_dialogs[0].get_by_role("button", name="确定", exact=True),
                                    "手动创作确认", enabled=True)
            await confirm.click(timeout=10000)
        upload_tab = page.locator(".container .header").get_by_text("上传图文", exact=True)
        await upload_tab.first.wait_for(state="visible", timeout=20000)
        await (await _unique(upload_tab, "商家上传图文标签", enabled=True)).click(timeout=10000)
        require_merchant_origin(page.url)
        await page.locator(self.upload_selector).first.wait_for(state="attached", timeout=20000)

    async def _album_images(self, scope):
        # 商品卡中的商品主图不属于笔记相册；其余已有图片仍视为恢复的草稿。
        # 不按启动时 URL 排除图片，因此不能漏过上次未清空的笔记配图。
        return await scope.locator("img").evaluate_all("""images=>images.filter(img=>{
            if(img.closest('.cell-note-item,header,nav,[role="navigation"],[class~="avatar"],'
                +'[class*="user-avatar"],[class*="userAvatar"],[class*="user_avatar"]'))return false;
            if(/^(?:logo|网站标志)$/i.test((img.getAttribute('alt')||'').trim()))return false;
            const box=img.getBoundingClientRect();const style=getComputedStyle(img);
            return box.width>0&&box.height>0&&style.visibility!=='hidden'&&style.display!=='none';
        }).map(img=>({src:img.currentSrc||img.src,ready:img.complete&&img.naturalWidth>0}))""")

    async def _verify_product_binding(self, page):
        # 当前编辑器里的唯一商品卡必须可读回准确 ID，搜索页候选卡不是绑定凭据。
        editor = await _unique(page.locator(self.editor_selector), "商家笔记正文编辑器")
        container = editor.locator('xpath=ancestor::*[contains(concat(" ", normalize-space(@class), " "), " container ")][1]')
        container = await _unique(container, "商家笔记编辑区域")
        cards = await self._product_cards(container)
        if len(cards) != 1 or cards[0][1] != self.options["product_id"]:
            raise PreparationError("无法核实编辑器内已关联的准确商品 ID，已阻止发布；请检查商家商品卡")
        candidate_action = cards[0][0].get_by_text("去发笔记", exact=True)
        if await candidate_action.count():
            raise PreparationError("页面仍显示搜索候选商品，不能当作已关联商品，已阻止发布")

    async def verify_note(self, page):
        await read_merchant_store_name(page, self.options["shop_name"])
        await self._verify_product_binding(page)
        await super().verify_note(page)

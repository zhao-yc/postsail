"""统一文章任务适配入口；准备验证与正式提交严格分开。"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from utils.articles.browser import (
    PreparationError, insert_body_images, install_preview_guard, install_native_preview_request_guard, is_uploaded_image,
    prepare_and_paste_document, read_result_evidence, save_screenshot, launch_article_browser,
    validate_assets, verify_rich_structure, inspect_content,
)
from utils.articles.model import (PLATFORMS, validate_options, validate_platform_content,
    validate_platform_cover, option_asset_ids, validate_option_asset, validate_title_characters)


TITLE_LIMITS = {name: (rules["title_min"], rules["title_max"]) for name, rules in PLATFORMS.items()}


def validate_task(snapshot: dict, assets: dict) -> Path | None:
    """进入浏览器前校验平台约束，避免旧类静默截断标题或跳过封面。"""
    platform = snapshot.get("platform")
    if platform not in TITLE_LIMITS:
        raise ValueError("不支持的文章发布平台")
    rules = PLATFORMS[platform]
    low, high = TITLE_LIMITS[platform]
    title = str(snapshot.get("title", "")).strip()
    if not low <= len(title) <= high:
        raise ValueError(f"{rules['label']}文章标题须为 {low}-{high} 个字符")
    validate_title_characters(platform, title)
    if snapshot.get("mode") not in {"preview", "publish"}:
        raise ValueError("文章任务只能选择预览或立即发布")
    if snapshot.get("publish_date", 0) != 0:
        raise ValueError("文章暂不支持定时发布")
    options = snapshot.get("options") or {}
    if not isinstance(options, dict):
        raise ValueError("平台 options 必须为对象")
    if "ai_generated" in options and not isinstance(options["ai_generated"], bool):
        raise ValueError("AI 创作声明必须为布尔值")
    if any(options.get(key) for key in ("schedule", "publish_date", "enableTimer")):
        raise ValueError("文章暂不支持定时发布")
    validate_options(platform, options)
    asset_fields = {field["name"]: field for field in rules["option_fields"] if field["type"] == "asset"}
    for name, asset_id in option_asset_ids(platform, options).items():
        extra = assets.get(asset_id)
        if not extra:
            raise ValueError(f"{asset_fields[name]['label']}素材不存在")
        extra_path = Path(extra.get("path", ""))
        if not extra_path.is_absolute() or not extra_path.is_file():
            raise ValueError(f"{asset_fields[name]['label']}文件不存在")
        validate_option_asset(asset_fields[name], {**extra, "size": extra_path.stat().st_size})
    tags = snapshot.get("tags") or []
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError("文章话题必须为文本数组")
    validate_platform_content(platform, snapshot.get("content_html", ""), tags)
    parsed = inspect_content(snapshot.get("content_html", ""))
    if rules.get("body_max_images") and len(parsed.asset_ids) > rules["body_max_images"]:
        raise ValueError(f"{rules['label']}正文最多包含 {rules['body_max_images']} 张图片")
    # 转换后的文本还会由平台读回校验，此处先拒绝已知超限的原稿。
    if rules.get("body_max_chars") and len("".join(parsed.text)) > rules["body_max_chars"]:
        raise ValueError(f"{rules['label']}正文最多 {rules['body_max_chars']} 字")
    if rules.get("tags_max") and len(snapshot.get("tags") or []) > rules["tags_max"]:
        raise ValueError(f"{rules['label']}最多选择 {rules['tags_max']} 个话题")
    if platform in {"douyin", "chejiahao"} and parsed.links and not options.get("links_as_text"):
        raise ValueError(f"{rules['label']}原生文章不支持正文超链接，请启用“将不支持的超链接转为文字和完整网址”选项")
    validate_assets(snapshot.get("content_html", ""), assets)
    cover_id = snapshot.get("cover_asset_id")
    if cover_id and rules.get("cover_supported") is False:
        raise ValueError(f"{rules['label']}文章不支持单独设置封面")
    if not cover_id:
        if rules["cover_required"]:
            raise ValueError(f"{rules['label']}文章必须选择展示封面")
        return None
    asset = assets.get(cover_id)
    if not asset:
        raise ValueError("封面素材不存在")
    path = Path(asset.get("path", ""))
    if not path.is_absolute() or not path.is_file():
        raise ValueError("封面文件不存在")
    if asset.get("mime_type") not in {"image/jpeg", "image/png"}:
        raise ValueError("文章封面须为 JPEG 或 PNG 图片")
    maximum = PLATFORMS[platform]["cover_max_bytes"]
    if path.stat().st_size > maximum:
        raise ValueError(f"{rules['label']}封面不能超过 {maximum // 1024 // 1024}MB")
    if (int(asset.get("width") or 0) <= rules["cover_min_width"] or
            int(asset.get("height") or 0) <= rules["cover_min_height"]):
        raise ValueError(f"{rules['label']}封面尺寸不足，请检查平台要求")
    validate_platform_cover(platform, asset)
    if platform == "jingdong":
        first_id = parsed.asset_ids[0] if parsed.asset_ids else None
        first = {**assets[first_id], "id": first_id} if first_id else None
        validate_platform_cover(platform, {**asset, "id": cover_id}, first)
    return path


def _create_app(snapshot: dict, account_file: Path, cover: Path | None):
    """复用现有文章类的标题、封面、话题和平台声明处理。"""
    platform = snapshot["platform"]
    options = snapshot.get("options") or {}
    if options.get("statement") and options["statement"] not in PLATFORMS[platform]["statement_options"]:
        raise ValueError("平台声明不支持，不能忽略或回退，请重新选择")
    shared = dict(title=snapshot["title"].strip(), body="文章富文本",
                  tags=snapshot.get("tags") or [], publish_date=0,
                  account_file=str(account_file), dry_run=snapshot["mode"] == "preview",
                  cover_path=str(cover) if cover else None)
    if platform == "baijiahao":
        from uploader.baijiahao_uploader.main import BaiJiaHaoArticle
        return BaiJiaHaoArticle(**shared, ai_generated=bool(options.get("ai_generated")))
    if platform == "zhihu":
        from uploader.zhihu_uploader.main import ZhiHuArticle
        app = ZhiHuArticle(**shared, creation_statement=options.get("statement"))
        statement = app.creation_statement
    elif platform == "toutiao":
        from uploader.toutiao_uploader.main import TouTiaoArticle
        app = TouTiaoArticle(**shared, work_statements=options.get("statement"))
        statement = app.work_statements[0] if app.work_statements else ""
    elif platform == "sohu":
        from uploader.sohu_uploader.main import SoHuArticle
        app = SoHuArticle(**shared, info_source=options.get("statement"))
        statement = app.info_source
    else:
        raise ValueError("不支持的旧文章适配平台")
    if options.get("statement") and statement != options["statement"]:
        raise ValueError("平台声明不支持，不能忽略或回退，请重新选择")
    return app


async def _open_editor(platform: str, app, page):
    """打开各平台真实文章页，只在提交前允许备用导航入口。"""
    if platform == "baijiahao":
        await app._open_article_page(page)
        editor = await app._wait_for_body_editor(page)
    elif platform == "zhihu":
        from uploader.zhihu_uploader.main import ZHIHU_WRITE_URL, _is_login_url
        await page.goto(ZHIHU_WRITE_URL, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        if _is_login_url(page.url):
            raise PreparationError("知乎登录已失效，请重新登录账号")
        editor = None
        for selector in (".public-DraftEditor-content", ".ProseMirror", ".ql-editor",
                         '[contenteditable="true"]'):
            candidate = page.locator(selector).first
            if await candidate.count() and await candidate.is_visible():
                editor = candidate
                break
    elif platform == "toutiao":
        from uploader.toutiao_uploader.main import TOUTIAO_ARTICLE_URL, _dismiss_overlays
        await page.goto(TOUTIAO_ARTICLE_URL, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)
        if "/login" in page.url or "sso.toutiao.com" in page.url:
            raise PreparationError("今日头条登录已失效，请重新登录账号")
        await _dismiss_overlays(page)
        _frame, editor = await app._find_editor(page)
    elif platform == "sohu":
        await app._open_article_editor(page)
        _frame, editor = await app._find_editor(page)
    else:
        raise PreparationError("文章平台没有注册编辑器")
    if editor is None:
        raise PreparationError("未找到平台文章编辑器；请检查登录、权限或页面变化")
    return editor


async def _apply_options(platform: str, app, page, editor) -> None:
    """正文准备完成后复用平台封面、声明及标签步骤。"""
    if platform == "baijiahao":
        await app.insert_topics_in_body(page, editor)
        await app.handle_cover(page)
        await app.apply_ai_declaration(page)
    elif platform == "zhihu":
        if app.cover_path:
            await app.upload_cover(page)
        await app.apply_creation_statement(page)
        if app.tags:
            await _prepare_native_tags(page, app.tags)
    elif platform == "toutiao":
        await app.insert_topics_in_body(page, editor)
        await app.handle_cover(page)
        await app.apply_work_statements(page)
    elif platform == "sohu":
        await app.fill_tags(page)
        await app.handle_cover(page)
        await app.apply_info_source(page)
    else:
        raise PreparationError("文章平台没有注册选项处理器")
    await _verify_tags(platform, page, editor, app.tags)


async def _verify_title(page, expected: str) -> None:
    """读取可见标题控件，不因填充函数没有抛错就认为标题已写入。"""
    values = await page.locator('input[placeholder*="标题"],textarea[placeholder*="标题"],'
        'input[placeholder*="字符"],input[name="title"],.title-input input,'
        'div.input-box [contenteditable="true"]').evaluate_all("""elements=>elements
            .filter(el=>{const box=el.getBoundingClientRect();const style=getComputedStyle(el);
                return box.width>0&&box.height>0&&style.display!=='none'&&style.visibility!=='hidden';})
            .map(el=>el.value===undefined ? (el.innerText||'').trim() : el.value.trim())""")
    if expected.strip() not in values:
        raise PreparationError("平台标题读回不一致，已阻止发布")


async def _prepare_native_tags(page, tags: list[str]) -> None:
    """知乎只选择明确的话题候选，页面没有原生入口时返回需要人工处理。"""
    for label in ("添加话题", "选择话题"):
        opener = page.get_by_role("button", name=label, exact=True).first
        if await opener.count() and await opener.is_visible():
            await opener.click(timeout=5000)
            break
    field = None
    for selector in ('input[placeholder*="搜索话题"]', 'input[placeholder*="添加话题"]',
                     'input[placeholder*="话题"]'):
        candidate = page.locator(selector).first
        if await candidate.count() and await candidate.is_visible():
            field = candidate
            break
    if field is None:
        raise PreparationError("知乎未找到可核验的话题入口；请移除话题或在平台人工设置")
    for tag in tags:
        await field.fill(str(tag).strip().lstrip("#"))
        await page.wait_for_timeout(500)
        option = page.get_by_role("option", name=str(tag).strip().lstrip("#"), exact=True).first
        if not await option.count() or not await option.is_visible():
            raise PreparationError(f"知乎未找到精确话题候选：{tag}；已阻止发布")
        await option.click(timeout=5000)
    await page.keyboard.press("Escape")


async def _verify_tags(platform: str, page, editor, tags: list[str]) -> None:
    """仅把真实话题节点或可移除的已选标签当作选中，不认纯文本 #。"""
    tags = list(dict.fromkeys(str(tag).strip().lstrip("#") for tag in tags if str(tag).strip()))
    if not tags:
        return
    limits = {"baijiahao": 5, "toutiao": 10, "sohu": 10, "zhihu": 5}
    if len(tags) > limits[platform]:
        raise PreparationError(f"{PLATFORMS[platform]['label']}当前适配最多验证 {limits[platform]} 个话题，已阻止发布")
    if platform in {"baijiahao", "toutiao"}:
        selector = ('a[data-bjh-box="topic"]' if platform == "baijiahao" else
                    '[data-topic],[data-hashtag],[class*="topic"],[class*="hashtag"],a[href*="topic"]')
        selected = await editor.locator(selector).evaluate_all("""elements=>elements.map(el=>
            (el.innerText||'').trim().replace(/^#+|#+$/g,''))""")
    else:
        selected = await page.locator('[aria-selected="true"],[data-selected="true"],.el-tag,'
            '[class*="Tag"],[class*="tag"]').evaluate_all("""elements=>elements.filter(el=>{
                if(el.closest('[role="option"],[role="listbox"]'))return false;
                return el.matches('[aria-selected="true"],[data-selected="true"],.el-tag') ||
                    el.querySelector('[aria-label*="删除"],[class*="remove"],[class*="Remove"],[class*="close"]');
            }).map(el=>(el.innerText||'').trim().replace(/[×✕]$/,'').trim().replace(/^#+|#+$/g,''))""")
    missing = [tag for tag in tags if tag not in selected]
    if missing:
        raise PreparationError("未确认平台已选话题：" + "、".join(missing) + "；已阻止发布")


async def _verify_options(platform: str, app, page, cover: Path | None) -> None:
    """旧上传函数可能只记录警告，统一入口必须读回封面和显式声明。"""
    if cover:
        if platform == "baijiahao":
            candidates = await page.locator('img[src*="picproxy"]').evaluate_all("""images=>images
                .filter(img=>!img.closest('.news-editor-pc,.edui-editor,[contenteditable="true"]'))
                .map(img=>({src:img.src,ready:img.complete&&img.naturalWidth>0,
                    width:img.getBoundingClientRect().width,height:img.getBoundingClientRect().height}))""")
            ready = (not await app._cover_placeholder_visible(page) and
                     any(item["width"] >= 80 and item["height"] >= 60 and
                         is_uploaded_image(item, platform) for item in candidates))
        elif platform == "toutiao":
            state = await app._cover_state(page)
            source = (state.get("preview") or {}).get("src", "")
            match = re.search(r'https?://[^"\'()\s]+', source)
            ready = bool(state.get("ready") and not state.get("empty") and match and
                         is_uploaded_image({"src": match.group(0), "ready": True}, platform))
        elif platform == "sohu":
            candidate = await page.evaluate("""() => {
                const pic=document.querySelector('.pic-cover');if(!pic)return null;
                const style=getComputedStyle(pic);const match=style.backgroundImage.match(/url\(["']?(https?:[^"')]+)/);
                return match ? {src:match[1],ready:style.display!=='none'} : null;
            }""")
            ready = bool(candidate and is_uploaded_image(candidate, platform))
        else:
            candidates = await page.evaluate("""() => {
                const images=document.querySelectorAll('[class*="Cover"] img,[class*="cover"] img');
                return Array.from(images).map(img=>({src:img.src,ready:img.complete&&img.naturalWidth>0}));
            }""")
            ready = any(is_uploaded_image(item, platform) for item in candidates)
        if not ready:
            raise PreparationError("未确认平台封面已设置，已阻止发布")
    if platform == "zhihu":
        expected = app.creation_statement
        row = page.locator('div:has(> label:has-text("创作声明"))').first
        combo = row.locator('button[role="combobox"],button.Select-button').first
        if (not await row.count() or not await combo.count() or
                re.sub(r"\s+", "", await combo.inner_text()) != re.sub(r"\s+", "", expected)):
            raise PreparationError("未确认知乎创作声明，已阻止发布")
    elif platform == "baijiahao" and app.ai_generated:
        checked = await _selected_statement(page, "采用AI生成内容")
        if not checked:
            raise PreparationError("未确认百家号 AI 创作声明，已阻止发布")
    elif platform == "toutiao" and app.work_statements:
        checked = await _selected_statement(page, app.work_statements[0])
        if not checked:
            raise PreparationError("未确认今日头条作品声明，已阻止发布")
    elif platform == "sohu":
        checked = await _selected_statement(page, app.info_source)
        if not checked:
            raise PreparationError("未确认搜狐信息来源，已阻止发布")


async def _selected_statement(page, expected: str) -> bool:
    """读取原生选中状态，不能仅因为页面出现选项文本就认为已选择。"""
    return await page.evaluate("""expected => {
        const nodes=Array.from(document.querySelectorAll('label,[role="radio"],[class*="radio"],[class*="checkbox"]'));
        const norm=text=>(text||'').replace(/\s/g,'');
        return nodes.some(el=>norm(el.innerText||el.getAttribute('aria-label'))===norm(expected) &&
            (el.matches('[aria-checked="true"]') || el.querySelector('input:checked,[aria-checked="true"]') ||
             /(^|[\s_-])(checked|selected)($|\s)/.test(el.className)));
    }""", expected)


async def _submit_once(page, on_submit) -> None:
    """提交边界先持久化，再点击一次；按钮异常后绝不切换候选重发。"""
    buttons = []
    for candidate in (page.get_by_role("button", name="发布", exact=True),
                      page.get_by_role("button", name="立即发布", exact=True)):
        for index in range(await candidate.count()):
            target = candidate.nth(index)
            if await target.is_visible() and await target.is_enabled():
                buttons.append(target)
    if len(buttons) != 1:
        raise PreparationError("未找到唯一可用的发布按钮，已阻止提交")
    button = buttons[0]
    await button.scroll_into_view_if_needed()
    on_submit()
    await button.click(timeout=10000)
    await page.wait_for_timeout(800)
    # 仅处理已经出现的明确二次确认；不重试第一次发布操作。
    dialog = page.locator('[role="dialog"]:visible,.ant-modal:visible,.el-dialog:visible').last
    if await dialog.count() and "发布" in await dialog.inner_text():
        confirm = dialog.get_by_role("button", name=re.compile(r"^(确认发布|确定发布|确认|确定)$")).first
        if await confirm.count() and await confirm.is_visible():
            await confirm.click(timeout=10000)
    await page.wait_for_timeout(3000)


async def _verify_final_body(editor, document, platform: str, tags: list[str] | None = None,
                             rich_verifier=None, image_verifier=None, document_reader=None) -> None:
    """封面及话题操作后完整校验正文，仅允许已核实的请求话题后缀。"""
    from utils.articles.browser import normalize_text, is_uploaded_image, body_sequence, inspect_text
    # 原生状态读回只替代 DOM 提取，全文、图片数量与顺序的比较仍在本层执行。
    # 例如 Lexical 的放大镜副本和图片工具栏并不是第二张正文图片或正文文字。
    state = await document_reader(editor) if document_reader else None
    actual = state["text"] if state is not None else await body_sequence(editor, platform, include_images=False)
    suffix = ""
    topic_selectors = {
        "baijiahao": 'a[data-bjh-box="topic"]',
        "toutiao": '[data-topic],[data-hashtag],[class*="topic"],[class*="hashtag"],a[href*="topic"]',
        "bilibili": 'a[data-type="topic"],span[data-type="topic"]',
    }
    requested = list(dict.fromkeys(str(tag).strip().strip("#") for tag in (tags or []) if str(tag).strip()))
    if normalize_text(actual) != normalize_text(document.expected_text) and requested and platform in topic_selectors:
        # 必须来自官方话题节点且按请求顺序完整匹配；不把纯文本、警告或其它尾注当作话题。
        selected = await editor.locator(topic_selectors[platform]).evaluate_all("""elements=>
            elements.filter(el=>!elements.some(parent=>parent!==el&&parent.contains(el)))
                .map(el=>(el.textContent||'').trim())""")
        if [text.strip().strip("#") for text in selected] == requested:
            suffix = "".join(selected)
    if normalize_text(actual) != normalize_text(document.expected_text + suffix):
        raise PreparationError("平台选项设置后正文不一致，已阻止发布")
    if any(marker in actual for marker in document.markers):
        raise PreparationError("正文仍有未替换的图片标记，已阻止发布")
    images = state["images"] if state is not None else await editor.evaluate("""el=>Array.from(el.querySelectorAll('img')).map(img=>({
        src:img.src,ready:img.complete&&img.naturalWidth>0}))""")
    if len(images) != len(document.image_paths) or not all(item["ready"] for item in images):
        raise PreparationError("正文图片读回不完整，已阻止发布")
    # 部分官方编辑器始终显示本地预览；仅该平台的专用验证器可用本次
    # 上传回执及原生素材标识证明持久化，不能全局将 data/blob 当成上传成功。
    if image_verifier:
        await image_verifier(editor, images, document)
    elif not all(is_uploaded_image(item, platform) for item in images):
        raise PreparationError("正文图片读回不完整，已阻止发布")
    if [item["src"] for item in images] != document.uploaded_urls:
        raise PreparationError("正文图片地址或顺序发生变化，已阻止发布")
    sequence = state["sequence"] if state is not None else await body_sequence(editor, platform)
    if normalize_text(sequence) != normalize_text(inspect_text(document.paste_html) + suffix):
        raise PreparationError("正文图片与相邻段落的位置发生变化，已阻止发布")
    # Draft/Braft 的展示 DOM 用 span 样式表达粗体；原生适配器可以校验编辑器
    # 导出的富文本。可见文字、图片 URL、数量与相邻段落仍须通过上面的统一核验。
    await (rich_verifier or verify_rich_structure)(editor, document.paste_html)



class LegacyArticleAdapter:
    """旧四平台以相同接口接入，保留已验证的正文准备与平台选项逻辑。"""

    def __init__(self, snapshot, account_file, cover):
        self.platform = snapshot["platform"]
        self.app = _create_app(snapshot, account_file, cover)
        self.title = self.app.title
        self.cover = cover

    async def open_editor(self, page):
        """只调用明确注册的旧平台编辑器。"""
        return await _open_editor(self.platform, self.app, page)

    async def fill_title(self, page):
        """复用平台标题输入，再由统一流程读回验证。"""
        await self.app.fill_title(page)

    async def verify_title(self, page):
        """避免旧上传类静默截断标题。"""
        await _verify_title(page, self.title)

    async def apply_options(self, page, editor):
        """应用封面、话题和声明。"""
        await _apply_options(self.platform, self.app, page, editor)

    async def verify_options(self, page, editor):
        """读取平台最终选项状态。"""
        await _verify_options(self.platform, self.app, page, self.cover)

    async def submit(self, page, on_submit):
        """正式提交一次，交由任务服务保护幂等边界。"""
        await _submit_once(page, on_submit)

    async def read_result(self, page):
        """仅认可平台回执或已打开的公开文章。"""
        return await read_result_evidence(page, self.platform, self.title)


def create_adapter(snapshot, account_file, cover):
    """按实际实现分派；待接入的平台不得进入通用提交或其他平台实现。"""
    from utils.articles.native import create_native_adapter
    from utils.articles.extended_platforms import EXTENDED_PLATFORMS
    platform = snapshot.get("platform")
    if platform in PLATFORMS and PLATFORMS[platform].get("available") is False:
        raise ValueError(PLATFORMS[platform]["reason"])
    factories = {name: LegacyArticleAdapter for name in ("baijiahao", "zhihu", "toutiao", "sohu")}
    factories.update({name: lambda data, _account, image: create_native_adapter(data, image)
                      for name in ("douyin", "bilibili", "weibo", "qiehao", *EXTENDED_PLATFORMS)})
    factory = factories.get(snapshot.get("platform"))
    if factory is None:
        raise ValueError("不支持的文章发布平台")
    return factory(snapshot, account_file, cover)


async def _run(snapshot, account_file, assets, on_submit, evidence_dir):
    """执行单个账户任务；提交后异常保持未知，交给用户核对平台记录。"""
    import conf
    from playwright.async_api import async_playwright
    from utils.base_social_media import set_init_script

    platform = snapshot["platform"]
    cover = validate_task(snapshot, assets)
    adapter = create_adapter(snapshot, account_file, cover)
    adapter.option_assets = {name: Path(assets[asset_id]["path"])
                             for name, asset_id in option_asset_ids(platform, snapshot.get("options", {})).items()}
    evidence_dir.mkdir(parents=True, exist_ok=True)
    result = dict(status="failed", message="文章任务未完成", platform_id=None,
                  platform_url=None, platform_status=None, evidence=[], prepared_html=None)
    submitted = False

    def mark_submitted():
        """主线程回调成功后才允许第一次可能产生正式文章的操作。"""
        nonlocal submitted
        on_submit()
        submitted = True

    from utils.articles.session import load_article_storage_state
    storage_state = load_article_storage_state(platform, account_file)
    async with async_playwright() as playwright:
        browser = await launch_article_browser(playwright,
            bool(getattr(conf, "ARTICLE_BROWSER_HEADLESS", getattr(conf, "LOCAL_CHROME_HEADLESS", False))),
            getattr(conf, "LOCAL_CHROME_PATH", ""))
        context = page = editor = None
        document = None
        request_guard = False
        try:
            context = await browser.new_context(storage_state=storage_state, locale="zh-CN", service_workers="block",
                                                viewport={"width": 1440, "height": 1000})
            if platform != "sohu":
                context = await set_init_script(context)
            page = await context.new_page()
            render_page = await context.new_page()
            preparation_guard = getattr(adapter, "install_preparation_guard", None)
            if preparation_guard:
                # 个别编辑器需先打开发布设置窗口；平台专属请求保护在导航前生效。
                await preparation_guard(page)
            if snapshot["mode"] == "preview":
                request_guard = await install_native_preview_request_guard(page, platform)
                if not request_guard and not preparation_guard:
                    await install_preview_guard(page)
            editor = await adapter.open_editor(page)
            if snapshot["mode"] == "preview" and not request_guard and not preparation_guard:
                await install_preview_guard(page)
            await page.bring_to_front()
            # 原生适配器可安排平台专属的准备顺序，最终仍统一读回所有内容。
            prepare_editor = getattr(adapter, "prepare_editor", None)
            if prepare_editor:
                await prepare_editor(page)
            if request_guard and not preparation_guard:
                # 封面准备时请求层已经禁止提交；完成后再禁用编辑器发布按钮。
                await install_preview_guard(page)
            await adapter.fill_title(page)
            await adapter.verify_title(page)

            def remember_prepared(document):
                """即使平台拒绝新版本，也保留最终转换稿和分段图片证据。"""
                result["prepared_html"] = document.prepared_html
                result["evidence"] = list(document.generated_files)
                # 只保存文章内容用于核对平台转换，不记录会话或请求凭据。
                (evidence_dir / "expected-body.html").write_text(document.paste_html, encoding="utf-8")
                rules = PLATFORMS[platform]
                if rules.get("body_max_images") and len(document.image_paths) > rules["body_max_images"]:
                    raise PreparationError(f"{rules['label']}转换后正文图片超过 {rules['body_max_images']} 张，请减少表格或代码分段")
                if rules.get("body_max_chars") and len(document.expected_text) > rules["body_max_chars"]:
                    raise PreparationError(f"{rules['label']}转换后正文超过 {rules['body_max_chars']} 字，请调整原稿")

            document = await prepare_and_paste_document(
                page, editor, render_page, snapshot["content_html"], assets, evidence_dir,
                getattr(conf, "ARTICLE_RENDER_FONT", "Noto Sans CJK SC,PingFang SC,Microsoft YaHei,sans-serif"),
                on_prepared=remember_prepared,
                links_as_text=bool((snapshot.get("options") or {}).get("links_as_text")),
                paste_handler=getattr(adapter, "paste_document", None))
            native_images = getattr(adapter, "insert_body_images", None)
            if native_images:
                await native_images(page, editor, render_page, document)
            else:
                await insert_body_images(page, editor, render_page, document, platform)
            await adapter.apply_options(page, editor)
            if snapshot["mode"] == "preview" and preparation_guard:
                await install_preview_guard(page)
            await adapter.verify_options(page, editor)
            await adapter.verify_title(page)
            await _verify_final_body(
                editor, document, platform, snapshot.get("tags") or [],
                rich_verifier=getattr(adapter, "verify_rich_document", None),
                image_verifier=getattr(adapter, "verify_uploaded_images", None),
                document_reader=getattr(adapter, "read_document_state", None))
            verify_body = getattr(adapter, "verify_body", None)
            if verify_body:
                await verify_body(page, editor, document)
            name = await save_screenshot(page, evidence_dir, "prepared.png")
            if name:
                result["evidence"].append(name)
            if snapshot["mode"] == "preview":
                result.update(status="previewed", message="平台预览已完成；平台可能自动保存草稿，未提交发布")
                seconds = max(0, min(120, int(getattr(conf, "ARTICLE_PREVIEW_SECONDS", 0))))
                if seconds:
                    await asyncio.sleep(seconds)
            else:
                await adapter.submit(page, mark_submitted)
                for _ in range(20):
                    state = await adapter.read_result(page)
                    if state["status"] != "unknown":
                        break
                    await page.wait_for_timeout(500)
                result.update(state)
                name = await save_screenshot(page, evidence_dir, "result.png")
                if name:
                    result["evidence"].append(name)
            # biliup 会话仍由其登录/renew 维护，不能用浏览器 state 覆盖 token_info。
            if platform != "bilibili":
                await context.storage_state(path=str(account_file))
        except Exception as exc:
            name = await save_screenshot(page, evidence_dir, "error.png") if page else None
            if name:
                result["evidence"].append(name)
            if editor is not None:
                try:
                    # 正文差异须可复查，不能只用截图判断内容完整。
                    diagnostic = {"text": await editor.inner_text(timeout=3000),
                                  "html": await editor.inner_html(timeout=3000)}
                    (evidence_dir / "body-readback.json").write_text(
                        json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
                    result["evidence"].append("body-readback.json")
                except Exception:
                    pass
            result.update(status="unknown" if submitted else "needs_action",
                          message=("已尝试提交，请先核对平台记录：" if submitted else "文章准备未完成：") + str(exc))
        finally:
            try:
                if context is not None:
                    await context.close()
            finally:
                await browser.close()
    return result


def run_article_task(snapshot: dict, account_file: Path, assets: dict[str, dict],
                     on_submit, evidence_dir: Path) -> dict:
    """提供后端工作线程可调用的同步入口，不执行其他账户或隐式重试。"""
    validate_task(snapshot, assets)
    return asyncio.run(_run(snapshot, Path(account_file), assets, on_submit, Path(evidence_dir)))

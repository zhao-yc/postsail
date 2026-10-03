"""文章浏览器操作：富文本粘贴、平台图片上传和可核验的结果读取。"""
from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class PreparationError(RuntimeError):
    """平台编辑器未完成准备，必须阻止正式提交。"""


async def launch_article_browser(playwright, headless: bool, executable_path: str = ""):
    """显式路径优先；无路径时先系统 Chrome，只在未安装时回退 Chromium。"""
    options = {"headless": headless,
               "args": ["--disable-blink-features=AutomationControlled", "--lang=zh-CN",
                        "--disable-infobars"]}
    if executable_path:
        path = Path(executable_path).expanduser()
        if not path.is_file():
            raise PreparationError("配置的 Chrome 路径不存在，请修正 LOCAL_CHROME_PATH 或清空该配置")
        if os.name != "nt" and not os.access(path, os.X_OK):
            raise PreparationError("配置的 Chrome 文件不可执行，请检查 LOCAL_CHROME_PATH 和文件权限")
        return await playwright.chromium.launch(**options, executable_path=str(path))
    try:
        return await playwright.chromium.launch(**options, channel="chrome")
    except Exception as exc:
        message = str(exc).lower()
        if not any(term in message for term in ("distribution 'chrome' is not found", "executable doesn't exist")):
            raise
    try:
        return await playwright.chromium.launch(**options)
    except Exception as exc:
        if "executable doesn't exist" not in str(exc).lower():
            raise
        raise PreparationError("没有可用浏览器；请安装系统 Chrome、配置 LOCAL_CHROME_PATH，或执行 python -m playwright install chromium") from exc


class _ContentParser(HTMLParser):
    """提取受控文章的文本、格式与素材引用，不下载外部地址。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.asset_ids = []
        self.links = []
        self.tags = {}
        self.format_segments = []
        self._active_formats = []

    def handle_starttag(self, tag, attrs):
        self.tags[tag] = self.tags.get(tag, 0) + 1
        if tag in {"script", "style", "iframe", "object", "embed", "form"}:
            raise ValueError("文章包含不支持的活动内容")
        values = dict(attrs)
        if any(key.startswith("on") for key in values):
            raise ValueError("文章包含不安全的事件属性")
        if tag == "img":
            asset_id = values.get("data-asset-id")
            if not asset_id:
                raise ValueError("正文图片必须先导入文章素材库")
            self.asset_ids.append(asset_id)
        if tag == "a" and values.get("href"):
            href = values["href"]
            if urlparse(href).scheme not in {"https", "http"}:
                raise ValueError("文章链接须为完整的 HTTP/HTTPS 地址")
            self.links.append(href)
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "u", "s", "strong", "b", "em", "i", "a", "code", "pre", "table", "tr", "td", "th"}:
            block_code = tag == "pre" or (tag == "code" and any(
                item["tag"] == "pre" for item in self._active_formats))
            self._active_formats.append({"tag": tag, "text": [], "block_code": block_code})

    def handle_endtag(self, tag):
        for index in range(len(self._active_formats) - 1, -1, -1):
            segment = self._active_formats[index]
            if segment["tag"] == tag:
                self.format_segments.append({"tag": tag, "text": "".join(segment["text"]),
                                             "block_code": segment["block_code"]})
                self._active_formats.pop(index)
                break

    def handle_data(self, data):
        self.text.append(data)
        for segment in self._active_formats:
            segment["text"].append(data)


def inspect_content(content_html: str) -> _ContentParser:
    """校验文章引用；图片未导入时不能使用外链代替本地素材。"""
    parsed = _ContentParser()
    parsed.feed(content_html or "")
    parsed.close()
    if not "".join(parsed.text).strip() and not parsed.asset_ids:
        raise ValueError("文章正文不能为空")
    return parsed


def validate_assets(content_html: str, assets: dict) -> None:
    """在打开平台之前确认所有正文图片真实存在。"""
    for asset_id in inspect_content(content_html).asset_ids:
        asset = assets.get(asset_id)
        if not asset:
            raise ValueError(f"正文图片素材不存在：{asset_id}")
        path = Path(asset.get("path", ""))
        if not path.is_absolute() or not path.is_file():
            raise ValueError(f"正文图片文件不存在：{asset_id}")
        if not str(asset.get("mime_type", "")).startswith("image/"):
            raise ValueError(f"正文素材不是图片：{asset_id}")


@dataclass
class PreparedDocument:
    """平台预览版本与依次插入正文的图片文件。"""

    prepared_html: str
    paste_html: str
    expected_text: str
    image_paths: list[Path]
    markers: list[str]
    generated_files: list[str]
    uploaded_urls: list[str] = field(default_factory=list)


async def prepare_document(render_page, content_html: str, assets: dict,
                           evidence_dir: Path, font: str, preserve_blocks: bool = False,
                           links_as_text: bool = False) -> PreparedDocument:
    """在隔离的本地页把表格和代码分段截图，再生成可粘贴的文章。"""
    validate_assets(content_html, assets)
    # 禁止渲染文章时访问外部资源；原图只读取已验证的本地素材。
    await render_page.route("**/*", lambda route: route.abort())
    await render_page.set_content("<html><body><main id='article'></main></body></html>")
    local_images = {}
    for asset_id in inspect_content(content_html).asset_ids:
        asset = assets[asset_id]
        encoded = base64.b64encode(Path(asset["path"]).read_bytes()).decode("ascii")
        local_images[asset_id] = f"data:{asset['mime_type']};base64,{encoded}"
    await render_page.evaluate(
        """({content, images, font, linksAsText}) => {
            const root = document.getElementById('article');
            root.innerHTML = content;
            // 用户显式启用后保留链接文字及地址，原稿不会被改写。
            if (linksAsText) root.querySelectorAll('a[href]').forEach(link => {
                const target = link.getAttribute('href');
                const nodes = Array.from(link.childNodes);
                if (link.textContent.trim() !== target) nodes.push(document.createTextNode('（' + target + '）'));
                link.replaceWith(...nodes);
            });
            const style = document.createElement('style');
            style.textContent = `body{margin:24px;background:white;color:#111}
                #article{width:920px;font:18px/1.6 ${font}}
                table{border-collapse:collapse;width:100%;table-layout:fixed}
                td,th{border:1px solid #bbb;padding:10px;overflow-wrap:anywhere}
                pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f7f8;
                    border:1px solid #ddd;padding:18px;font:16px/26px monospace}
                img{max-width:100%;height:auto}`;
            document.head.appendChild(style);
            root.querySelectorAll('img').forEach(img => {
                const id = img.getAttribute('data-asset-id'); img.src = images[id];
            });
        }""", {"content": content_html, "images": local_images, "font": font,
                  "linksAsText": links_as_text})
    await render_page.evaluate("document.fonts.ready")
    await render_page.evaluate("Promise.all(Array.from(document.images).map(img=>img.decode()))")
    # 分段上限约 1200px；表格优先沿行边界，代码沿行高边界拆分。
    count = 0 if preserve_blocks else await render_page.locator("#article table, #article pre").count()
    generated = []
    generated_paths = {}
    for index in range(count):
        block = render_page.locator("#article table, #article pre").nth(index)
        slices = await block.evaluate(
            """el => {
                const box = el.getBoundingClientRect(), max = 1196;
                const points = [0];
                if (el.tagName === 'TABLE') {
                    el.querySelectorAll('tr').forEach(row => {
                        const end = row.getBoundingClientRect().bottom - box.top;
                        if(end>0) points.push(end);
                    });
                } else {
                    const line = parseFloat(getComputedStyle(el).lineHeight) || 26;
                    for(let y=line;y<box.height;y+=line) points.push(y);
                }
                points.push(box.height); const out=[]; let top=0;
                while(top < box.height-0.5) {
                    const target=Math.min(top+max,box.height);
                    const valid=points.filter(y=>y>top+1 && y<=target);
                    const end=valid.length ? Math.max(...valid) : target;
                    out.push({x:box.x+scrollX,y:box.y+scrollY+top,
                        width:Math.ceil(box.width),height:Math.ceil(end-top)});
                    top=end;
                }
                return out;
            }""")
        filenames = []
        for segment, clip in enumerate(slices):
            name = f"rendered-block-{index + 1}-{segment + 1}.png"
            path = evidence_dir / name
            await render_page.screenshot(path=str(path), clip=clip, full_page=True)
            generated.append(name)
            token = f"rendered-block-{index + 1}-{segment + 1}"
            generated_paths[token] = path
            filenames.append({"id": token, "src": "data:image/png;base64," +
                              base64.b64encode(path.read_bytes()).decode("ascii")})
        await block.evaluate(
            """(el, parts) => {
                const holder=document.createElement('div');
                for(const part of parts){const p=document.createElement('p');
                    const img=document.createElement('img');img.src=part.src;
                    img.setAttribute('data-asset-id',part.id);img.alt='表格或代码分段图';
                    p.appendChild(img);holder.appendChild(p);}
                // 先保留原元素，避免后续 nth 索引发生变化。
                el.setAttribute('data-rendered-block','1');el.after(holder);
            }""", filenames)
        await render_page.evaluate("Promise.all(Array.from(document.images).map(img=>img.decode()))")
    await render_page.evaluate("document.querySelectorAll('[data-rendered-block]').forEach(el=>el.remove())")
    prepared_html = await render_page.locator("#article").inner_html()
    # 普通原图的预览继续引用应用素材接口，转换图保留 data URI 供前端显示。
    for asset_id, local_uri in local_images.items():
        prepared_html = prepared_html.replace(local_uri, f"/api/article-assets/{asset_id}/content")
    image_ids = await render_page.locator("#article img").evaluate_all(
        "els => els.map(el=>el.getAttribute('data-asset-id'))")
    image_paths = [generated_paths[asset_id] if asset_id in generated_paths else
                   Path(assets[asset_id]["path"]) for asset_id in image_ids]
    markers = [f"OMNIPOSTIMAGE{i:04d}END" for i in range(len(image_ids))]
    expected_text = await render_page.locator("#article").inner_text()
    await render_page.locator("#article img").evaluate_all(
        """(els, markers) => els.forEach((el,i)=>el.replaceWith(document.createTextNode(markers[i])))""",
        markers)
    paste_html = await render_page.locator("#article").inner_html()
    return PreparedDocument(prepared_html, paste_html, expected_text, image_paths, markers, generated)


async def prepare_and_paste_document(page, editor, render_page, content_html: str,
                                     assets: dict, evidence_dir: Path, font: str,
                                     on_prepared=None, links_as_text: bool = False) -> PreparedDocument:
    """优先原生表格/代码，仅正文或格式核验失败时改为 PNG 版本重填。"""
    document = await prepare_document(render_page, content_html, assets, evidence_dir, font,
                                      preserve_blocks=True, links_as_text=links_as_text)
    if on_prepared:
        on_prepared(document)
    try:
        await paste_rich_html(page, editor, document)
    except PreparationError:
        # 此处尚未开始正文图片上传，更没有正式提交，重新填写不会重复发文。
        document = await prepare_document(render_page, content_html, assets, evidence_dir, font,
                                          preserve_blocks=False, links_as_text=links_as_text)
        if on_prepared:
            on_prepared(document)
        await paste_rich_html(page, editor, document)
    return document


async def paste_rich_html(page, editor, document: PreparedDocument) -> None:
    """使用原生富文本粘贴事件，让编辑器更新自身状态而非只改 DOM。"""
    await page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    await page.bring_to_front()
    await editor.click(force=True)
    await page.keyboard.press("ControlOrMeta+A")
    await page.keyboard.press("Backspace")
    await page.evaluate(
        """async ({content, text}) => {
            await navigator.clipboard.write([new ClipboardItem({
                'text/html': new Blob([content], {type:'text/html'}),
                'text/plain': new Blob([text], {type:'text/plain'})})]);
        }""", {"content": document.paste_html, "text": inspect_text(document.paste_html)})
    await page.keyboard.press("ControlOrMeta+V")
    await page.wait_for_timeout(700)
    content = await editor.inner_text()
    if normalize_text(content) != normalize_text(inspect_text(document.paste_html)):
        raise PreparationError("平台正文读回与文章不一致，已阻止发布；请核对平台编辑器")
    await verify_rich_structure(editor, document.paste_html)


async def verify_rich_structure(editor, expected_html: str) -> None:
    """校验每种排版及其文字、链接目标；选项操作后仍可再次调用。"""
    # 逐项校验基本排版；平台不接受时不能悄悄退成纯文本。
    parsed = inspect_content(expected_html)
    tags = parsed.tags
    requirements = [(tag, tag) for tag in ("h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "u", "s", "hr", "code", "pre", "table", "tr", "td", "th")]
    requirements += [
                    ("strong", "strong,b"), ("b", "strong,b"),
                    ("em", "em,i"), ("i", "em,i"), ("a", "a[href]")]
    for tag, selector in requirements:
        if tags.get(tag, 0) and await editor.locator(selector).count() < tags[tag]:
            raise PreparationError(f"平台未保留文章格式 {tag}，已阻止发布")
        if tags.get(tag, 0):
            without_markers = lambda value: re.sub(r"OMNIPOSTIMAGE\d{4}END", "", normalize_text(value))
            actual_texts = await editor.locator(selector).all_text_contents()
            texts = [without_markers(value) for value in actual_texts]
            for segment in parsed.format_segments:
                if segment["tag"] == tag and segment["block_code"]:
                    if normalize_code_text(segment["text"]) not in [normalize_code_text(value) for value in actual_texts]:
                        raise PreparationError("平台改变了代码块的缩进或换行，需转换为图片；已阻止发布")
                    continue
                if segment["tag"] == tag and without_markers(segment["text"]) and without_markers(segment["text"]) not in texts:
                    raise PreparationError(f"平台改变了文章格式 {tag} 对应的文字，已阻止发布")
    expected_links = parsed.links
    links_ready = await editor.evaluate("""(el, expected) => {
        const actual=Array.from(el.querySelectorAll('a[href]')).map(a=>a.href);
        return expected.every(href=>actual.includes(new URL(href).href));
    }""", expected_links)
    if not links_ready:
        raise PreparationError("平台未保留文章链接地址，已阻止发布")


def inspect_text(content_html: str) -> str:
    """取正文文本，用忽略排版空白的完整读回来校验原生粘贴。"""
    parsed = _ContentParser()
    parsed.feed(content_html)
    return "".join(parsed.text)


def normalize_text(text: str) -> str:
    """不同编辑器产生的段落空白不影响完整正文比较。"""
    return re.sub(r"[\s\u200b\ufeff]+", "", text or "")


def normalize_code_text(text: str) -> str:
    """代码只统一换行及编辑器零宽字符，保留缩进和内部空白。"""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u200b", "").replace("\ufeff", "")
    lines = text.split("\n")
    # 编辑器可额外产生首末一条空行，内部空行和行首缩进不得被忽略。
    if lines and not lines[0].strip():
        lines.pop(0)
    if lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


async def body_sequence(editor, platform: str | None = None, *, include_images: bool = True) -> str:
    """按正文顺序读回；仅排除已核实的编辑控件，平台警告仍须阻止发布。"""
    return await editor.evaluate("""(el, options) => {
        let index=0,out='';const visit=node=>{
            if(node.nodeType===Node.TEXT_NODE){out+=node.textContent;return;}
            if(node.nodeType!==Node.ELEMENT_NODE)return;
            // 抖音图片节点内的编辑按钮不是正文，不屏蔽其它按钮或警告文字。
            if(options.platform==='douyin' && node.matches('.node-image button[title="编辑图片"]')) return;
            // 公众号 ProseMirror 使用内部占位图支撑光标，它不是用户正文图片。
            if(options.platform==='wechat' && node.matches('img.ProseMirror-separator')) return;
            if(node.tagName==='IMG'){
                if(options.includeImages)out+='OMNIPOSTIMAGE'+String(index++).padStart(4,'0')+'END';return;
            }
            for(const child of node.childNodes)visit(child);
        };visit(el);return out;
    }""", {"platform": platform, "includeImages": include_images})


async def _clipboard_image(page, render_page, path: Path) -> None:
    """用本地隔离页将任意浏览器支持的图片转换为 PNG 剪贴板。"""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    suffix = path.suffix.lower()
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif"}.get(suffix, "image/png")
    png = await render_page.evaluate(
        """async uri => {
            const img=new Image();img.src=uri;await img.decode();
            const canvas=document.createElement('canvas');canvas.width=img.naturalWidth;
            canvas.height=img.naturalHeight;canvas.getContext('2d').drawImage(img,0,0);
            return canvas.toDataURL('image/png').split(',')[1];
        }""", f"data:{mime};base64,{encoded}")
    await page.bring_to_front()
    await page.evaluate(
        """async encoded => {
            const bytes=Uint8Array.from(atob(encoded),x=>x.charCodeAt(0));
            await navigator.clipboard.write([new ClipboardItem({
                'image/png':new Blob([bytes],{type:'image/png'})})]);
        }""", png)


async def insert_body_images(page, editor, render_page, document: PreparedDocument,
                             platform: str | None = None) -> None:
    """按正文位置原生粘贴图片，等待平台上传完成后再允许下一步。"""
    for index, (marker, path) in enumerate(zip(document.markers, document.image_paths)):
        selected = await editor.evaluate(
            """(el, marker) => {
                const walker=document.createTreeWalker(el,NodeFilter.SHOW_TEXT);let node;
                while(node=walker.nextNode()){const index=node.textContent.indexOf(marker);
                    if(index<0)continue; el.focus(); const range=document.createRange();
                    range.setStart(node,index);range.setEnd(node,index+marker.length);
                    const selection=window.getSelection();selection.removeAllRanges();
                    selection.addRange(range);return true;}
                return false;
            }""", marker)
        if not selected:
            raise PreparationError("正文图片定位标记丢失，已阻止发布")
        await _clipboard_image(page, render_page, path)
        await page.keyboard.press("ControlOrMeta+V")
        uploaded = False
        for _ in range(40):
            state = await editor.evaluate(
                """(el, platform) => Array.from(el.querySelectorAll('img'))
                    .filter(img=>platform!=='wechat'||!img.classList.contains('ProseMirror-separator')).map(img=>({
                    src:img.src||'',width:img.naturalWidth,
                    ready:img.complete && img.naturalWidth>0}))""", platform)
            if len(state) == index + 1 and all(is_uploaded_image(item, platform) for item in state):
                if [item["src"] for item in state[:-1]] != document.uploaded_urls:
                    raise PreparationError("平台改变了已上传正文图片的顺序，已阻止发布")
                document.uploaded_urls.append(state[-1]["src"])
                uploaded = True
                break
            await page.wait_for_timeout(500)
        if not uploaded:
            raise PreparationError("平台正文图片上传未确认完成，已阻止发布；请检查预览截图")
    actual = await body_sequence(editor, platform, include_images=False)
    if any(marker in actual for marker in document.markers):
        raise PreparationError("平台没有替换正文图片标记，已阻止发布")
    if normalize_text(actual) != normalize_text(document.expected_text):
        raise PreparationError("插图后正文内容不一致，已阻止发布")
    if normalize_text(await body_sequence(editor, platform)) != normalize_text(inspect_text(document.paste_html)):
        raise PreparationError("正文图片位置与相邻段落不一致，已阻止发布")


IMAGE_HOST_SUFFIXES = {
    "douyin": ("douyinpic.com", "douyin.com", "byteimg.com", "ibytedtos.com", "pstatp.com", "bytecdn.cn"),
    "bilibili": ("hdslb.com", "biliimg.com", "bilibili.com"),
    "weibo": ("sinaimg.cn", "sinaimg.com", "weibo.com"),
    "qiehao": ("qpic.cn", "qq.com", "gtimg.com"),
    "baijiahao": ("bcebos.com", "bdstatic.com", "baidu.com"),
    "zhihu": ("zhimg.com", "zhihu.com"),
    "toutiao": ("byteimg.com", "toutiaoimg.com", "toutiao.com", "pstatp.com", "ibytedtos.com", "bytecdn.cn"),
    "sohu": ("itc.cn", "sohu.com", "sohucs.com", "s3img.com"),
    "xiaohongshu": ("xhscdn.com", "xiaohongshu.com", "xhsimg.com"),
    "kuaishou": ("ksapisrv.com", "kwaicdn.com", "kuaishouzt.com", "kuaishou.com", "yximgs.com",
                  "kwai.net", "ksyuncdn.com", "gifshow.com"),
    "tencent": ("qpic.cn", "qlogo.cn", "wxapp.tc.qq.com"),
    "wechat": ("mmbiz.qpic.cn", "mmbiz.qlogo.cn"),
    "jd": ("360buyimg.com",),
    "xiaohongshu_merchant": ("xhscdn.com", "xiaohongshu.com", "xhsimg.com"),
    "dongchedi": ("byteimg.com", "pstatp.com", "ibytedtos.com", "dcdapp.com", "dongchedi.com"),
    "taobao": ("alicdn.com",),
}


def is_uploaded_image(item: dict, platform: str | None = None) -> bool:
    """平台持久图片必须是已加载的 HTTP(S) 图片，data/blob 不算上传完成。"""
    parsed = urlparse(item.get("src", ""))
    persistent = bool(item.get("ready") and parsed.scheme in {"https", "http"} and
                parsed.hostname and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})
    if not persistent or platform is None:
        return persistent
    host = parsed.hostname.lower()
    return any(host == suffix or host.endswith("." + suffix) for suffix in IMAGE_HOST_SUFFIXES.get(platform, ()))


async def install_native_preview_request_guard(page, platform: str) -> bool:
    """已核实的原生提交入口直接阻断；保护生效后可延后修改平台编辑器 DOM。"""
    if platform == "jd":
        async def guard_jd(route):
            request = route.request
            url = urlparse(request.url)
            function_ids = parse_qs(url.query).get("functionId", [])
            function_ids.append(url.path.rstrip("/").rsplit("/", 1)[-1])
            body = request.post_data or ""
            if body:
                function_ids.extend(parse_qs(body).get("functionId", []))
                try:
                    payload = json.loads(body)
                except (ValueError, TypeError):
                    payload = None
                if isinstance(payload, dict):
                    function_ids.append(payload.get("functionId"))
            if "articlePublishImageText" in function_ids:
                await route.abort("blockedbyclient")
            else:
                await route.continue_()

        await page.route(re.compile(r"^https://(?:api\.m|dr|dr-new|creator)\.jd\.com/"), guard_jd)
        return True
    if platform == "wechat":
        # 公众号存草稿与发表使用不同 action，但都可能写入内容。
        # 预览阻断这些写请求；文章/图片读取以及上传仍按编辑器流程执行。
        endpoint = re.compile(r"^https://mp\.weixin\.qq\.com/cgi-bin/(?:masssend|masssendmsg|freepublish|appmsgpublish|operate_appmsg)(?:[/?]|$)")

        async def guard_wechat(route):
            if route.request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
                await route.continue_()
            else:
                await route.abort("blockedbyclient")

        await page.route(endpoint, guard_wechat)
        return True
    if platform != "douyin":
        return False
    endpoint = re.compile(r"^https://creator\.douyin\.com/web/api/media/aweme/create_v2/(?:\?.*)?$")
    await page.route(endpoint, lambda route: route.abort("blockedbyclient"))
    return True


async def install_preview_guard(page) -> None:
    """预览只允许编辑和自动保存草稿，阻止人工误点发布按钮或发布热键。"""
    await page.add_init_script(_PREVIEW_GUARD)
    for frame in page.frames:
        if frame == page.main_frame:
            # 主页面保护安装失败必须阻止预览，不能只吞掉异常。
            await frame.evaluate(_PREVIEW_GUARD)
            continue
        try:
            await frame.evaluate(_PREVIEW_GUARD)
        except Exception:
            continue


_PREVIEW_GUARD = """(() => {
    if(window.__omnipostPreviewGuard)return;window.__omnipostPreviewGuard=true;
    const isPublish=el=>el && /^(?:(?:立即|确认|确定|定时)?(?:(?:发布|投稿)(?:文章|图文)?|发表|群发)|提交审核|提交发布|预览并发布|发表并群发|群发给所有用户)$/.test((el.innerText||el.textContent||'').trim());
    const guard=event=>{let el=event.target;while(el&&el!==document.body){
        if(isPublish(el)){event.preventDefault();event.stopImmediatePropagation();return;}
        el=el.parentElement;}};
    document.addEventListener('click',guard,true);
    document.addEventListener('keydown',event=>{
        if((event.ctrlKey||event.metaKey)&&event.key==='Enter'){
            event.preventDefault();event.stopImmediatePropagation();}},true);
    const disable=()=>document.querySelectorAll('button,[role=button],a').forEach(el=>{
        if(isPublish(el)){el.setAttribute('aria-disabled','true');el.style.pointerEvents='none';
            if(el.tagName==='BUTTON')el.disabled=true;}});
    // 初始化脚本可能早于根节点创建；事件拦截立即生效，观察器在 DOM 可用后安装。
    const observe=()=>{
        if(!document.documentElement)return;
        new MutationObserver(disable).observe(document.documentElement,{subtree:true,childList:true});
        disable();
    };
    if(document.documentElement)observe();
    else document.addEventListener('DOMContentLoaded',observe,{once:true});
})()"""


_EXTERNAL_RECEIPT_TEXTS = """elements => elements.filter(el=> {
    if(el.closest('[contenteditable],.ProseMirror,.ql-editor,.public-DraftEditor-content,'+
        '.DraftEditor-root,.edui-body,.edui-editor,.news-editor-pc,[class*="syl-editor"]'))return false;
    const box=el.getBoundingClientRect(),style=getComputedStyle(el);
    return box.width>0&&box.height>0&&style.display!=='none'&&style.visibility!=='hidden';
}).map(el=>(el.innerText||'').trim())"""


def receipt_status(text: str) -> str | None:
    """只识别开头的明确结果句；“发布成功后请……”等说明不是回执。"""
    text = re.sub(r"^[✅✔✓√\ufe0f\s]+", "", text or "").strip()
    matched = re.match(r"^(?:文章|内容|笔记|图文)?(?:已)?(发布成功|发表成功|提交成功|审核中|等待审核|发布失败|发表失败|审核不通过|内容违规|提交失败)(?=[。！!，,；;：:\n]|$)", text)
    return matched.group(1) if matched else None


async def has_visible_challenge(page, feedback: list[str]) -> bool:
    """只认编辑器外的可见验证组件或明确反馈，正文提及验证码不算挑战。"""
    challenges = await page.locator('[role="dialog"],.ant-modal,.el-dialog,'
        '[class*="captcha"],[id*="captcha"],iframe').evaluate_all("""elements=>elements.filter(el=>{
            if(el.closest('[contenteditable],.ProseMirror,.ql-editor,.public-DraftEditor-content,'+
                '.DraftEditor-root,.edui-body,.edui-editor,.news-editor-pc'))return false;
            const box=el.getBoundingClientRect(),style=getComputedStyle(el);
            return box.width>0&&box.height>0&&style.display!=='none'&&style.visibility!=='hidden';
        }).map(el=>({is_frame:el.tagName==='IFRAME',src:el.getAttribute('src')||'',text:el.innerText||''}))""")
    for challenge in challenges:
        if challenge["is_frame"]:
            url = urlparse(challenge["src"])
            if re.search(r"captcha|geetest|recaptcha|hcaptcha|challenge|/verify(?:/|$)",
                         (url.hostname or "") + url.path, re.I):
                return True
        elif any(term in challenge["text"] for term in ("滑块验证", "安全验证", "请完成验证", "验证码")):
            return True
    for text in feedback:
        if text.strip() in {"滑块验证", "安全验证", "请完成验证", "验证码"} or re.search(
                r"(?:^|[，,。：:])\s*(?:请|需要|需|必须)[^。！!]*?(?:验证码|安全验证|滑块验证|完成验证)", text):
            return True
    return False


async def read_result_evidence(page, platform: str, expected_title: str = "") -> dict:
    """只接受明确发布反馈或文章地址；没有证据时保持未知结果。"""
    body = await page.locator("body").inner_text()
    feedback = await page.locator('[role="alert"],.ant-message,.cheetah-message,.n-message,'
        '.el-message,.vui_message,[class*="toast"]').evaluate_all(_EXTERNAL_RECEIPT_TEXTS)
    if await has_visible_challenge(page, feedback):
        return {"status": "needs_action", "message": "平台要求人工验证，请核对平台记录后处理"}
    # 页面说明中的“发布成功”不算结果；必须来自反馈区域或独立的成功标题。
    headings = await page.locator("h1,h2,h3").evaluate_all(_EXTERNAL_RECEIPT_TEXTS)
    feedback_statuses = [receipt_status(text) for text in feedback]
    # 标题原稿恰好叫“发布成功”时也不能把它当平台回执。
    signals = feedback_statuses + [receipt_status(text) for text in headings
                                   if text.strip() != expected_title.strip()]
    for term in ("发布失败", "发表失败", "审核不通过", "内容违规", "提交失败"):
        if term in feedback_statuses:
            return {"status": "failed", "message": f"平台反馈：{term}", "platform_status": term}
    patterns = {
        "douyin": r"^https://(?:www\.)?douyin\.com/article/(\d+)(?:[/?#]|$)",
        "bilibili": r"^https://(?:www\.)?bilibili\.com/(?:read/cv|opus/)(\d+)(?:[/?#]|$)",
        "weibo": r"^https://(?:www\.)?weibo\.com/ttarticle/p/show\?[^#]*\bid=(\d+)",
        "qiehao": r"^https://(?:new\.qq\.com/(?:rain/)?a/|page\.om\.qq\.com/page/)([A-Za-z0-9_-]+)(?:\.html)?(?:[/?#]|$)",
        "zhihu": r"^https://zhuanlan\.zhihu\.com/p/(\d+)(?:[/?#]|$)",
        "baijiahao": r"^https://baijiahao\.baidu\.com/s\?[^#]*\bid=(\d+)",
        "toutiao": r"^https://(?:www\.)?toutiao\.com/article/(\d+)(?:[/?#]|$)",
        "sohu": r"^https://(?:www\.)?sohu\.com/a/(\d+_\d+)(?:[/?#]|$)",
        "wechat": r"^https://mp\.weixin\.qq\.com/s/([A-Za-z0-9_-]+)(?:[/?#]|$)",
        "xiaohongshu": r"^https://(?:www\.)?xiaohongshu\.com/(?:explore|discovery/item)/([A-Za-z0-9]+)(?:[/?#]|$)",
        "kuaishou": r"^https://(?:www\.)?kuaishou\.com/short-video/([A-Za-z0-9_-]+)(?:[/?#]|$)",
    }
    public = re.search(patterns.get(platform, r"(?!)"), page.url or "")
    if platform == "wechat":
        if any(key in parse_qs(urlparse(page.url or "").query) for key in ("tempkey", "token", "is_temp_url", "preview")):
            public = None
    if public and expected_title and normalize_text(expected_title) in normalize_text(body):
        return {"status": "published", "message": "已打开并确认平台公开文章页面",
                "platform_id": public.group(1), "platform_url": page.url, "platform_status": "已发布"}
    if any(term in signals for term in ("提交成功", "等待审核", "审核中", "发布成功", "发表成功")):
        term = next(term for term in ("审核中", "等待审核", "发布成功", "发表成功", "提交成功") if term in signals)
        # 发布成功通常仍可能待审，因此必须有公开文章链接才能标记 published。
        return {"status": "submitted", "message": f"平台已确认提交：{term}", "platform_status": term}
    return {"status": "unknown", "message": "已尝试提交，尚未获得平台确认；请核对内容记录，勿重复提交"}


async def save_screenshot(page, evidence_dir: Path, name: str) -> str | None:
    """仅把证据文件名交给接口，避免暴露服务器绝对路径。"""
    try:
        await page.screenshot(full_page=True, path=str(evidence_dir / name))
        return name
    except Exception:
        return None

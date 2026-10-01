"""文章平台约束和规范化输入，共供 API、CLI 和浏览器适配器使用。"""
from __future__ import annotations

import html
from html.parser import HTMLParser

import mistune
import nh3


class ArticleError(ValueError):
    """可直接展示给调用者的文章业务错误。"""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


from .platforms import PLATFORMS

# 这里只记录可复查的真实验收，不能由适配器存在或模拟测试推导。
LIVE_VERIFICATION = {
    "douyin": {
        "preview": True, "submitted": True, "published": True,
        "date": "2026-10-01",
        "url": "https://www.douyin.com/article/7691535675165871406",
        "scope": "已验证单篇文章的标题、完整正文、三图顺序和高清封面；话题、声明及其他账号仍待验证",
    },
}

ALLOWED_TAGS = {"p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "em", "i", "u", "s",
                "ul", "ol", "li", "blockquote", "a", "img", "table", "thead", "tbody", "tfoot", "tr", "th", "td",
                "pre", "code", "hr"}


def clean_content(content: str, content_format: str) -> str:
    """统一输入格式并清理脚本、事件、外部样式，保留文章语义。"""
    if not isinstance(content, str) or not content.strip():
        raise ArticleError("文章正文不能为空")
    if len(content.encode("utf-8")) > 2 * 1024 * 1024:
        raise ArticleError("文章正文不能超过 2MB")
    if content_format == "markdown":
        content = mistune.create_markdown(escape=False, plugins=["table", "strikethrough"])(content)
    elif content_format == "text":
        content = "".join("<p>" + html.escape(p).replace("\n", "<br>") + "</p>" for p in content.split("\n\n"))
    elif content_format != "html":
        raise ArticleError("正文格式必须为 html、markdown 或 text")
    cleaned = nh3.clean(content, tags=ALLOWED_TAGS,
                        attributes={"a": {"href", "title"}, "img": {"src", "alt", "data-asset-id"},
                                    "th": {"colspan", "rowspan"}, "td": {"colspan", "rowspan"},
                                    "code": {"class"}, "ol": {"start"}},
                        url_schemes={"http", "https"}, strip_comments=True)
    if not cleaned.strip():
        raise ArticleError("清理后的文章正文为空")
    return cleaned


class ImageReferences(HTMLParser):
    """在规范 HTML 中收集图片引用，避免用正则解析 HTML。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images = []

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.images.append(dict(attrs))


def image_references(content_html: str) -> list[dict]:
    """按原稿顺序返回正文图片。"""
    parser = ImageReferences()
    parser.feed(content_html)
    return parser.images


def validate_options(platform: str, options: dict) -> None:
    """平台选项先校验类型和已知限制，再由真实编辑器核验可用性。"""
    rules = PLATFORMS[platform]
    if not isinstance(options, dict):
        raise ArticleError("平台 options 必须为对象")
    if any(options.get(key) for key in ("schedule", "publish_date", "enableTimer")):
        raise ArticleError("文章暂不支持定时发布")
    fields = {field["name"]: field for field in rules["option_fields"]}
    for name, value in options.items():
        if name in {"schedule", "publish_date", "enableTimer"}:
            continue
        if name not in fields:
            # 旧调用者会携带未勾选的 ai_generated；空值不代表启用该功能。
            if value in (None, "", False):
                continue
            raise ArticleError(f"{rules['label']}不支持平台选项：{name}")
        field = fields[name]
        if field["type"] == "boolean":
            if not isinstance(value, bool):
                raise ArticleError(f"{field['label']}必须为布尔值")
        elif not isinstance(value, str):
            raise ArticleError(f"{field['label']}必须为文本")
        elif field.get("max_length") and len(value) > field["max_length"]:
            raise ArticleError(f"{field['label']}不能超过 {field['max_length']} 字")
        elif field["type"] == "select" and value and value not in field.get("options", []):
            raise ArticleError(f"{rules['label']}创作声明不受支持")


def capabilities() -> list[dict]:
    """公开能力中明确区分实现与真实平台验收状态。"""
    return [{"platform": platform, **rules, "scheduled": False,
             "formats": ["headings", "bold", "lists", "quotes",
                         "link_text" if platform == "douyin" else "links", "images", "table", "code"],
             "live_verified": LIVE_VERIFICATION.get(platform, {}).get("published", False),
             "verification": {stage: LIVE_VERIFICATION.get(platform, {}).get(stage, False)
                              for stage in ("preview", "submitted", "published")},
             "verification_scope": LIVE_VERIFICATION.get(platform, {}).get("scope", "缺少真实账号验收"),
             "verification_date": LIVE_VERIFICATION.get(platform, {}).get("date", ""),
             "verification_url": LIVE_VERIFICATION.get(platform, {}).get("url", ""),
             "permission_check": "进入平台编辑器后检查账号文章权限",
             "format_fallbacks": {"table": "image", "code": "image",
                                  **({"links": "text_url_opt_in"} if platform == "douyin" else {})}}
            for platform, rules in PLATFORMS.items()]

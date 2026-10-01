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


PLATFORMS = {
    "baijiahao": {"label": "百家号", "account_type": 5, "title_min": 2, "title_max": 64,
                  "cover_required": True, "cover_max_bytes": 5 * 1024 * 1024,
                  "cover_min_width": 0, "cover_min_height": 0, "statement_options": []},
    "zhihu": {"label": "知乎", "account_type": 9, "title_min": 1, "title_max": 100,
              "cover_required": False, "cover_max_bytes": 10 * 1024 * 1024,
              "cover_min_width": 0, "cover_min_height": 0,
              "statement_options": ["无声明", "包含剧透", "包含医疗建议", "虚构创作", "包含理财内容",
                                    "包含 AI 辅助创作 作者对内容负责"]},
    "toutiao": {"label": "今日头条", "account_type": 7, "title_min": 1, "title_max": 30,
                "cover_required": False, "cover_max_bytes": 20 * 1024 * 1024,
                "cover_min_width": 0, "cover_min_height": 0,
                "statement_options": ["取材网络", "引用站内", "个人观点，仅供参考", "引用AI", "虚构演绎，故事经历",
                                      "投资观点，仅供参考", "健康医疗分享，仅供参考"]},
    "sohu": {"label": "搜狐号", "account_type": 8, "title_min": 5, "title_max": 72,
             "cover_required": False, "cover_max_bytes": 10 * 1024 * 1024,
             "cover_min_width": 450, "cover_min_height": 300,
             "statement_options": ["无特别声明", "引用声明", "包含AI创作内容", "包含虚构创作"]},
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


def capabilities() -> list[dict]:
    """公开能力中明确区分实现与真实平台验收状态。"""
    return [{"platform": platform, **rules, "scheduled": False,
             "formats": ["headings", "bold", "lists", "quotes", "links", "images", "table", "code"],
             "live_verified": False} for platform, rules in PLATFORMS.items()]

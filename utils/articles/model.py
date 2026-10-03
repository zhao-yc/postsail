"""文章平台约束和规范化输入，共供 API、CLI 和浏览器适配器使用。"""
from __future__ import annotations

import html
from html.parser import HTMLParser
from urllib.parse import urlsplit

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
    """在规范 HTML 中收集图片引用与标题层级，避免用正则解析 HTML。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images = []
        self.heading_levels = set()

    def handle_starttag(self, tag, attrs):
        if tag == "img":
            self.images.append(dict(attrs))
        elif tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading_levels.add(int(tag[1]))


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
    for name, field in fields.items():
        if field.get("required") and (name not in options or options[name] is None or
                field["type"] == "boolean" and options[name] is not True or
                isinstance(options[name], str) and not options[name].strip()):
            raise ArticleError(f"{rules['label']}必须设置{field['label']}")
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
            raise ArticleError(f"{rules['label']}{field['label']}不受支持，请重新选择当前平台选项")
        if field.get("format") == "url" and value:
            try:
                url = urlsplit(value)
                valid = url.scheme in {"http", "https"} and url.hostname and not url.username and not url.password
            except ValueError:
                valid = False
            if not valid:
                raise ArticleError(f"{field['label']}必须是完整 HTTP/HTTPS 地址")
    if platform == "csdn" and options.get("create_type") in {"转载", "翻译"} and not options.get("source_url", "").strip():
        raise ArticleError("CSDN 转载或翻译必须填写原文链接")
    if platform == "yiche" and options.get("declaration") == "内容为转载" and not options.get("source_url", "").strip():
        raise ArticleError("易车号声明内容为转载时必须填写转载来源")
    if platform == "yiche" and options.get("source_url") and options.get("declaration") != "内容为转载":
        raise ArticleError("易车号仅在声明内容为转载时填写转载来源，请重新选择声明或清空来源")
    if platform == "jingdong" and options.get("category", "").strip():
        path = options["category"].split("/")
        if len(path) != 3 or any(not part.strip() for part in path):
            raise ArticleError("京东标签分类须填写完整三级路径：一级/二级/三级")


def option_asset_ids(platform: str, options: dict) -> dict[str, str]:
    """仅将能力表声明的素材字段视为素材引用，不接受任意本地文件路径。"""
    references = {}
    for field in PLATFORMS[platform]["option_fields"]:
        if field["type"] != "asset":
            continue
        value = options.get(field["name"])
        if value in (None, ""):
            continue
        if not isinstance(value, str) or not value.strip():
            raise ArticleError(f"{field['label']}必须引用已上传的素材 ID")
        references[field["name"]] = value
    return references


def validate_option_asset(field: dict, asset: dict) -> None:
    """核对平台额外封面素材，尺寸边界包含等号。"""
    label = field["label"]
    if asset.get("mime_type") not in {"image/jpeg", "image/png"}:
        raise ArticleError(f"{label}须为 JPEG 或 PNG 图片")
    if int(asset.get("size") or 0) > field.get("max_bytes", 20 * 1024 * 1024):
        raise ArticleError(f"{label}超过大小限制")
    width, height = int(asset.get("width") or 0), int(asset.get("height") or 0)
    if width < field.get("min_width", 1) or height < field.get("min_height", 1):
        raise ArticleError(f"{label}尺寸至少为 {field.get('min_width', 1)}×{field.get('min_height', 1)}")
    if field.get("max_width") and width > field["max_width"]:
        raise ArticleError(f"{label}宽度不能超过 {field['max_width']}")
    ratio = field.get("aspect_ratio")
    if ratio and width * ratio[1] != height * ratio[0]:
        raise ArticleError(f"{label}比例须为 {ratio[0]}:{ratio[1]}，请上传对应比例的封面")
    ratios = field.get("aspect_ratios")
    if ratios and (not height or not any(abs(width / height - pair[0] / pair[1]) <=
                                        field.get("aspect_ratio_tolerance", 0) for pair in ratios)):
        allowed = "、".join(f"{pair[0]}:{pair[1]}" for pair in ratios)
        raise ArticleError(f"{label}比例须为 {allowed}")


def weighted_character_count(text: str) -> float:
    """汽车之家 Qi：逐 UTF-16 单元计数，编码值大于 256 算一字，其余算半字。"""
    encoded = text.encode("utf-16-le", errors="surrogatepass")
    return sum(2 if encoded[index] + (encoded[index + 1] << 8) > 256 else 1
               for index in range(0, len(encoded), 2)) / 2


def validate_title_characters(platform: str, title: str) -> None:
    """核对平台自己的标题计数规则，不以通用字符串长度代替。"""
    rules = PLATFORMS[platform]
    if any(low <= ord(character) <= high for character in title
           for low, high in rules.get("title_forbidden_ranges", [])):
        raise ArticleError(f"{rules['label']}标题不支持 Emoji 等特殊符号，请移除后重试")
    minimum = rules.get("title_min_cjk", 0)
    if minimum and sum("\u4e00" <= character <= "\u9fa5" for character in title) < minimum:
        raise ArticleError(f"{rules['label']}标题至少包含 {minimum} 个汉字")
    weighted = rules.get("title_weighted_limits")
    if weighted and not weighted[0] <= weighted_character_count(title.strip()) <= weighted[1]:
        raise ArticleError(f"{rules['label']}标题须为 {weighted[0]}–{weighted[1]} 字（英文字符按半字计）")


def validate_platform_content(platform: str, content_html: str, tags: list) -> None:
    """服务建任务和执行器使用相同的正文、话题约束。"""
    rules = PLATFORMS[platform]
    if rules.get("available") is False:
        raise ArticleError(rules["reason"])
    if rules.get("body_max_html_chars") and len(content_html) > rules["body_max_html_chars"]:
        raise ArticleError(f"{rules['label']}文章 HTML 最多 {rules['body_max_html_chars']} 个字符")
    if rules.get("heading_levels"):
        structure = ImageReferences()
        structure.feed(content_html)
        if structure.heading_levels - set(rules["heading_levels"]):
            raise ArticleError(f"{rules['label']}正文仅支持一级标题，请将二至六级标题改为一级标题或普通段落")
    if rules.get("tags_supported") is False and tags:
        raise ArticleError(f"{rules['label']}文章不支持单独设置话题，请清空该平台话题")
    if len(tags) < rules.get("tags_min", 0) or any(not tag.strip() for tag in tags):
        raise ArticleError(f"{rules['label']}必须设置有效的文章标签")
    if rules.get("tags_max") and len(tags) > rules["tags_max"]:
        raise ArticleError(f"{rules['label']}最多设置 {rules['tags_max']} 个话题")


def validate_platform_cover(platform: str, cover: dict, first_body_asset: dict | None = None) -> None:
    """核对平台封面比例；京东封面与正文首图不能是同一素材。"""
    rules = PLATFORMS[platform]
    if rules.get("cover_max_width") and int(cover.get("width") or 0) > rules["cover_max_width"]:
        raise ArticleError(f"{rules['label']}横版封面宽度不能超过 {rules['cover_max_width']} 像素")
    ratio = rules.get("cover_aspect_ratio")
    if ratio and int(cover.get("width") or 0) * ratio[1] != int(cover.get("height") or 0) * ratio[0]:
        raise ArticleError(f"{rules['label']}横版封面比例须为 {ratio[0]}:{ratio[1]}")
    if platform != "jingdong":
        return
    width, height = int(cover.get("width") or 0), int(cover.get("height") or 0)
    if not height or abs(width / height - 10 / 7) > 0.01:
        raise ArticleError("京东文章封面比例必须为 10:7，请选择单独制作的横版封面")
    if first_body_asset:
        same_id = cover.get("id") and cover["id"] == first_body_asset.get("id")
        same_hash = cover.get("sha256") and cover["sha256"] == first_body_asset.get("sha256")
        if same_id or same_hash:
            raise ArticleError("京东文章封面不能使用正文首图，请选择不同的封面素材")


def capabilities() -> list[dict]:
    """公开能力中明确区分实现与真实平台验收状态。"""
    return [{"platform": platform, **rules, "scheduled": False,
             "formats": ["headings", "bold", "lists", "quotes",
                         "link_text" if platform in {"douyin", "chejiahao"} else "links", "images", "table", "code"],
             "live_verified": LIVE_VERIFICATION.get(platform, {}).get("published", False),
             "verification": {stage: LIVE_VERIFICATION.get(platform, {}).get(stage, False)
                              for stage in ("preview", "submitted", "published")},
             "verification_scope": LIVE_VERIFICATION.get(platform, {}).get("scope", rules.get("verification_scope", "缺少真实账号验收")),
             "verification_date": LIVE_VERIFICATION.get(platform, {}).get("date", ""),
             "verification_url": LIVE_VERIFICATION.get(platform, {}).get("url", ""),
             "permission_check": "进入平台编辑器后检查账号文章权限",
             "format_fallbacks": {"table": "image", "code": "image",
                                  **({"links": "text_url_opt_in"} if platform in {"douyin", "chejiahao"} else {})}}
            for platform, rules in PLATFORMS.items()]

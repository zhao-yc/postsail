"""网页、API、CLI 共用的文章平台定义；不依赖浏览器或 Web 运行时。"""
from .extended_platforms import EXTENDED_PLATFORMS, EXTENDED_CONTENT_KINDS, EXTENDED_OPTION_FIELDS
from .note_platforms import NOTE_PLATFORMS, NOTE_PLATFORM_RULES

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

# 平台表保持轻量，CLI 无需加载 Flask 或浏览器依赖即可列出相同平台。
PLATFORMS.update({
    "douyin": {"label": "抖音", "account_type": 3, "title_min": 1, "title_max": 30,
               "cover_required": True, "cover_max_bytes": 20 * 1024 * 1024,
               "cover_min_width": 499, "cover_min_height": 499, "statement_options": [],
               "body_max_chars": 20000, "body_max_images": 30, "tags_max": 5},
    "bilibili": {"label": "哔哩哔哩", "account_type": 6, "title_min": 1, "title_max": 30,
                 "cover_required": False, "cover_max_bytes": 20 * 1024 * 1024,
                 "cover_min_width": 599, "cover_min_height": 335, "statement_options": []},
    "weibo": {"label": "新浪微博", "account_type": 10, "title_min": 1, "title_max": 32,
              "cover_required": True, "cover_max_bytes": 10 * 1024 * 1024,
              "cover_min_width": 0, "cover_min_height": 0, "statement_options": []},
    "qiehao": {"label": "企鹅号", "account_type": 11, "title_min": 5, "title_max": 64,
               "cover_required": False, "cover_max_bytes": 10 * 1024 * 1024,
               "cover_min_width": 0, "cover_min_height": 0, "statement_options": []},
})

PLATFORMS.update(EXTENDED_PLATFORMS)

CONTENT_KINDS = {"douyin": "原生文章", "bilibili": "专栏／长图文", "weibo": "头条文章",
                 **EXTENDED_CONTENT_KINDS}
OPTION_FIELDS = {
    "douyin": [{"name": "summary", "label": "文章摘要", "type": "textarea", "max_length": 30},
               {"name": "links_as_text", "label": "将不支持的超链接转为文字和完整网址", "type": "boolean"}],
    "bilibili": [],
    "weibo": [{"name": "summary", "label": "文章导语", "type": "textarea", "max_length": 44},
              {"name": "publish_text", "label": "配套微博文字", "type": "textarea",
               "placeholder": "留空使用文章标题"}],
    "qiehao": [{"name": "category", "label": "文章分类", "type": "text",
                "placeholder": "填写平台显示的完整分类名称"},
               {"name": "summary", "label": "文章摘要", "type": "textarea", "max_length": 200}],
}
for name, rules in PLATFORMS.items():
    rules["content_kind"] = CONTENT_KINDS.get(name, "文章")
    rules["content_mode"] = "rich_article"
    if name in EXTENDED_OPTION_FIELDS:
        rules["option_fields"] = [dict(field) for field in EXTENDED_OPTION_FIELDS[name]]
        continue
    fields = list(OPTION_FIELDS.get(name, []))
    if name == "baijiahao":
        fields.append({"name": "ai_generated", "label": "采用 AI 生成内容", "type": "boolean"})
    elif rules["statement_options"]:
        fields.append({"name": "statement", "label": "创作声明", "type": "select",
                       "options": rules["statement_options"]})
    else:
        fields.append({"name": "statement", "label": "创作声明", "type": "text",
                       "placeholder": "按平台原文填写；不填写则保留平台默认值"})
    rules["option_fields"] = fields

PLATFORMS.update(NOTE_PLATFORM_RULES)

# 列表顺序和用户选择器一致；既有 API 标识及账号类型保持兼容。
PLATFORMS = {name: PLATFORMS[name] for name in (
    "douyin", "bilibili", "baijiahao", "toutiao", "weibo", "zhihu", "qiehao", "sohu",
    *EXTENDED_PLATFORMS, *NOTE_PLATFORM_RULES)}
ARTICLE_PLATFORMS = tuple(PLATFORMS)

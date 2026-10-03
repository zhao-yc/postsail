"""网页、API、CLI 共用的文章平台定义；不依赖浏览器或 Web 运行时。"""

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
    "xiaohongshu": {"label": "小红书", "account_type": 1, "title_min": 1, "title_max": 20,
                   "cover_required": False, "cover_max_bytes": 20 * 1024 * 1024,
                   "cover_min_width": 0, "cover_min_height": 0, "statement_options": [],
                   "body_max_chars": 1000, "body_max_images": 18, "tags_max": 10},
    "kuaishou": {"label": "快手", "account_type": 4, "title_min": 1, "title_max": 90,
                 "cover_required": False, "cover_max_bytes": 20 * 1024 * 1024,
                 "cover_min_width": 0, "cover_min_height": 0, "statement_options": [],
                 "body_max_chars": 500, "body_max_images": 30, "tags_max": 5},
    "tencent": {"label": "视频号", "account_type": 2, "title_min": 1, "title_max": 16,
                "cover_required": False, "cover_max_bytes": 20 * 1024 * 1024,
                "cover_min_width": 0, "cover_min_height": 0, "statement_options": [],
                "body_max_chars": 1000, "body_max_images": 9, "tags_max": 5},
    "wechat": {"label": "微信公众号", "account_type": 12, "title_min": 1, "title_max": 64,
               "cover_required": True, "cover_max_bytes": 10 * 1024 * 1024,
               "cover_min_width": 0, "cover_min_height": 0, "statement_options": [],
               "limitations": "暂不支持原生话题，请在账号设置中清空话题；发表可能需要管理员扫码确认。保存草稿不代表已发表。"},
    "jd": {"label": "京东", "account_type": 13, "title_min": 5, "title_max": 20,
           "cover_required": False, "cover_max_bytes": 5 * 1024 * 1024,
           "cover_min_width": 0, "cover_min_height": 0, "statement_options": [],
           "body_max_chars": 1000, "body_max_images": 20, "cover_is_first_image": True},
    "xiaohongshu_merchant": {"label": "小红书商家号", "account_type": 14, "title_min": 1, "title_max": 20,
                            "cover_required": False, "cover_max_bytes": 20 * 1024 * 1024,
                            "cover_min_width": 0, "cover_min_height": 0, "statement_options": [],
                            "body_max_chars": 1000, "body_max_images": 9, "tags_max": 10},
    "dongchedi": {"label": "懂车号", "account_type": 15, "title_min": 1, "title_max": 30,
                  "cover_required": True, "cover_max_bytes": 10 * 1024 * 1024,
                  "cover_min_width": 0, "cover_min_height": 0, "statement_options": [], "tags_supported": False,
                  "limitations": "当前适配采用标题 30 字、封面 10 MB 的保守限制；暂不支持原生话题和声明，请清空话题。"},
    "taobao": {"label": "淘宝光合", "account_type": 16, "title_min": 1, "title_max": 30,
               "cover_required": False, "cover_max_bytes": 20 * 1024 * 1024,
               "cover_min_width": 0, "cover_min_height": 0,
               "statement_options": ["内容无需标注", "含AI生成内容", "含虚构演绎内容", "内容为转载",
                                     "个人观点，仅供参考", "内容含营销信息"],
               "statement_required": True, "tags_supported": False,
               "body_max_chars": 1000, "body_max_images": 9, "cover_is_first_image": True,
               "image_min_width": 720, "image_min_height": 720},
})

NOTE_PLATFORMS = frozenset({"xiaohongshu", "kuaishou", "tencent", "jd", "xiaohongshu_merchant", "taobao"})
CONTENT_KINDS = {"douyin": "原生文章", "bilibili": "专栏／长图文", "weibo": "头条文章",
                 "wechat": "公众号图文", **{name: "图文笔记" for name in NOTE_PLATFORMS}}
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
    "wechat": [{"name": "author", "label": "作者", "type": "text", "max_length": 8},
               {"name": "summary", "label": "摘要", "type": "textarea", "max_length": 120}],
    **{name: [{"name": "flatten_content", "label": "将富文本转换为纯文本描述和图片列表", "type": "boolean"}]
       for name in NOTE_PLATFORMS},
}
OPTION_FIELDS["xiaohongshu_merchant"] += [
    {"name": "product_id", "label": "关联商品 ID", "type": "text", "required": True, "max_length": 64,
     "placeholder": "填写该店铺中要关联的准确商品 ID"},
    {"name": "shop_name", "label": "店铺名称", "type": "text", "required": True, "max_length": 100,
     "placeholder": "填写商家后台显示的完整店铺名称"},
]
OPTION_FIELDS["jd"].append(
    {"name": "product_links", "label": "关联商品", "type": "textarea", "max_length": 2000,
     "placeholder": "填写京东商品链接或 SKU，用换行或逗号分隔，最多 10 个"})
for name, rules in PLATFORMS.items():
    rules["content_kind"] = CONTENT_KINDS.get(name, "文章")
    rules["content_mode"] = "image_text" if name in NOTE_PLATFORMS else "rich_article"
    if name in NOTE_PLATFORMS:
        rules["limitations"] = ("至少一张图片；封面未出现在正文中时放在图片列表首位。描述与图片分开展示，"
                                 "链接保留为文字和完整网址；富文本排版须明确同意转换。话题按 #文字 写入描述。")
        if name == "kuaishou":
            rules["limitations"] += "快手标题写入描述首行，与正文和话题一并计入字数。"
        elif name == "xiaohongshu_merchant":
            rules["limitations"] += "使用独立商家账号；须填写准确店铺名和商品 ID。图片采用 9 张保守上限。"
        elif name == "jd":
            rules["limitations"] += "首图自动生成封面，已在正文中的所选封面必须是首图；每张图片最多 5 MB，关联商品按当前频道要求校验。"
        elif name == "taobao":
            rules["limitations"] = ("每张图片至少 720×720，首图为封面，最多 9 张；已在正文中的所选封面必须是首图。富文本转为描述须明确同意。"
                                     "须选择创作者声明；暂不支持关联商品和原生内容标签，请清空话题。")
    fields = list(OPTION_FIELDS.get(name, []))
    if name == "baijiahao":
        fields.append({"name": "ai_generated", "label": "采用 AI 生成内容", "type": "boolean"})
    elif rules["statement_options"]:
        fields.append({"name": "statement", "label": "创作声明", "type": "select",
                       "options": rules["statement_options"], "required": rules.get("statement_required", False)})
    elif name not in NOTE_PLATFORMS and name not in {"wechat", "dongchedi"}:
        fields.append({"name": "statement", "label": "创作声明", "type": "text",
                       "placeholder": "按平台原文填写；不填写则保留平台默认值"})
    rules["option_fields"] = fields

# 列表顺序和用户选择器一致；既有 API 标识及账号类型保持兼容。
PLATFORMS = {name: PLATFORMS[name] for name in (
    "douyin", "kuaishou", "tencent", "xiaohongshu", "baijiahao", "toutiao",
    "weibo", "zhihu", "sohu", "wechat", "bilibili", "qiehao",
    "jd", "xiaohongshu_merchant", "dongchedi", "taobao")}
ARTICLE_PLATFORMS = tuple(PLATFORMS)

"""蚁小二“文章发布”类别对应的平台约定，不依赖其服务或账号。

参数依据见 docs/article-platform-verification.md；公开契约不是本项目的真实发布验收。
没有公开标题上限的平台仅保留原稿 300 字上限，运行时再读取平台控件限制。
"""


def _platform(label, account_type, *, title_min=1, title_max=300,
              cover_required=False, cover_supported=True, **extra):
    return {
        "label": label, "account_type": account_type,
        "title_min": title_min, "title_max": title_max,
        "title_limit_confirmed": title_max != 300,
        "cover_required": cover_required, "cover_supported": cover_supported,
        "cover_max_bytes": 20 * 1024 * 1024,
        "cover_min_width": 0, "cover_min_height": 0,
        "statement_options": [], "available": True,
        "verification_scope": "已按公开文章契约接入，尚未完成真实账号验收",
        **extra,
    }


EXTENDED_PLATFORMS = {
    "yidian": _platform("一点号", 12, title_min=5, title_max=64,
                        cover_required=True, tags_supported=False),
    "dayu": _platform("大鱼号", 13, title_max=50, body_max_html_chars=50000,
                      tags_supported=False),
    "netease": _platform("网易号", 14, cover_required=True, tags_supported=False),
    "acfun": _platform("AcFun", 15, title_max=50, cover_required=True,
                       body_max_html_chars=50000, tags_max=1),
    "kuaichuan": _platform("快传号", 16, cover_required=True),
    "xueqiu": _platform("雪球号", 17, title_min=9, title_max=100,
                        tags_supported=False),
    # 蚁小二文章契约与京东当前官方 style=0 编辑器交叉核实；真实账号仍待验收。
    "jingdong": _platform("京东", 18, title_min=15, title_max=27,
                          cover_required=True, cover_max_bytes=5 * 1024 * 1024,
                          # 共用校验使用严格大于边界，599/419 表示至少 600×420。
                          cover_min_width=599, cover_min_height=419,
                          tags_supported=False,
                          cover_hint="比例 10:7，至少 600 × 420，最大 5 MB；每次设置一张封面，不能使用正文首图",
                          verification_scope="依据京东官方文章编辑器实现，官方组件离线验证通过；真实账号预览及发布尚未验收"),
    "douban": _platform("豆瓣", 19, cover_supported=False),
    "csdn": _platform("CSDN", 20, cover_required=True, tags_min=1),
    "jianshu": _platform("简书", 21, cover_supported=False, tags_supported=False),
    "chejiahao": _platform("车家号", 22, title_max=60, title_weighted_limits=[6, 30],
                          title_forbidden_ranges=[[0x2600, 0x27ff], [0x10000, 0x10ffff]],
                          limitations="标题不支持 Emoji 等特殊符号；正文按平台规则计 10–100000 字，英文字符按半字计。",
                          cover_required=True, tags_supported=False, cover_label="横版封面",
                          cover_max_bytes=10 * 1024 * 1024, cover_min_width=559, cover_min_height=419,
                          cover_aspect_ratio=[4, 3], body_weighted_limits=[10, 100000],
                          cover_hint="比例 4:3，至少 560 × 420，最大 10 MB；另需独立竖版封面",
                          verification_scope="依据汽车之家当前官方长文编辑器实现，官方正文和双封面组件离线验证通过；真实账号预览及发布尚未验收"),
    "yiche": _platform("易车号", 23, title_min=5, title_max=28, cover_required=True,
                       body_max_html_chars=8000, cover_max_bytes=10 * 1024 * 1024, cover_max_width=5000,
                       cover_aspect_ratio=[3, 2],
                       cover_hint="比例 3:2，最大 10 MB，宽度不超过 5000；另需独立竖版封面",
                       tags_supported=False, cover_label="横版封面",
                       verification_scope="依据易车官方文章编辑器实现，官方裁剪与图片编辑组件离线验证通过；真实账号预览及发布尚未验收"),
    "dongchedi": _platform("懂车号", 24, title_min=2, title_max=30, title_min_cjk=2,
                          cover_required=True, tags_supported=False, cover_label="横版封面",
                          heading_levels=[1],
                          body_max_native_text_units=50000, body_max_native_html_units=60000,
                          limitations="正文标题仅支持一级标题；二至六级标题需改为一级标题或普通段落。正文去空白后最多 50000 字符，原生 HTML 最多 60000 字符。",
                          cover_min_width=531, cover_min_height=398, cover_aspect_ratio=[4, 3],
                          cover_hint="比例 4:3，至少 532 × 399，最大 20 MB；另需独立竖版封面",
                          verification_scope="依据懂车官方文章编辑器实现，官方正文、图片与双封面组件离线验证通过；真实账号预览及发布尚未验收"),
}

EXTENDED_CONTENT_KINDS = {
    "acfun": "文章投稿", "xueqiu": "长文章", "jingdong": "文章",
    "douban": "日记文章", "csdn": "博客文章", "jianshu": "文章",
    "chejiahao": "文章", "yiche": "文章", "dongchedi": "文章",
}

_STATEMENT = {"name": "statement", "label": "创作声明", "type": "text",
              "placeholder": "填写平台显示的完整声明；留空保留平台默认值"}
_ORIGINAL = {"name": "original", "label": "声明原创", "type": "boolean"}
_SOURCE = {"name": "source_url", "label": "原文链接", "type": "text", "format": "url",
           "placeholder": "转载或翻译时填写原文 HTTP/HTTPS 地址"}
_VISIBILITY = {"name": "visibility", "label": "可见范围", "type": "select",
               "options": ["公开", "仅自己可见"]}
_VERTICAL_COVER = {"name": "vertical_cover_asset_id", "label": "竖版封面", "type": "asset",
                   "required": True, "placeholder": "上传独立的 JPEG 或 PNG 竖版封面"}

EXTENDED_OPTION_FIELDS = {
    "yidian": [_STATEMENT],
    "dayu": [_STATEMENT],
    "netease": [_STATEMENT, _ORIGINAL],
    "acfun": [{"name": "summary", "label": "文章摘要", "type": "textarea", "max_length": 200},
              {"name": "category", "label": "文章分类", "type": "text", "required": True,
               "placeholder": "填写平台显示的完整分类名称"}, _ORIGINAL, _SOURCE],
    "kuaichuan": [_ORIGINAL],
    "xueqiu": [_VISIBILITY, _STATEMENT],
    "jingdong": [{"name": "category", "label": "标签分类", "type": "text",
                  "placeholder": "可选，填写平台显示的完整路径：一级/二级/三级"}],
    "douban": [_ORIGINAL, _VISIBILITY],
    "csdn": [{"name": "summary", "label": "文章摘要", "type": "textarea", "required": True},
             {"name": "create_type", "label": "创作类型", "type": "select", "required": True,
              "options": ["原创", "转载", "翻译"]}, _SOURCE, _STATEMENT],
    "jianshu": [],
    "chejiahao": [{**_VERTICAL_COVER, "max_bytes": 10 * 1024 * 1024,
                   "min_width": 560, "min_height": 420, "aspect_ratio": [3, 4],
                   "placeholder": "比例 3:4、宽度至少 560，建议 600 × 800；最大 10 MB"}, _ORIGINAL,
                  {"name": "first_publish", "label": "声明首发", "type": "boolean"},
                  {"name": "links_as_text", "label": "将不支持的超链接转为文字和完整网址", "type": "boolean"},
                  {"name": "agree_upload_terms", "label": "我已阅读并同意《汽车之家内容上传服务条款》《汽车之家联合共创须知》",
                   "type": "boolean", "required": True},
                  {"name": "content_type", "label": "内容属性", "type": "select",
                   "options": ["非商业内容", "商业内容"], "placeholder": "平台要求时选择内容属性"}],
    "yiche": [{**_VERTICAL_COVER, "aspect_ratios": [[3, 4], [4, 3]], "aspect_ratio_tolerance": 0.01,
               "max_bytes": 10 * 1024 * 1024, "max_width": 5000,
               "placeholder": "比例 3:4 或 4:3，最大 10 MB，宽度不超过 5000"},
              {"name": "declaration", "label": "创作声明", "type": "select",
               "options": ["内容无需标注", "含AI生成内容", "含虚构演绎内容", "内容含营销信息", "个人观点，仅供参考", "内容为转载"]},
              {**_SOURCE, "label": "转载来源", "placeholder": "声明内容为转载时填写原文 HTTP/HTTPS 地址"},
              {"name": "allow_forward", "label": "同意转发", "type": "boolean"},
              {"name": "allow_abstract", "label": "同意生成摘要", "type": "boolean"}],
    "dongchedi": [{**_VERTICAL_COVER, "min_width": 534, "min_height": 712,
                   "max_bytes": 20 * 1024 * 1024, "aspect_ratio": [3, 4],
                   "placeholder": "比例 3:4，至少 534 × 712，最大 20 MB"}],
}

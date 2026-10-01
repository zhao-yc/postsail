# 百家号内容类型说明

百家号支持两种主要内容类型：**视频**和**图文文章**。

本文的文章部分对应当前独立文章服务；百家号真实账号的预览、图片上传、审核回执和正式发表尚未验收，能力接口明确返回 `live_verified:false`。完整多平台流程见[独立多平台文章发布](./articles.md)。

## 内容类型对比

| 特性 | 视频 (Video) | 图文文章 (Article) |
|------|-------------|-------------------|
| 主要内容 | 视频文件 (.mp4) | 文字 + 图片 |
| 标题要求 | 1-30 字符 | 当前代码校验 2–64 字，不自动补字或截断，实际页面再校验 |
| 封面 | 自动生成 | 必须提供，当前大小上限 5MB |
| 正文编辑器 | 无 | 富文本编辑器 |
| 标签支持 | ✅ | ✅ |
| 定时发布 | 原有视频流程按平台支持 | 首版明确不支持 |
| 发布页面 | `/builder/rc/edit?type=videoV2` | `?type=news` / `?type=article` / `?type=newsManuscript` 依次尝试（未在真实账号上验证） |

## 使用方法

### 1. 视频发布

#### 通过前端界面
1. 登录百家号账号（账号管理）
2. 上传视频文件（素材管理）
3. 选择"百家号"平台
4. 填写标题、标签
5. 点击发布

#### 通过示例脚本
```bash
python examples/upload_video_to_baijiahao.py
```

#### 通过 API
```python
POST /postVideo
{
    "type": 5,  // 百家号
    "contentType": "video",  // 视频类型
    "title": "视频标题",
    "files": ["video.mp4"],
    "tags": ["标签1", "标签2"],
    "accounts": ["account.json"],
    "enableTimer": false,
    "dryRun": false
}
```

### 2. 图文文章发布

#### 通过前端界面
1. 登录百家号账号（账号管理）
2. 打开「文章管理」（路由 `/articles`）保存原稿
3. 插入正文图片并上传封面
4. 选择百家号账号，按需覆盖标题、话题及 AI 声明
5. 选择仅预览，或立即正式发布
6. 查询账号任务状态；平台已接收、审核中与已发表分别显示

#### 通过文章 CLI

```bash
sau article import --file ./draft/article.md --title "百家号示例文章" --cover ./draft/cover.png --json
sau article accounts --platform baijiahao --json
sau article publish ARTICLE_ID --platform baijiahao --account-id 2 --preview --idempotency-key draft-preview-01 --json
sau article status BATCH_ID --wait --json
```

删除 `--preview` 表示正式立即发布；替换资源 ID 和账号 ID，并为正式操作使用独立幂等键。默认正式发布，定时请求会明确拒绝。

#### 通过示例脚本
```bash
python examples/upload_article_to_baijiahao.py
```

该脚本保留用于单平台排障；日常多平台文章优先使用当前文章 API、CLI 或网页管理。

#### 通过 API
先通过 `POST /api/article-assets` 上传正文图片与封面，再通过 `POST /api/articles` 保存原稿：

```json
{
    "title": "百家号示例文章",
    "format": "html",
    "content": "<p>正文内容</p><img src=\"/api/article-assets/ASSET_ID/content\">",
    "tags": ["标签1", "标签2"],
    "cover_asset_id": "COVER_ASSET_ID"
}
```

随后向 `POST /api/articles/{id}/publish` 提交 `revision,mode,targets,idempotency_key`，账号目标使用 `{"platform":"baijiahao","account_id":2}`。旧 `/postVideo` 文章请求保留兼容，但已转接同一任务服务并返回批次 ID。

## 代码实现

### 类结构

```
uploader/baijiahao_uploader/
├── main.py
│   ├── BaiJiaHaoVideo      # 视频发布类
│   └── BaiJiaHaoArticle    # 图文文章发布类 (新增)
└── __init__.py
```

### 后端路由处理

当前文章由 `utils/articles/` 处理原稿、素材、发布快照与任务，适配器复用百家号页面操作；视频继续使用原有发布路径。

## 注意事项

### 图文文章
- 标题按当前能力接口校验，不自动补充后缀或截断。
- 原稿正文支持富文本与正文图片，提交前读回校验完整性；平台页面仍可能有额外限制。
- 话题通过平台配置传入，不自动改写原稿正文。
- 封面必须提供，当前上限 5MB；素材支持 PNG、JPEG、WebP，WebP 导入后转为 PNG。
- 首版仅立即发布，定时请求明确拒绝。
- 提交后的异常进入待确认，核查平台后才能决定是否重试。

### 视频
- ✅ 支持 MP4 格式视频
- ✅ 视频会自动上传并生成封面
- ✅ 标题 1-30 字符
- ⚠️ 上传大视频文件可能需要较长时间

## 测试模式 (Dry Run)

视频保留原有 `dryRun`；当前文章使用 `mode:"preview"` 或 CLI 的 `--preview`。

```python
dry_run = True  # 仅预览不发布
```

当前文章预览会填写并校验正文、图片和封面，保存截图，不点击正式发布；平台可能自动保存草稿。浏览器默认截图后关闭，`ARTICLE_PREVIEW_SECONDS` 可以配置保留秒数。

截图保存位置：
- 视频：`cookiesFile/dry_run_preview.png`
- 当前文章：`articleData/evidence/{task_id}/`，通过任务返回的 `evidence` 链接查询

## 常见问题

### Q1: 图文文章标题太短怎么办？
A: 修改原稿或该平台标题覆盖项。当前服务按 2–64 字校验，不自动补字；实际平台页面如有额外约束，会停止该目标并提示处理。

### Q2: 如何添加文章封面？
A: CLI 导入时传 `--cover`，或先上传素材后使用 `cover_asset_id`；网页在「文章管理」上传封面。当前文章 API 不接受服务器任意文件路径。

### Q3: 标签如何显示？
A: 原稿保存 `tags`，允许在百家号覆盖项中单独设置，适配器按平台话题控件处理；不自动改写原稿正文。

### Q4: 视频上传超时怎么办？
A: 视频上传有 10 分钟超时限制。建议：
- 压缩视频文件
- 使用更快的网络
- 检查视频格式是否正确

### Q5: Cookie 失效怎么办？
A: 运行以下命令重新获取 Cookie：
```bash
python examples/get_baijiahao_cookie.py
```

## 相关文档

- [百家号视频上传示例](../examples/upload_video_to_baijiahao.py)
- [百家号图文文章示例](../examples/upload_article_to_baijiahao.py)
- [百家号 Cookie 获取](../examples/get_baijiahao_cookie.py)
- [今日头条内容类型对比](./toutiao-content-types.md)

## 验证状态

已验证：
- Python 侧编译与导入通过
- 两处后端调用的实参顺序与 `post_article_baijiahao` 形参一致
- 前端 `npm run build` 通过

未验证（需真实百家号账号跑一次 dryRun）：
- 图文发布页 URL 与页面选择器（标题框、正文编辑器、封面上传、发布按钮）
- 定时发布的日期/时间选择控件

首次使用请务必勾选「仅预览不发布」，据浏览器实际页面调整选择器。

## 更新日志

**2026-07-29**
- ✨ 新增 `BaiJiaHaoArticle` 类，支持图文文章发布
- ✨ 新增 `post_article_baijiahao` 函数
- ✨ 后端 `/postVideo` 与 `/postVideoBatch` 均支持 `contentType` 区分视频和图文
- ✨ 前端发布中心：百家号新增「内容类型」选择，复用正文/封面表单
- 🐛 修复后端校验只放行头条图文、导致百家号图文被「文件列表不能为空」拦截的问题
- 📝 添加示例脚本 `upload_article_to_baijiahao.py`
- 🐛 视频上传页元素定位增加多选择器回退

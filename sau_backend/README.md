## 当前后端启动

在仓库根目录使用 Python 3.10–3.12，安装 Web 可选依赖并启动：

```bash
uv pip install -e ".[web]"
python sau_backend.py
```

新安装按[安装说明](../docs/install.md)初始化账号数据库。已有数据库保留，文章功能通过增量建表添加，不删除数据库、不重建账号和素材。浏览器按显式 `LOCAL_CHROME_PATH`、系统 Chrome、已安装 Playwright Chromium 选择；文章需要 Chromium 回退时运行 `python -m playwright install chromium`。

当前网页「文章管理」（`/articles`）和 `sau article` 共用 `/api/articles`、`/api/article-assets`、发布批次和账号任务 API。百家号、知乎、今日头条、搜狐号文章首版仅立即发布、可选预览，不支持定时；各平台真实账号尚未验收。完整契约、结果确认及 `articleData/`、数据库、账号会话备份见[独立多平台文章发布](../docs/articles.md)。

消息中心使用 `/api/interactions/`，分析与报表使用 `/api/analytics/`。启动时恢复已有明确启用的轮询和周期配置，新安装均关闭；回调认证、发送待核查和统计覆盖口径见[工作台说明](../docs/operations.md)。

## 历史接口说明

以下是保留的旧接口说明，具体字段以当前根目录 `sau_backend.py` 为准；旧文章请求已转接任务服务，不能把 HTTP 受理当作平台已发表。
## 接口说明
1. /upload post
    上传接口，上传成功会返回文件的唯一id，后期靠这个发布视频
2. /login id参数 用户名 type参数 平台标识：登录流程，前端和后端建立sse连接，后端获取到图片base64编码后返回给前端，前端接受扫码后后端存库后返回200，前端主动断开连接，然后调取/getValidAccounts获取当前所有可用账号
3. /getValidAccounts 会获取当前所有可用cookie，时间较慢，会逐个校验cookie，status 1 有效 0 无效cookie
4. /postVideo 发布视频接口 post json传参
    file_list      /upload获取的文件唯一标识
    account_list   /getValidAccounts获取的filePath字段
    type           类型字段（平台标识）
    title          视频标题
    tags           视频tag 列表，不带#
    category       原作者说是原创表示，0表示不是原创其他表示为原创，但测试该字段没有效果
    enableTimer    是否开启定时发布，默认关闭，开启传True，如果开启，下面三个必传，否则不传
    videos_per_day 每天发布几个视频
    daily_times    每天发布视频的时间，整形列表，与上面列表长度保持一致
    start_days     开始天数，0 代表明天开始定时发布 1 代表明天的明天
    以上三个字段是我的理解，不知道对不对，也不知道原作者为什么要这么设置
## 数据库说明
见当前目录下 db目录，py文件是创建脚本，db文件是sqlite数据库
## 文件说明
cookiesFile文件夹 存储cookie文件
myUtils文件夹 存储自己封装的python模块
videoFile文件夹 文件上传存放位置
web 文件夹 web路由目录
conf.py 全局配置，记得修改配置中 LOCAL_CHROME_PATH 为本机浏览器地址

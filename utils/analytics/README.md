# 数据分析模块

模块在现有 SQLite 数据库增量建立四张分析表，不修改账号表字段，也不删除旧作品缓存。`replace_account_stats` 会在替换最近作品缓存前迁移原缓存基线，再追加当前观测；以后采集条数减少，旧作品观测仍保留。

## 接入

```python
from utils.analytics.routes import register_analytics_routes

# 刷新函数先在浏览器中读取，返回归一化作品和实际资料；函数内部不写分析表。
def refresh_account(account_id, platform, limit):
    return {
        "items": collected_items,  # 未采集作品时使用 None，而非空数组
        "followerCount": actual_follower_count,  # 未获得精确资料时为 None
        "evidence": profile_evidence,
        "warnings": profile_warnings,
        "scope": "partial",
    }

register_analytics_routes(app, db_path_provider, account_refresher=refresh_account)
```

现有作品采集支持抖音、快手、小红书和 B站最近作品。新增资料采集入口 `utils.analytics.collectors.profile.collect_account_profile_sync(account_file, platform)` 复用项目浏览器配置，访问已有创作者首页，读取明确账号资料字段或页面粉丝标签。它不猜测额外接口；未获得精确数字、数字为“1.2 万”等缩写或多个来源冲突时返回空值和说明。通用解析与 DOM 规则已用夹具测试，实际平台页面需使用真实登录账号进一步核验。

## 统计口径

- 作品累计值：截至结束日期，所有已实际观测作品的各自最新值；并非账号全量作品总计。开始日期只控制发布数和增长；作品列表还按发布时间过滤。
- 区间增长：同一作品后一次有效观测落在查询区间时，使用之前最近已有的真实有效观测作为基线。真正首次观测没有基线，保持空值；平台累计量下降保留负修正。缺失中间样本时可使用最近已知基线，但差值涵盖整个观测跨度。
- 日趋势：增量归属第二次观测所在日期，支持每天只采集一次时计算实际观测差值。响应的 `intervalStart`/`intervalEnd` 给出实际覆盖跨度，`crossesRangeStart` 和边界说明标明差值包含查询开始前的时间。它表达观测差值，而非还原平台自然日精确流量；没有真正基线的观测仍为空。
- 发布数：查询区间内被实际观测、具有发布时间且非草稿/审核中/待发布的作品数量。受最近作品采集范围限制，不能作为全量发布数量。
- 粉丝总数：账号最近一次明确已知值。资料获取失败保留原值，并用 `followerLastSyncedAt` 和 `followerStatus=stale` 区分旧资料。区间增长需要两次精确资料观测；没有资料时保持空值。
- 环比：上一周期与当前区间长度相同，增长口径一致；上一周期为空或零时不生成误导性百分比。
- 负责人：按当前账号负责人分组，不代表历史发布人或过去负责人的数据归属。标签可用于账号分组筛选。
- 排行：账号与负责人流量排行使用区间观测增量；作品排行使用作品累计指标。缺失指标放在末尾且不分配名次。

响应中的 `coverage` 给出样本范围、基线/可比较作品数、各指标可比较样本数、粉丝样本账号数和最后观测时间。旧采集器的缺失作品字段可能补零，分析快照会检查保留的原响应字段，将缺失指标恢复为空；旧接口返回结构保持兼容。

## API

JSON 响应使用 `{code,msg,data}`。公共参数：`startDate`/`endDate`、`platform`、`accountId`、`owner`、`tag`（或 `group`）、`keyword`、账号 `status=0|1`、`page`/`pageSize`、`sortBy`/`sortOrder`。日期默认近 30 日，最多 366 日；每页最多 200 条。空负责人表示不过滤，`owner=__unassigned__` 表示只看未分配账号。

| 方法和路径 | 用途 |
| --- | --- |
| GET `/api/analytics/capabilities` | 平台能力与指标口径 |
| GET `/api/analytics/overview` | 汇总、环比、趋势、平台汇总 |
| GET `/api/analytics/accounts` | 累计账号指标及区间增长 |
| GET `/api/analytics/works` | 作品累计指标及区间增长 |
| GET `/api/analytics/owners` | 当前负责人汇总 |
| GET `/api/analytics/rankings?entity=accounts&metric=playCount` | 账号/作品/负责人排行 |
| GET `/api/analytics/export?entity=works` | 全部筛选结果的 UTF-8 BOM CSV |
| GET `/api/analytics/account-settings` | 当前账号负责人与标签 |
| PUT/PATCH `/api/analytics/account-settings` | 保存 `{accountId,owner,tags}` |
| POST `/api/analytics/accounts/<accountId>/refresh` | `{limit:5}`，先采集再保存快照 |

刷新复用旧统计缓存写入的快照钩子，同一事务更新累计缓存、作品快照和粉丝资料，不产生重复快照。调用者需提供已校验账号和 Cookie 路径的采集函数。主应用的访问认证应覆盖这些 API；本模块不单独建立第二套认证。

业务时区由环境变量 `OMNIPOST_ANALYTICS_TIMEZONE` 配置，默认 `Asia/Shanghai`。它控制新采集时间、默认日期和有时区输入的转换；UTC 使用 `UTC`。其他 IANA 时区需系统提供时区数据库，Windows 可安装 `tzdata`；默认中国时区在缺少数据库时使用 UTC+8 回退，不增加必需依赖。旧缓存和既有作品发布时间不包含时区，新模块按配置时区解释，无法自动推断旧宿主机时区并回溯更正。

CSV 排除会话字段，缺失指标留空，导出文本以 `= + - @` 开头时转义，避免表格公式注入；负数增长保留为数值。

本轮新增 `push.py` 提供钉钉、飞书和企业微信机器人日报/周报/月报推送，使用独立持久化配置与发送审计。默认关闭，保存配置不发送；手动发送须显式提交，定时任务检查当前频次、时区和发送时间，并通过数据库幂等去重。未知发送结果需人工核查，不能自动重发；返回界面时隐藏机器人地址授权参数和密钥。原作品统计的钉钉推送接口保持兼容。完整配置、操作与验证限制见 [运营工作台文档](../../docs/operations.md)。

## 验证

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_analytics*.py'
.venv/bin/python -m unittest discover -s tests -p 'test_douyin_content_stats.py'
```

测试覆盖真实 SQLite 写入/回滚、旧缓存基线迁移、样本缩减、增长边界、缺失粉丝与指标、负责人和标签过滤、累计及增量排序、排行、分页、导出公式转义、独立 Flask 路由和粉丝字段提取。`tests/test_analytics_push.py` 的 25 项测试使用请求替身，验证三渠道官方域名限制、默认关闭、保存不发送、凭据脱敏、日报/周报/月报和时区边界、并发幂等、未知结果核查、设置变更与停用、实际基线日报以及报表缺失指标说明；没有向真实群聊发送。

浏览器平台真实账号资料采集、三渠道真实机器人送达、Windows/Linux 和长期历史规模尚需验证。具体验收范围以运营文档中的当前记录为准。

"""以真实观测区间计算增长、排行榜和负责人汇总，保留缺失指标。"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .store import METRICS, bootstrap_legacy_stats, business_now, business_today, ensure_analytics_tables

PLATFORMS = {
    "xiaohongshu": (1, "小红书"), "channels": (2, "视频号"),
    "douyin": (3, "抖音"), "kuaishou": (4, "快手"),
    "baijiahao": (5, "百家号"), "bilibili": (6, "B站"),
    "toutiao": (7, "今日头条"), "sohu": (8, "搜狐"), "zhihu": (9, "知乎"),
}
WORK_STATS_PLATFORMS = {"douyin", "kuaishou", "xiaohongshu", "bilibili"}
ACCOUNT_STATS_PLATFORMS = WORK_STATS_PLATFORMS
METRIC_LABELS = {
    "playCount": "播放/阅读", "likeCount": "点赞", "commentCount": "评论",
    "shareCount": "分享", "collectCount": "收藏", "publishedCount": "发布数",
    "followerCount": "粉丝总数", "newFollowers": "新增粉丝",
}
COVERAGE_MESSAGE = ("仅统计实际采集到的作品；累计值为已观测作品的最新值。"
                    "增长使用已有真实基线，首次观测为空。差值按第二次观测日期归属，"
                    "可能涵盖查询开始前的采集区间，不能视为自然日精确流量。")


class AnalyticsError(ValueError):
    """可直接向调用者说明的参数或账号错误。"""

    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Filters:
    """公共筛选器；只接受白名单字段，所有 SQL 值均由绑定参数传入。"""
    start: date
    end: date
    platform: str = ""
    account_id: int | None = None
    owner: str | None = None
    tag: str = ""
    keyword: str = ""
    status: str = ""
    page: int = 1
    page_size: int = 20
    sort_by: str = "playCount"
    descending: bool = True

    @classmethod
    def from_params(cls, params):
        """日期范围最多一年，分页上限 200，避免不受控查询和图表响应。"""
        try:
            end = date.fromisoformat(params.get("endDate") or business_today().isoformat())
            start = date.fromisoformat(params.get("startDate") or (end - timedelta(days=29)).isoformat())
            account_id = int(params["accountId"]) if params.get("accountId") else None
            page = int(params.get("page") or 1)
            page_size = int(params.get("pageSize") or 20)
        except (ValueError, TypeError, KeyError) as exc:
            raise AnalyticsError("日期、账号或分页参数无效") from exc
        if start > end or (end - start).days > 365:
            raise AnalyticsError("日期范围需按先后顺序，且最多 366 天")
        if page < 1 or not 1 <= page_size <= 200 or (account_id is not None and account_id < 1):
            raise AnalyticsError("分页或账号参数超出范围")
        platform = str(params.get("platform") or "").lower()
        if platform == "all":
            platform = ""
        if platform and platform not in PLATFORMS:
            raise AnalyticsError("平台参数无效")
        status = str(params.get("status") or "")
        if status and status not in {"0", "1"}:
            raise AnalyticsError("账号状态仅支持 0 或 1")
        order = str(params.get("sortOrder") or "desc").lower()
        if order not in {"asc", "desc", "ascending", "descending"}:
            raise AnalyticsError("排序方向无效")
        return cls(start, end, platform, account_id, params.get("owner") or None,
                   str(params.get("tag") or params.get("group") or ""),
                   str(params.get("keyword") or "").strip(), status,
                   page, page_size, str(params.get("sortBy") or "playCount"),
                   order in {"desc", "descending"})

    @property
    def start_at(self):
        return self.start.isoformat() + " 00:00:00.000000"

    @property
    def end_at(self):
        return (self.end + timedelta(days=1)).isoformat() + " 00:00:00.000000"

    def previous(self):
        """使用长度相同且紧邻当前区间的上一周期计算环比。"""
        size = (self.end - self.start).days + 1
        return Filters(**{**self.__dict__, "start": self.start - timedelta(days=size),
                          "end": self.start - timedelta(days=1)})


def _sum_known(values):
    """所有输入均缺失时保留为空，有明确观测值时才参与求和。"""
    values = [value for value in values if value is not None]
    return sum(values) if values else None


def _safe_json(value, fallback):
    try:
        result = json.loads(value or "")
        return result if isinstance(result, type(fallback)) else fallback
    except (TypeError, ValueError):
        return fallback


def _published_in(row, filters):
    """发布时间缺失或草稿/待定时发布的作品不计入发布数。"""
    published = str(row.get("published_at") or "")[:10]
    status = str(row.get("status") or "")
    return bool(published and filters.start.isoformat() <= published <= filters.end.isoformat()
                and not any(value in status for value in ("草稿", "定时", "审核", "待发布", "发布中", "未发布", "失败")))


def _observed_intervals(history, filters, column):
    """后一次观测在区间内即可使用最近的真实基线，同时公开跨边界观测跨度。"""
    known = [row for row in history if row.get(column) is not None]
    intervals = []
    for prior, current in zip(known, known[1:]):
        if (prior["observed_at"] < current["observed_at"]
                and filters.start_at <= current["observed_at"] < filters.end_at):
            intervals.append({"date": current["observed_at"][:10], "change": current[column] - prior[column],
                              "intervalStart": prior["observed_at"], "intervalEnd": current["observed_at"],
                              "crossesRangeStart": prior["observed_at"] < filters.start_at})
    return intervals


def _growth(history, filters, column):
    """缺失真正基线时为空；平台累计量下降保留真实负修正，不截断为零。"""
    events = [(interval["date"], interval["change"]) for interval in _observed_intervals(history, filters, column)]
    return _sum_known(delta for _, delta in events), events


class AnalyticsService:
    """分析服务只查询本地快照；浏览器采集由路由注入，避免网络跨数据库事务。"""

    def __init__(self, db_path):
        self.db_path = Path(db_path)

    @contextmanager
    def connect(self):
        """短连接与自动回滚，兼容既有 SQLite 数据库而不修改账号字段。"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            ensure_analytics_tables(conn)
            bootstrap_legacy_stats(conn)
            conn.commit()
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _data(self, filters):
        """统一取账号、作品和粉丝历史，单次响应使用同一数据库读视图。"""
        with self.connect() as conn:
            conn.execute("BEGIN")
            accounts = []
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='user_info' AND type='table'").fetchone():
                # 明确白名单，账号 Cookie 路径绝不进入分析响应或导出。
                rows = conn.execute("""SELECT u.id,u.type,u.userName,u.status,
                    s.owner,s.tags_json FROM user_info u LEFT JOIN
                    analytics_account_settings s ON s.account_id=u.id ORDER BY u.id""").fetchall()
                for row in rows:
                    platform = next((name for name, meta in PLATFORMS.items() if meta[0] == row["type"]), "")
                    account = {"accountId": row["id"], "accountName": row["userName"],
                               "platform": platform, "platformLabel": PLATFORMS.get(platform, (0, "未知平台"))[1],
                               "status": row["status"], "owner": row["owner"] or "",
                               "tags": _safe_json(row["tags_json"], [])}
                    if self._matches_account(account, filters):
                        accounts.append(account)
            selected = {account["accountId"]: account for account in accounts}
            histories = {}
            fans = {}
            runs = []
            # 使用连接上的只读事务保证各组查询具有同一快照。
            for raw in conn.execute("SELECT * FROM analytics_work_snapshots WHERE observed_at<? ORDER BY observed_at,run_id", (filters.end_at,)):
                row = dict(raw)
                account = selected.get(row["account_id"])
                if account and account["platform"] == row["platform"]:
                    histories.setdefault((row["platform"], row["account_id"], row["item_id"]), []).append(row)
            if filters.keyword:
                # 按最新标题选作品后保留完整历史，标题改名不能让既有基线丢失。
                histories = {key: history for key, history in histories.items()
                             if filters.keyword.lower() in (history[-1]["title"] or "").lower()
                             or filters.keyword.lower() in selected[key[1]]["accountName"].lower()}
                matched = {key[1] for key in histories}
                accounts = [account for account in accounts if account["accountId"] in matched
                            or filters.keyword.lower() in account["accountName"].lower()]
                selected = {account["accountId"]: account for account in accounts}
            for raw in conn.execute("SELECT * FROM analytics_account_snapshots WHERE observed_at<? ORDER BY observed_at,id", (filters.end_at,)):
                row = dict(raw)
                account = selected.get(row["account_id"])
                if account and row["platform"] == account["platform"]:
                    fans.setdefault(row["account_id"], []).append(row)
            for raw in conn.execute("SELECT * FROM analytics_sync_runs WHERE synced_at<? ORDER BY synced_at,id", (filters.end_at,)):
                row = dict(raw)
                account = selected.get(row["account_id"])
                if account and row["platform"] == account["platform"]:
                    runs.append(row)
            return accounts, histories, fans, runs

    @staticmethod
    def _matches_account(account, filters):
        """平台、负责人、标签和状态组合筛选；未分配负责人使用显式值。"""
        return not (
            (filters.platform and account["platform"] != filters.platform)
            or (filters.account_id and account["accountId"] != filters.account_id)
            or (filters.owner is not None and account["owner"] != ("" if filters.owner == "__unassigned__" else filters.owner))
            or (filters.tag and filters.tag not in account["tags"])
            or (filters.status and str(account["status"]) != filters.status))

    @staticmethod
    def _coverage(histories, fans, runs, filters):
        """覆盖范围保留实际批次信息，少量最近作品不能宣称账号全量数据。"""
        comparable = sum(any(_observed_intervals(history, filters, column) for column in METRICS.values())
                         for history in histories.values())
        intervals = [interval for history in histories.values() for column in METRICS.values()
                     for interval in _observed_intervals(history, filters, column)]
        intervals.extend(interval for history in fans.values() for interval in _observed_intervals(history, filters, "follower_count"))
        observed = [row["observed_at"] for history in [*histories.values(), *fans.values()] for row in history]
        known_fans = [row for history in fans.values() for row in history if row["follower_count"] is not None]
        return {"scope": "partial", "message": COVERAGE_MESSAGE,
                "baselineCount": sum(len(history) == 1 for history in histories.values()), "comparableCount": comparable,
                "uncomparableCount": len(histories) - comparable,
                "intervalStart": min((interval["intervalStart"] for interval in intervals), default=None),
                "intervalEnd": max((interval["intervalEnd"] for interval in intervals), default=None),
                "crossesRangeStart": any(interval["crossesRangeStart"] for interval in intervals),
                "boundaryMessage": "差值覆盖上一次真实采集以来的区间，包含查询开始前时间，不能视为自然日精确流量" if any(interval["crossesRangeStart"] for interval in intervals) else None,
                "firstObservedAt": min(observed) if observed else None,
                "lastSyncedAt": max([row["synced_at"] for row in runs] +
                                     [row["observed_at"] for history in fans.values() for row in history], default=None),
                "followerDataAvailable": bool(known_fans),
                "followerSampleCount": len({row["account_id"] for row in known_fans}),
                "followerScope": "partial",
                "metricComparableWorkCounts": {key: sum(_growth(history, filters, column)[0] is not None
                                                        for history in histories.values()) for key, column in METRICS.items()},
                "workSampleCount": len(histories), "syncCount": len(runs),
                "metricBasis": "observed_increments", "dailyAttribution": "observation_date"}

    def overview(self, filters):
        """仪表盘返回观测增长、同长度上一周期和每日采样趋势。"""
        accounts, histories, fans, runs = self._data(filters)
        summary, trends = self._summarize(accounts, histories, fans, filters)
        previous_filters = filters.previous()
        old_accounts, old_histories, old_fans, _ = self._data(previous_filters)
        previous, _ = self._summarize(old_accounts, old_histories, old_fans, previous_filters)
        comparison = {}
        for key in ["publishedCount", "newFollowers", *METRICS]:
            current, prior = summary[key], previous[key]
            change = current - prior if current is not None and prior is not None else None
            comparison[key] = {"current": current, "previous": prior, "change": change,
                               "changePercent": round(change / abs(prior) * 100, 2) if change is not None and prior else None}
        platforms = []
        for platform in sorted({account["platform"] for account in accounts}):
            group = [account for account in accounts if account["platform"] == platform]
            identifiers = {account["accountId"] for account in group}
            metrics, _ = self._summarize(group, {key: value for key, value in histories.items() if key[1] in identifiers},
                                       {key: value for key, value in fans.items() if key in identifiers}, filters)
            platforms.append({"platform": platform, "platformLabel": PLATFORMS.get(platform, (0, "未知平台"))[1], **metrics})
        return {"range": {"startDate": filters.start.isoformat(), "endDate": filters.end.isoformat(),
                           "previousStartDate": previous_filters.start.isoformat(), "previousEndDate": previous_filters.end.isoformat()},
                "summary": summary, "comparison": comparison, "trends": trends,
                "platforms": platforms, "coverage": self._coverage(histories, fans, runs, filters)}

    @staticmethod
    def _summarize(accounts, histories, fans, filters):
        """发布数是区间内被实际观测的发布记录，流量是相邻样本增量。"""
        trends = {}
        day = filters.start
        while day <= filters.end:
            trends[day.isoformat()] = {"date": day.isoformat(), "publishedCount": 0, "newFollowers": None,
                                      "intervalStart": None, "intervalEnd": None, "crossesRangeStart": False,
                                      **{key: None for key in METRICS}}
            day += timedelta(days=1)
        summary = {"accountCount": len(accounts), "workCount": len(histories),
                   "publishedCount": 0, "followerCount": None, "newFollowers": None,
                   **{key: None for key in METRICS}}
        for history in histories.values():
            latest = history[-1]
            if _published_in(latest, filters):
                summary["publishedCount"] += 1
                trends[latest["published_at"][:10]]["publishedCount"] += 1
            for key, column in METRICS.items():
                value, events = _growth(history, filters, column)
                summary[key] = _sum_known([summary[key], value])
                for day, delta in events:
                    trends[day][key] = _sum_known([trends[day][key], delta])
                for interval in _observed_intervals(history, filters, column):
                    AnalyticsService._merge_trend_interval(trends[interval["date"]], interval)
        for history in fans.values():
            known = [row for row in history if row["follower_count"] is not None]
            if known:
                summary["followerCount"] = _sum_known([summary["followerCount"], known[-1]["follower_count"]])
            value, events = _growth(known, filters, "follower_count")
            summary["newFollowers"] = _sum_known([summary["newFollowers"], value])
            for day, delta in events:
                trends[day]["newFollowers"] = _sum_known([trends[day]["newFollowers"], delta])
            for interval in _observed_intervals(known, filters, "follower_count"):
                AnalyticsService._merge_trend_interval(trends[interval["date"]], interval)
        return summary, list(trends.values())

    @staticmethod
    def _merge_trend_interval(trend, interval):
        """每日聚合保留观测跨度，前端可显示差值实际覆盖的起止时间。"""
        trend["intervalStart"] = min(value for value in (trend["intervalStart"], interval["intervalStart"]) if value)
        trend["intervalEnd"] = max(value for value in (trend["intervalEnd"], interval["intervalEnd"]) if value)
        trend["crossesRangeStart"] = trend["crossesRangeStart"] or interval["crossesRangeStart"]

    def accounts(self, filters, paginate=True):
        """账号表累计量与区间增长分开提供，刷新范围和最后采样时间明确可见。"""
        accounts, histories, fans, runs = self._data(filters)
        items = []
        for account in accounts:
            if filters.keyword and filters.keyword.lower() not in account["accountName"].lower():
                # 标题搜索也可选中有匹配作品的账号。
                if not any(key[1] == account["accountId"] for key in histories):
                    continue
            related = {key: value for key, value in histories.items() if key[1] == account["accountId"]}
            account_fans = {key: value for key, value in fans.items() if key == account["accountId"]}
            account_runs = [run for run in runs if run["account_id"] == account["accountId"]]
            summary, _ = self._summarize([account], related, account_fans, filters)
            coverage = self._coverage(related, account_fans, account_runs, filters)
            fan_history = account_fans.get(account["accountId"], [])
            known_fans = [row for row in fan_history if row["follower_count"] is not None]
            item = {**account, "workCount": len(related), "publishedCount": summary["publishedCount"],
                    "followerCount": summary["followerCount"], "newFollowers": summary["newFollowers"],
                    "growth": {key: summary[key] for key in METRICS},
                    "lastSyncedAt": coverage["lastSyncedAt"], "coverage": coverage,
                    "intervalStart": coverage["intervalStart"], "intervalEnd": coverage["intervalEnd"],
                    "crossesRangeStart": coverage["crossesRangeStart"],
                    "followerLastSyncedAt": known_fans[-1]["observed_at"] if known_fans else None,
                    "followerStatus": ("stale" if fan_history and fan_history[-1]["follower_count"] is None else "available") if known_fans else "missing",
                    "statsSupported": account["platform"] in WORK_STATS_PLATFORMS}
            for key, column in METRICS.items():
                item[key] = _sum_known(history[-1][column] for history in related.values())
            items.append(item)
        return self._page(items, filters, self._coverage(histories, fans, runs, filters), paginate)

    def works(self, filters, paginate=True):
        """作品列表按真实发布时间筛选，保留历史样本而不随最近作品缓存缩短。"""
        accounts, histories, fans, runs = self._data(filters)
        by_id = {account["accountId"]: account for account in accounts}
        items = []
        for history in histories.values():
            latest = history[-1]
            if not _published_in(latest, filters):
                continue
            account = by_id[latest["account_id"]]
            coverage = self._coverage({(latest["platform"], latest["account_id"], latest["item_id"]): history}, {}, [], filters)
            item = {**account, "itemId": latest["item_id"], "title": latest["title"],
                    "coverUrl": latest["cover_url"], "status": latest["status"],
                    "publishedAt": latest["published_at"], "firstObservedAt": history[0]["observed_at"],
                    "lastSyncedAt": latest["observed_at"], "isBaseline": len(history) == 1,
                    "intervalStart": coverage["intervalStart"], "intervalEnd": coverage["intervalEnd"],
                    "crossesRangeStart": coverage["crossesRangeStart"],
                    "growth": {key: _growth(history, filters, column)[0] for key, column in METRICS.items()},
                    **{key: latest[column] for key, column in METRICS.items()}}
            items.append(item)
        return self._page(items, filters, self._coverage(histories, fans, runs, filters), paginate)

    def owners(self, filters, paginate=True):
        """负责人以当前账号归属汇总，不伪造历史发布人或过去负责人变更。"""
        accounts, histories, fans, runs = self._data(filters)
        items = []
        for owner in sorted({account["owner"] for account in accounts}):
            group = [account for account in accounts if account["owner"] == owner]
            identifiers = {account["accountId"] for account in group}
            summary, _ = self._summarize(group, {key: value for key, value in histories.items() if key[1] in identifiers},
                                       {key: value for key, value in fans.items() if key in identifiers}, filters)
            items.append({"owner": owner, "ownerLabel": owner or "未分配", **summary})
        return self._page(items, filters, self._coverage(histories, fans, runs, filters), paginate)

    def rankings(self, filters, entity="accounts", metric="playCount"):
        """账号/负责人流量排行按区间增量，作品排行按该作品当前累计值。"""
        if entity not in {"accounts", "works", "owners"} or metric not in METRIC_LABELS:
            raise AnalyticsError("排行榜对象或指标无效")
        if entity == "works" and metric in {"followerCount", "newFollowers", "publishedCount"}:
            raise AnalyticsError("作品排行榜不支持该指标")
        payload = getattr(self, entity)(filters, paginate=False)
        for item in payload["items"]:
            item["metricValue"] = item["growth"].get(metric) if entity == "accounts" and metric in METRICS else item.get(metric)
        # 缺失值始终排末尾，不参与任何增长名次判断。
        known = sorted([item for item in payload["items"] if item["metricValue"] is not None], key=lambda item: item["metricValue"], reverse=True)
        for index, item in enumerate(known, 1):
            item["rank"] = index
        missing = [dict(item, rank=None) for item in payload["items"] if item["metricValue"] is None]
        items = known + missing
        offset = (filters.page - 1) * filters.page_size
        return {**payload, "entity": entity, "metric": metric, "items": items[offset:offset + filters.page_size],
                "page": filters.page, "pageSize": filters.page_size}

    @staticmethod
    def _page(items, filters, coverage, paginate):
        """白名单排序，缺失值在正反排序中均放到最后。"""
        allowed = set(METRIC_LABELS) | {"accountName", "platform", "publishedAt", "lastSyncedAt", "workCount", "owner", "title"}
        allowed.update("growth." + key for key in METRICS)
        if filters.sort_by not in allowed:
            raise AnalyticsError("排序字段无效")
        def sort_value(item):
            """增量模式显式按增长字段排序，不误用累计量替代。"""
            return item.get("growth", {}).get(filters.sort_by[7:]) if filters.sort_by.startswith("growth.") else item.get(filters.sort_by)
        known = [item for item in items if sort_value(item) is not None]
        missing = [item for item in items if sort_value(item) is None]
        known.sort(key=sort_value, reverse=filters.descending)
        items = known + missing
        total = len(items)
        if paginate:
            offset = (filters.page - 1) * filters.page_size
            items = items[offset:offset + filters.page_size]
        return {"items": items, "total": total, "page": filters.page,
                "pageSize": filters.page_size, "coverage": coverage}

    def account_settings(self):
        """列出真实注册账号的归属配置，不返回任何会话文件信息。"""
        return {"items": [{key: account[key] for key in ("accountId", "platform", "accountName", "owner", "tags")}
                          for account in self._data(Filters(business_today() - timedelta(days=29), business_today()))[0]]}

    def update_account_settings(self, account_id, owner, tags):
        """仅编辑负责人和标签，严格限制结构及大小以保护公共 API。"""
        try:
            account_id = int(account_id)
        except (TypeError, ValueError) as exc:
            raise AnalyticsError("账号参数无效") from exc
        if not isinstance(owner, str) or len(owner) > 100:
            raise AnalyticsError("负责人应为最多 100 字的字符串")
        if not isinstance(tags, list) or len(tags) > 30 or any(not isinstance(tag, str) or not tag.strip() or len(tag) > 50 for tag in tags):
            raise AnalyticsError("标签应为最多 30 项、每项最多 50 字的非空字符串数组")
        tags = list(dict.fromkeys(tag.strip() for tag in tags))
        with self.connect() as conn:
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='user_info' AND type='table'").fetchone()
            if not exists or not conn.execute("SELECT 1 FROM user_info WHERE id=?", (account_id,)).fetchone():
                raise AnalyticsError("账号不存在", 404)
            conn.execute("""INSERT INTO analytics_account_settings(account_id,owner,tags_json,updated_at)
                VALUES (?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET owner=excluded.owner,
                tags_json=excluded.tags_json,updated_at=excluded.updated_at""",
                (account_id, owner.strip(), json.dumps(tags, ensure_ascii=False), business_now().isoformat()))
        return next(item for item in self.account_settings()["items"] if item["accountId"] == account_id)

    def account(self, account_id):
        """查找刷新目标，后端以数据库平台为准，不信任前端传入平台。"""
        try:
            account_id = int(account_id)
        except (ValueError, TypeError) as exc:
            raise AnalyticsError("账号参数无效") from exc
        result = self._data(Filters(business_today() - timedelta(days=29), business_today(), account_id=account_id))[0]
        if not result:
            raise AnalyticsError("账号不存在", 404)
        return result[0]

    def export_csv(self, filters, entity="works"):
        """导出全部筛选结果并转义公式起始符，缺失值为空、增长口径另列说明。"""
        if entity not in {"accounts", "works", "owners"}:
            raise AnalyticsError("导出对象无效")
        items = getattr(self, entity)(filters, paginate=False)["items"]
        columns = ["platformLabel", "accountName", "owner", "tags", "title", "publishedAt",
                   "accountCount", "workCount", "publishedCount", "followerCount", "newFollowers", *METRICS,
                   *("growth." + key for key in METRICS), "lastSyncedAt"]
        columns = [column for column in columns if column.startswith("growth.") and entity in {"accounts", "works"}
                   or any(column in item for item in items)] or ["platformLabel", "accountName", "owner", "publishedCount", *METRICS]
        labels = {"platformLabel": "平台", "accountName": "账号", "owner": "负责人", "tags": "标签",
                  "title": "作品标题", "publishedAt": "发布时间", "accountCount": "账号数", "workCount": "已采集作品数",
                  "lastSyncedAt": "最后观测时间", **METRIC_LABELS}
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["区间观测增长：" + METRIC_LABELS[column[7:]] if column.startswith("growth.") else labels[column] for column in columns])
        for item in items:
            values = []
            for column in columns:
                value = item.get("growth", {}).get(column[7:]) if column.startswith("growth.") else item.get(column)
                if isinstance(value, list):
                    value = "、".join(str(entry) for entry in value)
                text = "" if value is None else str(value)
                # 表格软件可能忽略前导空白；负增量保留为数值，外部文本必须防公式注入。
                if isinstance(value, str) and text.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
                    text = "'" + text
                values.append(text)
            writer.writerow(values)
        return "\ufeff" + output.getvalue()


def capabilities():
    """公开能力按当前真实采集器列举，其他平台仅展示注册账号。"""
    return {"platforms": [{"platform": name, "platformLabel": meta[1], "accountType": meta[0],
                            "workStatsSupported": name in WORK_STATS_PLATFORMS,
                            "accountStatsSupported": name in ACCOUNT_STATS_PLATFORMS,
                            "followerCountSupported": name in ACCOUNT_STATS_PLATFORMS}
                           for name, meta in PLATFORMS.items()],
            "metrics": [{"key": key, "label": label,
                          "description": "首次观测为基线，缺失数据保留为空"} for key, label in METRIC_LABELS.items()],
            "notes": [COVERAGE_MESSAGE, "账号、负责人和标签按当前配置归属；历史发布人未采集。",
                      "粉丝数来自实际登录页面资料，未采集或页面不可读时为空。"]}

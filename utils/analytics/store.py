"""只增加分析表；首次观测是基线，采集失败不能覆盖已知数据。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

METRICS = {
    "playCount": "play_count", "likeCount": "like_count",
    "commentCount": "comment_count", "shareCount": "share_count",
    "collectCount": "collect_count",
}

_SOURCE_KEYS = {
    "douyin": {"play_count": ("play_count", "playCount", "view_count"),
               "like_count": ("digg_count", "like_count", "likeCount"),
               "comment_count": ("comment_count", "commentCount"),
               "share_count": ("share_count", "shareCount"), "collect_count": ("collect_count", "collectCount")},
    "kuaishou": {"play_count": ("playCount", "viewCount"), "like_count": ("likeCount", "diggCount"),
                 "comment_count": ("commentCount",), "share_count": ("shareCount", "forwardCount"),
                 "collect_count": ("collectCount", "collect_count")},
    "xiaohongshu": {"play_count": ("view_count", "read_count"), "like_count": ("likes", "liked_count", "like_count"),
                    "comment_count": ("comments_count", "comment_count"), "share_count": ("shared_count", "share_count"),
                    "collect_count": ("collected_count", "collect_count")},
    "bilibili": {"play_count": ("view", "vv"), "like_count": ("like",), "comment_count": ("reply",),
                 "share_count": ("share",), "collect_count": ("favorite",)},
}

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS analytics_sync_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL,
        account_id INTEGER NOT NULL, synced_at TEXT NOT NULL,
        scope TEXT NOT NULL DEFAULT 'partial', item_count INTEGER NOT NULL,
        source TEXT NOT NULL DEFAULT 'collector', message TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS analytics_work_snapshots (
        run_id INTEGER NOT NULL REFERENCES analytics_sync_runs(id),
        platform TEXT NOT NULL, account_id INTEGER NOT NULL, item_id TEXT NOT NULL,
        observed_at TEXT NOT NULL, title TEXT, cover_url TEXT, status TEXT,
        published_at TEXT, play_count INTEGER, like_count INTEGER,
        comment_count INTEGER, share_count INTEGER, collect_count INTEGER,
        PRIMARY KEY(run_id,item_id))""",
    "CREATE INDEX IF NOT EXISTS analytics_work_history ON analytics_work_snapshots(platform,account_id,item_id,observed_at)",
    """CREATE TABLE IF NOT EXISTS analytics_account_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT, platform TEXT NOT NULL,
        account_id INTEGER NOT NULL, observed_at TEXT NOT NULL,
        follower_count INTEGER, evidence_json TEXT NOT NULL DEFAULT '[]',
        UNIQUE(platform,account_id,observed_at))""",
    """CREATE TABLE IF NOT EXISTS analytics_account_settings (
        account_id INTEGER PRIMARY KEY, owner TEXT NOT NULL DEFAULT '',
        tags_json TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL)""",
)


def analytics_timezone():
    """业务日期统一使用配置时区，默认中国时间，不随执行机器的时区漂移。"""
    name = os.environ.get("OMNIPOST_ANALYTICS_TIMEZONE", "Asia/Shanghai").strip()
    if name in {"UTC", "Etc/UTC"}:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        if name == "Asia/Shanghai":
            # Windows 未安装 IANA 数据时，默认业务时区仍可使用当前中国 UTC+8。
            return timezone(timedelta(hours=8))
        raise ValueError("分析时区无效或缺少时区数据库，请检查 OMNIPOST_ANALYTICS_TIMEZONE")


def business_now() -> datetime:
    """采集快照、默认查询日期和负责人配置共用同一业务时钟。"""
    return datetime.now(analytics_timezone())


def business_today():
    return business_now().date()


def timestamp(value: str | datetime) -> str:
    """统一日期分隔符，保证来自旧缓存和采集器的时间可按字典序比较。"""
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(analytics_timezone()).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%d %H:%M:%S.%f")


def ensure_analytics_tables(conn) -> None:
    """逐句执行 DDL，避免 executescript 隐式提交破坏调用者的原子事务。"""
    for statement in SCHEMA:
        conn.execute(statement)


def nullable_count(value: Any) -> int | None:
    """缺失与无效值保留为空，平台确实返回零时才记录零。"""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
        if number < 0 or not number.is_integer():
            return None
        return int(number)
    except (TypeError, ValueError, OverflowError):
        return None


def observed_metric(item: dict, platform: str, column: str) -> int | None:
    """旧采集器将缺失字段补零；分析快照依据保留的原响应识别这些缺失。"""
    try:
        raw = json.loads(item.get("raw_json") or "")
    except (TypeError, ValueError):
        raw = None
    if isinstance(raw, dict) and platform in _SOURCE_KEYS:
        if platform == "douyin":
            raw = raw.get("statistics") or raw.get("stats") or {}
        elif platform == "bilibili":
            raw = raw.get("stat") or raw.get("Stat") or {}
        if not isinstance(raw, dict):
            return None
        for key in _SOURCE_KEYS[platform][column]:
            if key in raw:
                return nullable_count(raw[key])
        return None
    return nullable_count(item.get(column))


def record_content_snapshot(conn, *, platform: str, account_id: int,
                            items: list[dict], synced_at: str,
                            scope: str = "partial", source: str = "collector",
                            message: str = "仅包含本次实际采集的最近作品") -> int:
    """每个实际采集批次保存不可变作品快照，不把未返回的作品视为删除。"""
    ensure_analytics_tables(conn)
    observed_at = timestamp(synced_at)
    cursor = conn.execute("""INSERT INTO analytics_sync_runs
        (platform,account_id,synced_at,scope,item_count,source,message)
        VALUES (?,?,?,?,?,?,?)""", (platform, account_id, observed_at,
                                    scope, len(items), source, message))
    # 同一秒内的两次真实采集也分别保存，不能以粗时间戳去重丢失观测。
    run_id = cursor.lastrowid
    for item in items:
        item_id = str(item.get("item_id") or "").strip()
        if not item_id:
            raise ValueError("作品快照缺少 item_id")
        conn.execute("""INSERT OR IGNORE INTO analytics_work_snapshots
            (run_id,platform,account_id,item_id,observed_at,title,cover_url,status,
             published_at,play_count,like_count,comment_count,share_count,collect_count)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run_id, platform, account_id, item_id, observed_at,
             item.get("title") or "", item.get("cover_url") or "",
             item.get("status") or "", item.get("published_at") or "",
             *(observed_metric(item, platform, column) for column in METRICS.values())))
    return run_id


def record_account_snapshot(conn, *, platform: str, account_id: int,
                            synced_at: str, follower_count: int | None,
                            evidence: list | None = None) -> None:
    """保存资料采集证据；没有明确粉丝数的观测不会覆盖旧的已知粉丝数。"""
    ensure_analytics_tables(conn)
    conn.execute("""INSERT OR IGNORE INTO analytics_account_snapshots
        (platform,account_id,observed_at,follower_count,evidence_json)
        VALUES (?,?,?,?,?)""", (platform, account_id, timestamp(synced_at),
        nullable_count(follower_count), json.dumps(evidence or [], ensure_ascii=False)))


def bootstrap_legacy_stats(conn, platform: str | None = None,
                           account_id: int | None = None) -> None:
    """把已有累计缓存导入一次真实旧基线；绝不生成不存在的历史增长。"""
    ensure_analytics_tables(conn)
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='content_stats' AND type='table'").fetchone():
        return
    sql = """SELECT c.* FROM content_stats c WHERE NOT EXISTS (
        SELECT 1 FROM analytics_work_snapshots s WHERE s.platform=c.platform
        AND s.account_id=c.account_id AND s.item_id=c.item_id)"""
    params = []
    if platform is not None:
        sql += " AND c.platform=?"
        params.append(platform)
    if account_id is not None:
        sql += " AND c.account_id=?"
        params.append(account_id)
    cur = conn.execute(sql, params)
    columns = [column[0] for column in cur.description]
    grouped: dict[tuple, list] = {}
    for raw in cur.fetchall():
        row = dict(zip(columns, raw))
        try:
            observed_at = timestamp(row["synced_at"])
        except (KeyError, ValueError, TypeError):
            # 不可定位时间的旧缓存不能参与历史计算。
            continue
        grouped.setdefault((row["platform"], row["account_id"], observed_at), []).append(row)
    for (name, identifier, observed_at), items in grouped.items():
        record_content_snapshot(conn, platform=name, account_id=identifier,
            items=items, synced_at=observed_at, source="legacy_baseline",
            message="迁移已有累计缓存作为首次观测基线；不是完整历史")

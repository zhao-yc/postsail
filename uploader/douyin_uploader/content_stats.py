# uploader/douyin_uploader/content_stats.py
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from patchright.async_api import async_playwright

from conf import LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
from utils.base_social_media import set_init_script
from utils.log import douyin_logger


CONTENT_STATS_DDL = """
CREATE TABLE IF NOT EXISTS content_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    title TEXT,
    cover_url TEXT,
    status TEXT,
    published_at TEXT,
    play_count INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    share_count INTEGER DEFAULT 0,
    collect_count INTEGER DEFAULT 0,
    completion_rate REAL,
    avg_play_duration_sec REAL,
    bounce_rate_2s REAL,
    completion_rate_5s REAL,
    avg_play_percent REAL,
    traffic_sources_json TEXT,
    extra_json TEXT,
    boost_play_count INTEGER,
    boost_reason TEXT,
    synced_at TEXT NOT NULL,
    raw_json TEXT,
    UNIQUE(platform, account_id, item_id)
)
"""

_TRAFFIC_COLUMNS = (
    ("completion_rate", "REAL"),
    ("avg_play_duration_sec", "REAL"),
    ("bounce_rate_2s", "REAL"),
    ("completion_rate_5s", "REAL"),
    ("avg_play_percent", "REAL"),
    ("traffic_sources_json", "TEXT"),
    ("extra_json", "TEXT"),
    ("boost_play_count", "INTEGER"),
    ("boost_reason", "TEXT"),
)

DOUYIN_EXTRA_KEYS = (
    "completion_rate",
    "avg_play_duration_sec",
    "bounce_rate_2s",
    "completion_rate_5s",
    "avg_play_percent",
    "traffic_sources",
    "audience_gender",
    "audience_age",
    "audience_region",
)

_DISTRIBUTION_KEYS = (
    "traffic_sources",
    "audience_gender",
    "audience_age",
    "audience_region",
)


def build_douyin_extra(item: dict) -> dict:
    extra: dict[str, Any] = {}
    for key in DOUYIN_EXTRA_KEYS:
        if key in item and item.get(key) is not None:
            extra[key] = item.get(key)
    return extra


def dumps_extra_json(extra: dict | None) -> str | None:
    if not extra:
        return None
    return json.dumps(extra, ensure_ascii=False)


def loads_extra_json(raw: Any) -> dict:
    if raw is None or raw == "":
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        douyin_logger.warning("content_stats.extra_json is not valid JSON; ignoring")
        return {}
    return data if isinstance(data, dict) else {}


def _row_get(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key] if key in row.keys() else None
    except Exception:
        return None


def merge_traffic_fields_from_row(row: Any) -> dict:
    """Prefer extra_json keys; fall back to legacy REAL / traffic_sources_json."""
    extra = loads_extra_json(_row_get(row, "extra_json"))
    out: dict[str, Any] = {}
    for key in DOUYIN_EXTRA_KEYS:
        if key in _DISTRIBUTION_KEYS:
            if key in extra:
                sources = extra.get(key)
                out[key] = sources if isinstance(sources, list) else []
                continue
            if key == "traffic_sources":
                legacy = _row_get(row, "traffic_sources_json")
                if legacy:
                    try:
                        parsed = json.loads(legacy)
                        out["traffic_sources"] = parsed if isinstance(parsed, list) else []
                    except (TypeError, json.JSONDecodeError):
                        out["traffic_sources"] = []
                else:
                    out["traffic_sources"] = None if legacy is None else []
            else:
                out[key] = None
            continue

        if key in extra:
            out[key] = extra.get(key)
        else:
            out[key] = _row_get(row, key)
    return out


def row_to_stat_item(row: Any) -> dict:
    traffic = merge_traffic_fields_from_row(row)
    boost_count = _row_get(row, "boost_play_count")
    boost_reason = _row_get(row, "boost_reason")
    extra = loads_extra_json(_row_get(row, "extra_json"))
    extra_diagnose = extra.get("content_diagnose")
    if not isinstance(extra_diagnose, list):
        extra_diagnose = None
    extra_trends = extra.get("metric_trends")
    if not isinstance(extra_trends, list):
        extra_trends = None
    return {
        "itemId": _row_get(row, "item_id"),
        "title": _row_get(row, "title") or "",
        "coverUrl": _row_get(row, "cover_url") or "",
        "status": _row_get(row, "status") or "",
        "publishedAt": _row_get(row, "published_at") or "",
        "playCount": _row_get(row, "play_count") or 0,
        "likeCount": _row_get(row, "like_count") or 0,
        "commentCount": _row_get(row, "comment_count") or 0,
        "shareCount": _row_get(row, "share_count") or 0,
        "collectCount": _row_get(row, "collect_count") or 0,
        "completionRate": traffic.get("completion_rate"),
        "avgPlayDurationSec": traffic.get("avg_play_duration_sec"),
        "bounceRate2s": traffic.get("bounce_rate_2s"),
        "completionRate5s": traffic.get("completion_rate_5s"),
        "avgPlayPercent": traffic.get("avg_play_percent"),
        "trafficSources": traffic.get("traffic_sources"),
        "audienceGender": traffic.get("audience_gender"),
        "audienceAge": traffic.get("audience_age"),
        "audienceRegion": traffic.get("audience_region"),
        "boostPlayCount": None if boost_count is None else boost_count,
        "boostReason": (str(boost_reason).strip() if boost_reason else None) or None,
        "contentDiagnose": extra_diagnose,
        "metricTrends": extra_trends,
    }


DOUYIN_LIST_URL_HINTS = (
    "janus/douyin/creator/pc/work_list",
    "creator/pc/work_list",
    "work_list",
    "aweme/v1/creator/item/list",
    "creator/item/list",
    "item/list",
    "content/item",
)

# Creator center current list API (actively fetched as fallback if intercept misses).
# page_size 取大一些，便于去掉置顶干扰后再按发布时间排序。
WORK_LIST_API = (
    "https://creator.douyin.com/janus/douyin/creator/pc/work_list"
    "?page_size={page_size}&page_num=1&status=0"
)


def ensure_content_stats_table(conn) -> None:
    conn.execute(CONTENT_STATS_DDL)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(content_stats)").fetchall()}
    for name, col_type in _TRAFFIC_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE content_stats ADD COLUMN {name} {col_type}")
    _migrate_legacy_traffic_into_extra_json(conn)
    conn.commit()


def _migrate_legacy_traffic_into_extra_json(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(content_stats)").fetchall()}
    if "extra_json" not in cols:
        return
    rows = conn.execute(
        """
        SELECT id, completion_rate, avg_play_duration_sec, bounce_rate_2s, completion_rate_5s,
               avg_play_percent, traffic_sources_json, extra_json
        FROM content_stats
        WHERE extra_json IS NULL OR extra_json = ''
        """
    ).fetchall()
    for row in rows:
        (
            row_id,
            completion_rate,
            avg_play_duration_sec,
            bounce_rate_2s,
            completion_rate_5s,
            avg_play_percent,
            traffic_sources_json,
            _extra,
        ) = row
        if all(
            v is None
            for v in (
                completion_rate,
                avg_play_duration_sec,
                bounce_rate_2s,
                completion_rate_5s,
                avg_play_percent,
                traffic_sources_json,
            )
        ):
            continue
        item = {
            "completion_rate": completion_rate,
            "avg_play_duration_sec": avg_play_duration_sec,
            "bounce_rate_2s": bounce_rate_2s,
            "completion_rate_5s": completion_rate_5s,
            "avg_play_percent": avg_play_percent,
        }
        if traffic_sources_json:
            try:
                sources = json.loads(traffic_sources_json)
                if isinstance(sources, list):
                    item["traffic_sources"] = sources
            except (TypeError, json.JSONDecodeError):
                pass
        extra = build_douyin_extra(item)
        if not extra:
            continue
        conn.execute(
            "UPDATE content_stats SET extra_json = ? WHERE id = ?",
            (dumps_extra_json(extra), row_id),
        )


def normalize_count(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _first_url(node: Any) -> str:
    if isinstance(node, dict):
        url_list = node.get("url_list") or node.get("urlList") or []
        if isinstance(url_list, list) and url_list:
            return str(url_list[0] or "")
        for key in ("url", "uri", "cover_url", "coverUrl"):
            if node.get(key):
                return str(node[key])
        for child in node.values():
            found = _first_url(child)
            if found:
                return found
    elif isinstance(node, list):
        for child in node:
            found = _first_url(child)
            if found:
                return found
    return ""


def _extract_list(payload: dict) -> list:
    if not isinstance(payload, dict):
        return []
    for key in ("work_list", "aweme_list", "item_list", "list", "works"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_list(data)
    if isinstance(data, list):
        return data
    return []


def _status_text(raw: dict) -> str:
    status = raw.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip()
    if isinstance(status, dict):
        if status.get("is_private"):
            return "私密"
        for key in ("status_desc", "desc", "name"):
            if status.get(key):
                return str(status[key])
    for key in ("status_desc", "item_status_desc", "audit_status_desc"):
        if raw.get(key):
            return str(raw[key])
    return "已发布"


def _published_at(raw: dict) -> str:
    ts = raw.get("create_time") or raw.get("createTime") or raw.get("publish_time")
    if ts is None:
        return ""
    try:
        ts_i = int(ts)
        if ts_i > 10_000_000_000:  # ms
            ts_i //= 1000
        return datetime.fromtimestamp(ts_i, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(ts)


def parse_douyin_item(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    item_id = raw.get("aweme_id") or raw.get("item_id") or raw.get("itemId") or raw.get("id")
    if item_id is None or str(item_id).strip() == "":
        return None
    stats = raw.get("statistics") or raw.get("stats") or {}
    if not isinstance(stats, dict):
        stats = {}
    cover = ""
    video = raw.get("video") or {}
    if isinstance(video, dict):
        cover = _first_url(video.get("cover") or video.get("origin_cover") or video)
    if not cover:
        cover = _first_url(raw.get("cover") or raw.get("cover_url"))
    return {
        "item_id": str(item_id),
        "title": str(raw.get("desc") or raw.get("title") or raw.get("caption") or ""),
        "cover_url": cover,
        "status": _status_text(raw),
        "published_at": _published_at(raw),
        "play_count": normalize_count(
            stats.get("play_count", stats.get("playCount", stats.get("view_count", 0)))
        ),
        "like_count": normalize_count(
            stats.get("digg_count", stats.get("like_count", stats.get("likeCount", 0)))
        ),
        "comment_count": normalize_count(
            stats.get("comment_count", stats.get("commentCount", 0))
        ),
        "share_count": normalize_count(
            stats.get("share_count", stats.get("shareCount", 0))
        ),
        "collect_count": normalize_count(
            stats.get("collect_count", stats.get("collectCount", 0))
        ),
        "completion_rate": None,
        "avg_play_duration_sec": None,
        "bounce_rate_2s": None,
        "completion_rate_5s": None,
        "avg_play_percent": None,
        "traffic_sources": None,
        "raw_json": json.dumps(raw, ensure_ascii=False)[:8000],
    }


def normalize_percent(value: Any) -> float | None:
    """Normalize to percent number (28.13 means 28.13%). Values in (0,1] treated as ratios."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        s = value.strip().replace("%", "")
        if not s:
            return None
        try:
            value = float(s)
        except ValueError:
            return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if 0 < num <= 1:
        num *= 100.0
    return round(num, 2)


def _dig(node: Any, *paths: tuple[str, ...]) -> Any:
    """Return first found value for any dotted path tuple of keys."""
    if not isinstance(node, dict):
        return None
    for path in paths:
        cur: Any = node
        ok = True
        for key in path:
            if not isinstance(cur, dict) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if ok:
            return cur
    return None


def parse_traffic_metrics(payload: dict) -> dict:
    """Extract scalar attractiveness metrics from traffic / item mget payloads."""
    if not isinstance(payload, dict):
        payload = {}

    # creator item/mget: { items: [ { metrics: {...} } ] }
    items = payload.get("items")
    if isinstance(items, list) and items and isinstance(items[0], dict):
        metrics = items[0].get("metrics")
        if isinstance(metrics, dict):
            payload = metrics

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if isinstance(data.get("metrics"), dict):
        data = data["metrics"]

    completion = _dig(
        data,
        ("finish_rate",),
        ("completion_rate",),
        ("play_finish_rate",),
        ("metrics", "finish_rate"),
        ("metrics", "completion_rate"),
    )
    avg_dur = _dig(
        data,
        ("avg_play_duration",),
        ("avg_view_second",),
        ("avg_duration",),
        ("average_play_time",),
        ("metrics", "avg_play_duration"),
        ("metrics", "avg_view_second"),
    )
    bounce_2s = _dig(
        data,
        ("bounce_rate_2s",),
        ("two_second_bounce_rate",),
        ("bounce_rate",),
        ("metrics", "bounce_rate_2s"),
    )
    finish_5s = _dig(
        data,
        ("finish_rate_5s",),
        ("five_second_finish_rate",),
        ("completion_rate_5s",),
        ("metrics", "finish_rate_5s"),
        ("metrics", "completion_rate_5s"),
    )
    avg_pct = _dig(
        data,
        ("avg_play_progress",),
        ("avg_view_proportion",),
        ("avg_play_percent",),
        ("average_play_ratio",),
        ("metrics", "avg_play_progress"),
        ("metrics", "avg_view_proportion"),
    )
    dur: float | None
    try:
        dur = float(avg_dur) if avg_dur is not None and avg_dur != "" else None
        if dur is not None:
            dur = round(dur, 2)
    except (TypeError, ValueError):
        dur = None
    return {
        "completion_rate": normalize_percent(completion),
        "avg_play_duration_sec": dur,
        "bounce_rate_2s": normalize_percent(bounce_2s),
        "completion_rate_5s": normalize_percent(finish_5s),
        "avg_play_percent": normalize_percent(avg_pct),
    }


def parse_mget_items_metrics(payload: dict) -> dict[str, dict]:
    """Map item_id -> traffic scalars from /web/api/creator/item/mget body."""
    out: dict[str, dict] = {}
    if not isinstance(payload, dict):
        return out
    items = payload.get("items")
    if not isinstance(items, list):
        return out
    for row in items:
        if not isinstance(row, dict):
            continue
        item_id = row.get("id") or row.get("item_id") or row.get("aweme_id")
        if item_id is None or str(item_id).strip() == "":
            continue
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else row
        parsed = parse_traffic_metrics(metrics if isinstance(metrics, dict) else {})
        parsed["traffic_sources"] = parse_traffic_sources(row) or []
        out[str(item_id)] = parsed
    return out



# Confirmed 2026-08-17: /janus/.../item/play/source → play_source[{key,value}]
DOUYIN_PLAY_SOURCE_LABELS = {
    "homepage_hot": "推荐页",
    "familiar": "朋友",
    "search": "搜索",
    "homepage": "个人主页",
    "message": "消息",
    "other": "其他",
    "homepage_follow": "关注页",
    "follow": "关注页",
    "homepage_fresh": "同城",
    "nearby": "同城",
    "samecity": "同城",
}


def parse_traffic_sources(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    raw_list = (
        data.get("play_source")
        or data.get("traffic_source")
        or data.get("traffic_sources")
        or data.get("source_list")
        or data.get("sources")
        or []
    )
    if isinstance(raw_list, dict):
        items = [{"name": k, "ratio": v} for k, v in raw_list.items()]
    elif isinstance(raw_list, list):
        items = [x for x in raw_list if isinstance(x, dict)]
    else:
        items = []
    out: list[dict] = []
    for row in items:
        key = row.get("key")
        label_from_key = (
            DOUYIN_PLAY_SOURCE_LABELS.get(str(key))
            or DOUYIN_PLAY_SOURCE_LABELS.get(str(key).lower() if key is not None else "")
        )
        name = str(
            row.get("name")
            or row.get("source_name")
            or row.get("title")
            or label_from_key
            or key
            or ""
        ).strip()
        ratio = normalize_percent(row.get("ratio", row.get("percent", row.get("value"))))
        if not name or ratio is None:
            continue
        out.append({"name": name, "ratio": ratio})
    out.sort(key=lambda x: float(x.get("ratio") or 0), reverse=True)
    return out


def parse_distribution_list(raw: Any) -> list[dict]:
    if isinstance(raw, dict):
        raw = (
            raw.get("ratio_list")
            or raw.get("list")
            or raw.get("items")
            or raw.get("distribution")
            or []
        )
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        name = (
            row.get("name")
            or row.get("label")
            or row.get("key")
            or row.get("title")
        )
        if name is None or name == "":
            continue
        name_s = str(name)
        # portrait API uses male/female keys
        if name_s.lower() == "male":
            name_s = "男"
        elif name_s.lower() == "female":
            name_s = "女"
        ratio = normalize_percent(
            row.get("ratio", row.get("percent", row.get("value", row.get("proportion"))))
        )
        if ratio is None:
            continue
        out.append({"name": name_s, "ratio": ratio})
    return out


def truncate_distribution_top_n(items: list[dict], n: int = 10) -> list[dict]:
    n = max(0, int(n))
    ordered = sorted(items, key=lambda x: float(x.get("ratio") or 0), reverse=True)
    return ordered[:n]


def parse_audience_payload(payload: dict) -> dict:
    """Map creator audience/traffic JSON into distribution blocks.

    Confirmed portrait API:
      GET /janus/douyin/creator/data/fans/item/portrait?item_id=...
      body.gender/age/province.ratio_list = [{key, value}, ...]
    """
    if not isinstance(payload, dict):
        payload = {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    gender_raw = _dig(
        data,
        ("gender",),
        ("gender_distribution",),
        ("audience_gender",),
        ("sex",),
        ("metrics", "gender"),
    )
    age_raw = _dig(
        data,
        ("age",),
        ("age_distribution",),
        ("audience_age",),
        ("metrics", "age"),
    )
    region_raw = _dig(
        data,
        ("province",),
        ("region",),
        ("city",),
        ("audience_region",),
        ("geo",),
        ("metrics", "province"),
    )
    sources_raw = _dig(
        data,
        ("play_source",),
        ("traffic_source",),
        ("traffic_sources",),
        ("source",),
        ("flow_source",),
    )

    return {
        "audience_gender": parse_distribution_list(gender_raw),
        "audience_age": parse_distribution_list(age_raw),
        "audience_region": truncate_distribution_top_n(parse_distribution_list(region_raw), 10),
        "traffic_sources": parse_traffic_sources(
            {"play_source": sources_raw} if isinstance(sources_raw, list) else data
        )
        or parse_distribution_list(sources_raw),
    }


def merge_traffic_into_item(item: dict, traffic: dict | None) -> dict:
    merged = dict(item)
    traffic = traffic or {}
    for key in (
        "completion_rate",
        "avg_play_duration_sec",
        "bounce_rate_2s",
        "completion_rate_5s",
        "avg_play_percent",
    ):
        if key in traffic:
            merged[key] = traffic[key]
        else:
            merged.setdefault(key, None)
    if "traffic_sources" in traffic:
        merged["traffic_sources"] = traffic["traffic_sources"]
    else:
        merged.setdefault("traffic_sources", None)
    for key in ("audience_gender", "audience_age", "audience_region"):
        if key in traffic:
            merged[key] = traffic[key]
        else:
            merged.setdefault(key, None)
    return merged


def _item_sort_ts(raw: dict) -> int:
    ts = raw.get("create_time") or raw.get("createTime") or raw.get("publish_time") or raw.get("public_time") or 0
    try:
        ts_i = int(ts)
        if ts_i > 10_000_000_000:  # ms
            ts_i //= 1000
        return ts_i
    except (TypeError, ValueError):
        return 0


def parse_douyin_list_payload(payload: dict, limit: int = 5) -> list[dict]:
    """Parse list JSON and return the most recent `limit` items by create_time.

    Creator `work_list` often puts pinned (`is_pinned`) works first; we therefore
    collect candidates, sort by create_time descending, then truncate.
    """
    limit = max(0, int(limit))
    raw_items = [raw for raw in _extract_list(payload) if isinstance(raw, dict)]
    raw_items.sort(key=_item_sort_ts, reverse=True)
    items: list[dict] = []
    for raw in raw_items:
        parsed = parse_douyin_item(raw)
        if parsed:
            items.append(parsed)
        if len(items) >= limit:
            break
    return items


def replace_account_stats(conn, *, platform: str, account_id: int, items: list[dict], synced_at: str) -> None:
    ensure_content_stats_table(conn)
    conn.execute(
        "DELETE FROM content_stats WHERE platform = ? AND account_id = ?",
        (platform, account_id),
    )
    for item in items:
        sources = item.get("traffic_sources")
        if sources is None:
            sources_json = None
        else:
            sources_json = json.dumps(sources, ensure_ascii=False)

        if platform == "douyin":
            extra = build_douyin_extra(item)
            completion = avg_dur = bounce = finish5 = avg_pct = None
            sources_json = None
            extra_json = dumps_extra_json(extra)
        else:
            completion = item.get("completion_rate")
            avg_dur = item.get("avg_play_duration_sec")
            bounce = item.get("bounce_rate_2s")
            finish5 = item.get("completion_rate_5s")
            avg_pct = item.get("avg_play_percent")
            extra = {}
            if item.get("content_diagnose"):
                extra["content_diagnose"] = item["content_diagnose"]
            if item.get("metric_trends"):
                extra["metric_trends"] = item["metric_trends"]
            extra_json = dumps_extra_json(extra)

        conn.execute(
            """
            INSERT INTO content_stats (
                platform, account_id, item_id, title, cover_url, status, published_at,
                play_count, like_count, comment_count, share_count, collect_count,
                completion_rate, avg_play_duration_sec, bounce_rate_2s, completion_rate_5s,
                avg_play_percent, traffic_sources_json, extra_json,
                boost_play_count, boost_reason,
                synced_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                platform,
                account_id,
                item["item_id"],
                item.get("title") or "",
                item.get("cover_url") or "",
                item.get("status") or "",
                item.get("published_at") or "",
                normalize_count(item.get("play_count")),
                normalize_count(item.get("like_count")),
                normalize_count(item.get("comment_count")),
                normalize_count(item.get("share_count")),
                normalize_count(item.get("collect_count")),
                completion,
                avg_dur,
                bounce,
                finish5,
                avg_pct,
                sources_json,
                extra_json,
                item.get("boost_play_count"),
                item.get("boost_reason"),
                synced_at,
                item.get("raw_json") or "",
            ),
        )
    conn.commit()


MANAGE_URL = "https://creator.douyin.com/creator-micro/content/manage"

# Clicking 完播率 / 2秒跳出率 on manage opens this detail page.
TRAFFIC_PAGE_URL = (
    "https://creator.douyin.com/creator-micro/work-management/work-detail/{item_id}"
    "?enter_from=content&tabKey=overview&metricKey=completion_rate"
)

AUDIENCE_PAGE_URL = (
    "https://creator.douyin.com/creator-micro/work-management/work-detail/{item_id}"
    "?enter_from=content&tabKey=overview&metricKey=completion_rate"
)

# Confirmed 2026-08-17: clicking 观众分析 loads this portrait API.
AUDIENCE_PORTRAIT_API = (
    "https://creator.douyin.com/janus/douyin/creator/data/fans/item/portrait"
    "?item_id={item_id}"
)

# Confirmed 2026-08-17: 流量来源 chart loads this play/source API.
PLAY_SOURCE_API = (
    "https://creator.douyin.com/janus/douyin/creator/data/item/play/source"
    "?item_id={item_id}"
)

# Confirmed: detail page loads metrics via item/mget?fields=metrics,review,play_info
ITEM_MGET_API = (
    "https://creator.douyin.com/web/api/creator/item/mget"
    "?ids={ids}&fields=metrics,review,play_info"
)

DOUYIN_TRAFFIC_URL_HINTS = (
    "creator/item/mget",
    "item/mget",
    "item/analysis",
    "item_analysis",
    "item_compare",
    "diagnose",
    "traffic",
    "finish_rate",
    "play_analysis",
    "item/play/source",
    "play/source",
    "play_source",
    "data/item",
    "content/analysis",
    "work-detail",
)

DOUYIN_AUDIENCE_URL_HINTS = (
    "fans/item/portrait",
    "fans/item/others",
    "audience",
    "portrait",
    "gender",
    "province",
    "traffic_source",
    "fans_analysis",
    "flow_source",
    "user_portrait",
    "crowd",
)


def traffic_page_url(item_id: str) -> str:
    return TRAFFIC_PAGE_URL.format(item_id=item_id)


def is_douyin_list_api_url(url: str) -> bool:
    u = (url or "").lower()
    return any(hint in u for hint in DOUYIN_LIST_URL_HINTS)


def is_douyin_traffic_api_url(url: str) -> bool:
    u = (url or "").lower()
    if is_douyin_list_api_url(u):
        return False
    return any(hint in u for hint in DOUYIN_TRAFFIC_URL_HINTS)


def is_douyin_audience_api_url(url: str) -> bool:
    u = (url or "").lower()
    if is_douyin_list_api_url(u):
        return False
    return any(hint in u for hint in DOUYIN_AUDIENCE_URL_HINTS)


def merge_audience_into_item(item: dict, audience: dict | None) -> dict:
    merged = dict(item)
    if not audience:
        for key in ("audience_gender", "audience_age", "audience_region"):
            merged.setdefault(key, None)
        return merged
    for key in ("audience_gender", "audience_age", "audience_region"):
        if key in audience:
            merged[key] = audience[key]
    # Do not wipe traffic_sources filled by play/source with empty audience result.
    if audience.get("traffic_sources"):
        merged["traffic_sources"] = audience["traffic_sources"]
    return merged


async def fetch_audience_for_item(page, item_id: str) -> dict:
    """Open work-detail, click 观众分析 / intercept portrait, also active-fetch portrait API."""
    captured: list[dict] = []

    async def on_response(resp):
        try:
            url = resp.url
            if not (
                is_douyin_audience_api_url(url)
                or ("source" in url.lower() and "traffic" in url.lower())
                or is_douyin_traffic_api_url(url)
            ):
                return
            if resp.status != 200:
                return
            body = await resp.json()
            if isinstance(body, dict):
                captured.append(body)
        except Exception:
            return

    empty = {
        "audience_gender": [],
        "audience_age": [],
        "audience_region": [],
        "traffic_sources": [],
    }
    page.on("response", on_response)
    try:
        url = AUDIENCE_PAGE_URL.format(item_id=item_id)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        for label in ("观众分析", "流量来源", "流量分析"):
            loc = page.get_by_text(label, exact=False)
            try:
                if await loc.count():
                    await loc.first.click(timeout=2000)
                    await page.wait_for_timeout(1500)
            except Exception:
                pass
        await page.wait_for_timeout(1500)

        # Active fetch confirmed portrait API (more reliable than intercept alone).
        try:
            api_url = AUDIENCE_PORTRAIT_API.format(item_id=item_id)
            fetched = await page.evaluate(
                """async (url) => {
                    const resp = await fetch(url, {
                        credentials: 'include',
                        headers: { 'Agw-Js-Conv': 'str' },
                    });
                    if (!resp.ok) return { __http_status: resp.status };
                    return await resp.json();
                }""",
                api_url,
            )
            if isinstance(fetched, dict) and not fetched.get("__http_status"):
                captured.append(fetched)
        except Exception as exc:
            douyin_logger.warning("audience portrait fetch failed for %s: %s", item_id, exc)
    except Exception as exc:
        douyin_logger.warning("audience page failed for %s: %s", item_id, exc)
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
        return empty

    try:
        page.remove_listener("response", on_response)
    except Exception:
        pass

    merged = dict(empty)
    for body in captured:
        parsed = parse_audience_payload(body)
        for key, val in parsed.items():
            if val:
                merged[key] = val
        sources = parse_traffic_sources(body)
        if sources:
            merged["traffic_sources"] = sources
    return merged


def merge_intercepted_payloads(payloads: list[dict]) -> dict:
    best: dict = {}
    best_len = -1
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        length = len(_extract_list(payload))
        if length > best_len:
            best = payload
            best_len = length
    return best


class DouyinStatsSyncError(Exception):
    def __init__(self, message: str, code: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message


async def _fetch_metrics_via_mget(page, item_ids: list[str]) -> dict[str, dict]:
    """Fetch metrics for item ids via creator item/mget (same session cookie)."""
    ids = [str(i).strip() for i in item_ids if str(i).strip()]
    if not ids:
        return {}
    api_url = ITEM_MGET_API.format(ids=",".join(ids))
    try:
        fetched = await page.evaluate(
            """async (url) => {
                const resp = await fetch(url, {
                    credentials: 'include',
                    headers: { 'Agw-Js-Conv': 'str' },
                });
                if (!resp.ok) return { __http_status: resp.status };
                return await resp.json();
            }""",
            api_url,
        )
    except Exception as exc:
        douyin_logger.warning("item/mget fetch failed: %s", exc)
        return {}
    if not isinstance(fetched, dict) or fetched.get("__http_status"):
        douyin_logger.warning("item/mget bad response: %s", fetched)
        return {}
    return parse_mget_items_metrics(fetched)


async def fetch_play_sources_for_item(page, item_id: str) -> list[dict]:
    """Active-fetch confirmed play/source API; return normalized traffic_sources list."""
    try:
        api_url = PLAY_SOURCE_API.format(item_id=item_id)
        fetched = await page.evaluate(
            """async (url) => {
                const resp = await fetch(url, {
                    credentials: 'include',
                    headers: { 'Agw-Js-Conv': 'str' },
                });
                if (!resp.ok) return { __http_status: resp.status };
                return await resp.json();
            }""",
            api_url,
        )
    except Exception as exc:
        douyin_logger.warning("play/source fetch failed for %s: %s", item_id, exc)
        return []
    if not isinstance(fetched, dict) or fetched.get("__http_status"):
        douyin_logger.warning("play/source bad response for %s: %s", item_id, fetched)
        return []
    return parse_traffic_sources(fetched)


async def _fetch_traffic_for_item(page, item_id: str) -> dict:
    """Prefer mget; fallback: open work-detail (完播率入口) and parse intercepted JSON."""
    by_id = await _fetch_metrics_via_mget(page, [item_id])
    if item_id in by_id:
        metrics = by_id[item_id]
        sources = await fetch_play_sources_for_item(page, item_id)
        if sources:
            metrics["traffic_sources"] = sources
        return metrics

    payloads: list[dict] = []

    async def on_response(response):
        try:
            if not is_douyin_traffic_api_url(response.url):
                return
            if response.status != 200:
                return
            data = await response.json()
            if isinstance(data, dict):
                payloads.append(data)
        except Exception as exc:
            douyin_logger.debug("traffic intercept parse failed: %s", exc)

    page.on("response", on_response)
    try:
        await page.goto(traffic_page_url(item_id), wait_until="domcontentloaded", timeout=60000)
        for label in ("流量分析", "总览", "流量来源"):
            tab = page.get_by_text(label, exact=False)
            if await tab.count():
                try:
                    await tab.first.click(timeout=3000)
                    await page.wait_for_timeout(1500)
                except Exception:
                    pass
        for _ in range(20):
            if payloads:
                break
            await page.wait_for_timeout(500)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

    metrics: dict = {
        "completion_rate": None,
        "avg_play_duration_sec": None,
        "bounce_rate_2s": None,
        "completion_rate_5s": None,
        "avg_play_percent": None,
        "traffic_sources": None,
    }
    if not payloads:
        sources = await fetch_play_sources_for_item(page, item_id)
        if sources:
            metrics["traffic_sources"] = sources
        return metrics

    sources: list[dict] | None = None
    for payload in payloads:
        mapped = parse_mget_items_metrics(payload)
        if item_id in mapped:
            metrics = mapped[item_id]
            break
        parsed = parse_traffic_metrics(payload)
        for k, v in parsed.items():
            if metrics.get(k) is None and v is not None:
                metrics[k] = v
        parsed_sources = parse_traffic_sources(payload)
        if parsed_sources and sources is None:
            sources = parsed_sources
    if not sources:
        sources = await fetch_play_sources_for_item(page, item_id) or None
    metrics["traffic_sources"] = sources if sources is not None else []
    return metrics


async def sync_recent_items(account_file: str | Path, limit: int = 5, headless: bool | None = None) -> list[dict]:
    account_file = Path(account_file)
    if not account_file.exists():
        raise DouyinStatsSyncError("cookie 文件不存在，请先在账号管理中登录抖音", code=401)

    headless = LOCAL_CHROME_HEADLESS if headless is None else headless
    payloads: list[dict] = []

    async with async_playwright() as playwright:
        launch_args = {"headless": headless}
        if LOCAL_CHROME_PATH:
            launch_args["executable_path"] = LOCAL_CHROME_PATH
        else:
            launch_args["channel"] = "chrome"
        browser = await playwright.chromium.launch(**launch_args)
        try:
            context = await browser.new_context(storage_state=str(account_file))
            context = await set_init_script(context)
            page = await context.new_page()

            async def on_response(response):
                try:
                    url = response.url
                    if not is_douyin_list_api_url(url):
                        return
                    if response.status != 200:
                        return
                    data = await response.json()
                    if isinstance(data, dict):
                        payloads.append(data)
                except Exception as exc:
                    douyin_logger.debug("intercept response parse failed: %s", exc)
                    return

            page.on("response", on_response)
            await page.goto(MANAGE_URL, wait_until="domcontentloaded", timeout=60000)
            for _ in range(30):
                if await page.get_by_text("手机号登录").count() or await page.get_by_text("扫码登录").count():
                    raise DouyinStatsSyncError("抖音 cookie 已失效，请重新登录", code=401)
                if payloads:
                    break
                await page.wait_for_timeout(500)
            else:
                await page.reload(wait_until="domcontentloaded", timeout=60000)
                for _ in range(20):
                    if payloads:
                        break
                    await page.wait_for_timeout(500)

            if not payloads:
                # Fallback: directly call current creator work_list API in-page
                # (page may not auto-trigger the XHR we expected).
                try:
                    api_url = WORK_LIST_API.format(page_size=max(limit * 5, 20))
                    fetched = await page.evaluate(
                        """async (url) => {
                            const resp = await fetch(url, { credentials: 'include' });
                            if (!resp.ok) return { __http_status: resp.status };
                            return await resp.json();
                        }""",
                        api_url,
                    )
                    if isinstance(fetched, dict) and not fetched.get("__http_status"):
                        payloads.append(fetched)
                        douyin_logger.info("已通过主动请求 work_list 获取作品列表")
                    else:
                        douyin_logger.warning(f"主动请求 work_list 失败: {fetched}")
                except Exception as exc:
                    douyin_logger.warning(f"主动请求 work_list 异常: {exc}")

            if not payloads:
                raise DouyinStatsSyncError("未拦截到作品列表接口，页面结构可能已变化", code=500)

            await page.wait_for_timeout(500)

            merged = merge_intercepted_payloads(payloads)
            if not _extract_list(merged):
                raise DouyinStatsSyncError("未解析到作品列表，接口字段可能已变化", code=500)
            items = parse_douyin_list_payload(merged, limit=limit)
            metrics_by_id = await _fetch_metrics_via_mget(
                page, [it["item_id"] for it in items]
            )
            enriched = []
            for idx, item in enumerate(items):
                try:
                    traffic = metrics_by_id.get(item["item_id"])
                    if traffic is None:
                        traffic = await _fetch_traffic_for_item(page, item["item_id"])
                    else:
                        # mget has scalars only; fill traffic_sources via play/source
                        sources = await fetch_play_sources_for_item(page, item["item_id"])
                        if sources:
                            traffic = dict(traffic)
                            traffic["traffic_sources"] = sources
                    item = merge_traffic_into_item(item, traffic)
                except Exception as exc:
                    douyin_logger.warning(
                        "traffic fetch failed for %s: %s", item.get("item_id"), exc
                    )
                    item = merge_traffic_into_item(item, None)
                try:
                    audience = await fetch_audience_for_item(page, item["item_id"])
                    item = merge_audience_into_item(item, audience)
                except Exception as exc:
                    douyin_logger.warning(
                        "audience fetch failed for %s: %s", item.get("item_id"), exc
                    )
                    item = merge_audience_into_item(item, None)
                enriched.append(item)
                if idx + 1 < len(items):
                    await page.wait_for_timeout(800)
            douyin_logger.info(
                f"抖音作品同步完成: {len(enriched)} 条 (limit={limit}, with traffic+audience)"
            )
            return enriched
        finally:
            await browser.close()


def sync_recent_items_sync(account_file: str | Path, limit: int = 5, headless: bool | None = None) -> list[dict]:
    return asyncio.run(sync_recent_items(account_file, limit=limit, headless=headless))

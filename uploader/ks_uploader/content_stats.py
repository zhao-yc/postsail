# uploader/ks_uploader/content_stats.py
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from patchright.async_api import async_playwright

from conf import LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
from utils.base_social_media import set_init_script
from utils.log import kuaishou_logger

# Published works tab (status=1). status=2 is 待发布 and often empty.
MANAGE_URL = "https://cp.kuaishou.com/article/manage/video?status=1"

# Locked from headed probe (2026-08-17): 查看数据 -> 作品数据详情
TRAFFIC_PAGE_URL = "https://cp.kuaishou.com/statistics/article/detail/{item_id}"

KUAISHOU_LIST_URL_HINTS = (
    "rest/cp/works/v2/video/pc/photo/list",
    "video/pc/photo/list",
    "pc/photo/list",
)

KUAISHOU_TRAFFIC_URL_HINTS = (
    "photo/single/overview",
    "photo/single/traffic/source",
    "photo/single/info",
    "photo/single/diagnose",
    "analysis/pc/photo/single",
)


def traffic_page_url(item_id: str) -> str:
    return TRAFFIC_PAGE_URL.format(item_id=item_id)


def is_kuaishou_list_api_url(url: str) -> bool:
    u = (url or "").lower()
    return any(hint in u for hint in KUAISHOU_LIST_URL_HINTS)


def is_kuaishou_traffic_api_url(url: str) -> bool:
    u = (url or "").lower()
    if is_kuaishou_list_api_url(u):
        return False
    return any(hint in u for hint in KUAISHOU_TRAFFIC_URL_HINTS)


def is_kuaishou_login_url(url: str) -> bool:
    """True when browser landed on Kuaishou passport / login hosts."""
    u = (url or "").lower()
    if not u:
        return False
    if "passport.kuaishou.com" in u:
        return True
    if "id.kuaishou.com" in u and "login" in u:
        return True
    if "/account/login" in u or "/pc/account/login" in u:
        return True
    return False


def is_navigation_context_error(exc: BaseException) -> bool:
    """Playwright destroys JS context mid-navigation; Locator.count then raises."""
    msg = str(exc).lower()
    return (
        "execution context was destroyed" in msg
        or "most likely because of a navigation" in msg
        or "target closed" in msg
        or "frame was detached" in msg
    )


async def _safe_locator_count(locator) -> int:
    """count() that returns 0 while the page is navigating/reloading."""
    try:
        return await locator.count()
    except Exception as exc:
        if is_navigation_context_error(exc):
            return 0
        raise


class KuaishouStatsSyncError(Exception):
    def __init__(self, message: str, code: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_count(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


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
    """Extract scalar attractiveness metrics from Kuaishou traffic payloads."""
    if not isinstance(payload, dict):
        payload = {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if isinstance(data.get("metrics"), dict):
        data = data["metrics"]
    if isinstance(data.get("photoData"), dict):
        data = data["photoData"]

    # Confirmed probe shape: photo/single/overview -> data.trendList[{enName,sumCount}]
    trend_list = data.get("trendList")
    if isinstance(trend_list, list) and trend_list:
        by_en: dict[str, Any] = {}
        for row in trend_list:
            if not isinstance(row, dict):
                continue
            en = str(row.get("enName") or "").strip().upper()
            if en:
                by_en[en] = row.get("sumCount")
        completion = by_en.get("FPR")
        avg_dur = by_en.get("AVG_PLAY_DURATION")
        bounce_2s = by_en.get("TWO_SECONDS_EXIT")
        finish_5s = by_en.get("FIVE_SECONDS_FPR")
        avg_pct = None
    else:
        completion = _dig(
            data,
            ("playFinishRate",),
            ("finishRate",),
            ("finish_rate",),
            ("completionRate",),
            ("completion_rate",),
            ("play_finish_rate",),
            ("fpr",),
        )
        avg_dur = _dig(
            data,
            ("avgPlayDuration",),
            ("avgPlayDurationSec",),
            ("avg_play_duration",),
            ("avgViewDuration",),
            ("averagePlayTime",),
        )
        bounce_2s = _dig(
            data,
            ("twoSecondBounceRate",),
            ("bounceRate2s",),
            ("bounce_rate_2s",),
            ("two_second_bounce_rate",),
            ("bounceRate",),
        )
        finish_5s = _dig(
            data,
            ("fiveSecondFinishRate",),
            ("completionRate5s",),
            ("finish_rate_5s",),
            ("completion_rate_5s",),
        )
        avg_pct = _dig(
            data,
            ("avgPlayProgress",),
            ("avgPlayPercent",),
            ("avg_play_progress",),
            ("avg_play_percent",),
            ("averagePlayRatio",),
        )

    dur: float | None
    try:
        dur = float(avg_dur) if avg_dur is not None and avg_dur != "" else None
        if dur is not None:
            # overview AVG_PLAY_DURATION is milliseconds (e.g. 5834.299 -> 5.83s)
            if dur >= 1000:
                dur = dur / 1000.0
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


def parse_traffic_sources(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    # Confirmed: photo/single/traffic/source -> data.trafficDataList[tab=PLAY].trendData
    traffic_data_list = data.get("trafficDataList")
    if isinstance(traffic_data_list, list):
        play_tab = None
        for tab in traffic_data_list:
            if not isinstance(tab, dict):
                continue
            if str(tab.get("tab") or "").upper() == "PLAY" or tab.get("name") == "播放量":
                play_tab = tab
                break
        if play_tab is None and traffic_data_list and isinstance(traffic_data_list[0], dict):
            play_tab = traffic_data_list[0]
        if isinstance(play_tab, dict):
            rows = play_tab.get("trendData") or []
            if isinstance(rows, list) and rows:
                total = 0.0
                parsed_rows: list[tuple[str, float]] = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    name = str(row.get("name") or "").strip()
                    try:
                        count = float(row.get("count", 0) or 0)
                    except (TypeError, ValueError):
                        count = 0.0
                    if not name:
                        continue
                    parsed_rows.append((name, count))
                    total += count
                if not total:
                    try:
                        total = float(play_tab.get("sumCount") or 0)
                    except (TypeError, ValueError):
                        total = 0.0
                out: list[dict] = []
                if total > 0:
                    for name, count in parsed_rows:
                        if count <= 0:
                            continue
                        out.append({"name": name, "ratio": round(count * 100.0 / total, 2)})
                return out

    raw_list = (
        data.get("trafficSources")
        or data.get("traffic_sources")
        or data.get("trafficSource")
        or data.get("traffic_source")
        or data.get("sourceList")
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
    out = []
    for row in items:
        name = str(
            row.get("name") or row.get("sourceName") or row.get("source_name") or row.get("title") or ""
        ).strip()
        ratio = normalize_percent(row.get("ratio", row.get("percent", row.get("value"))))
        if not name or ratio is None:
            continue
        out.append({"name": name, "ratio": ratio})
    return out


def parse_boost_info(payload: dict) -> dict:
    """Extract 流量助推 count + reason from photo/single/info (or list-like) payloads."""
    out = {"boost_play_count": None, "boost_reason": None}
    if not isinstance(payload, dict):
        return out
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    boost_v3 = data.get("officialBoostV3")
    if isinstance(boost_v3, dict):
        split = boost_v3.get("splitViewMap")
        if isinstance(split, dict):
            candidates = [v for v in split.values() if isinstance(v, dict)]
            candidates.sort(key=lambda x: int(x.get("order") or 0))
            for row in candidates:
                promo = row.get("promotion")
                if promo is None or promo == "":
                    continue
                try:
                    count = int(float(promo))
                except (TypeError, ValueError):
                    continue
                if count <= 0:
                    continue
                reason = str(row.get("reason") or "").strip() or None
                return {"boost_play_count": count, "boost_reason": reason}

    # List card fallback: "184助推播放量"
    desc = data.get("promotionDesc") or payload.get("promotionDesc")
    if isinstance(desc, str) and desc.strip():
        m = re.search(r"(\d+)\s*助推", desc)
        if m:
            out["boost_play_count"] = int(m.group(1))
    return out


def parse_content_diagnose(payload: dict) -> list[dict]:
    """Extract 内容诊断 scores from photo/single/diagnose."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    detail = data.get("detail") if isinstance(data.get("detail"), dict) else {}
    content = detail.get("content") if isinstance(detail.get("content"), dict) else {}
    raw_list = content.get("diagnoseList") or []
    if not isinstance(raw_list, list):
        return []
    out: list[dict] = []
    for row in raw_list:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        try:
            score = None if row.get("score") is None or row.get("score") == "" else round(float(row.get("score")), 1)
        except (TypeError, ValueError):
            score = None
        if not title or score is None:
            continue
        desc = str(row.get("diagnoseDesc") or "").strip() or None
        out.append(
            {
                "dimension": str(row.get("contentDimension") or "").strip(),
                "title": title,
                "score": score,
                "desc": desc,
            }
        )
    return out


def _format_trend_ts(raw_ts: Any) -> str | None:
    try:
        ts = int(raw_ts)
    except (TypeError, ValueError):
        return None
    if ts > 10_000_000_000:
        ts //= 1000
    if ts <= 0:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:00")
    except (TypeError, ValueError, OSError):
        return None


def parse_metric_trends(payload: dict) -> list[dict]:
    """Extract hourly metric series from photo/single/overview trendList."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    trend_list = data.get("trendList")
    if not isinstance(trend_list, list):
        return []
    out: list[dict] = []
    for row in trend_list:
        if not isinstance(row, dict):
            continue
        key = str(row.get("enName") or "").strip().upper()
        name = str(row.get("name") or key).strip()
        raw_points = row.get("trendData")
        if not key or not isinstance(raw_points, list):
            continue
        points: list[dict] = []
        for item in raw_points:
            if not isinstance(item, dict):
                continue
            date = _format_trend_ts(item.get("date"))
            try:
                value = float(item.get("count"))
            except (TypeError, ValueError):
                continue
            if date is None:
                continue
            if key == "AVG_PLAY_DURATION" and value >= 1000:
                value = value / 1000.0
            points.append({"date": date, "value": round(value, 2)})
        while points and points[0]["value"] == 0:
            points.pop(0)
        if not points:
            continue
        out.append({"key": key, "name": name, "points": points})
    return out


def merge_traffic_into_item(item: dict, traffic: dict | None) -> dict:
    merged = dict(item)
    traffic = traffic or {}
    for key in (
        "completion_rate",
        "avg_play_duration_sec",
        "bounce_rate_2s",
        "completion_rate_5s",
        "avg_play_percent",
        "boost_play_count",
        "boost_reason",
        "content_diagnose",
        "metric_trends",
    ):
        if key in traffic:
            merged[key] = traffic[key]
        else:
            merged.setdefault(key, None)
    if "traffic_sources" in traffic:
        merged["traffic_sources"] = traffic["traffic_sources"]
    else:
        merged.setdefault("traffic_sources", None)
    return merged


def _extract_list(payload: dict) -> list:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("list", "photoList", "works", "videoList"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return _extract_list(data)
    for key in ("list", "photoList", "works", "videoList"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


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


def _item_sort_ts(raw: dict) -> int:
    ts = raw.get("uploadTime") or raw.get("publishTime") or raw.get("createTime") or raw.get("create_time") or 0
    try:
        ts_i = int(ts)
        if ts_i > 10_000_000_000:  # ms
            ts_i //= 1000
        return ts_i
    except (TypeError, ValueError):
        return 0


def _published_at(raw: dict) -> str:
    ts = _item_sort_ts(raw)
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return str(raw.get("uploadTime") or "")


def _tag_texts(raw: dict) -> list[str]:
    """Extract human-readable texts from photoStatusTags / judgement fields."""
    texts: list[str] = []
    for key in ("photoStatusTags", "judgementTitle", "statusTags"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            texts.append(value.strip())
            continue
        if isinstance(value, dict):
            t = value.get("text") or value.get("title") or value.get("name")
            if t:
                texts.append(str(t).strip())
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    texts.append(item.strip())
                elif isinstance(item, dict):
                    t = item.get("text") or item.get("title") or item.get("name")
                    if t:
                        texts.append(str(t).strip())
    # dedupe keep order
    seen = set()
    out = []
    for t in texts:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _status_text(raw: dict) -> str:
    """Publish status + optional platform badges (e.g. 流量助推), never dump raw dicts."""
    status = raw.get("publishStatus")
    mapping = {
        0: "全部",
        1: "已发布",
        2: "待发布",
        3: "已下线",
    }
    base = mapping.get(status)
    if not base:
        # photoStatus / judgementStatus fallbacks
        if raw.get("photoTop"):
            base = "已发布(置顶)"
        else:
            base = "已发布"

    tags = _tag_texts(raw)
    # Avoid repeating the same words already in base
    extras = [t for t in tags if t != base and t not in base]
    if extras:
        return f"{base} · {' · '.join(extras[:2])}"
    return base


def parse_kuaishou_item(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    item_id = raw.get("workId") or raw.get("photoId") or raw.get("publishId") or raw.get("id")
    if item_id is None or str(item_id).strip() in ("", "0"):
        return None
    cover = raw.get("publishCoverUrl") or raw.get("coverUrl") or raw.get("cover") or ""
    return {
        "item_id": str(item_id),
        "title": str(raw.get("title") or raw.get("caption") or "").strip(),
        "cover_url": str(cover or ""),
        "status": _status_text(raw),
        "published_at": _published_at(raw),
        "play_count": normalize_count(raw.get("playCount", raw.get("viewCount", 0))),
        "like_count": normalize_count(raw.get("likeCount", raw.get("diggCount", 0))),
        "comment_count": normalize_count(raw.get("commentCount", 0)),
        "share_count": normalize_count(raw.get("shareCount", raw.get("forwardCount", 0))),
        "collect_count": normalize_count(raw.get("collectCount", raw.get("collect_count", 0))),
        "completion_rate": None,
        "avg_play_duration_sec": None,
        "bounce_rate_2s": None,
        "completion_rate_5s": None,
        "avg_play_percent": None,
        "traffic_sources": None,
        "boost_play_count": None,
        "boost_reason": None,
        "content_diagnose": None,
        "metric_trends": None,
        "raw_json": json.dumps(raw, ensure_ascii=False)[:8000],
    }


def parse_kuaishou_list_payload(payload: dict, limit: int = 5) -> list[dict]:
    """Return most recent `limit` works by uploadTime (pinned items may lead API order)."""
    limit = max(0, int(limit))
    raw_items = [raw for raw in _extract_list(payload) if isinstance(raw, dict)]
    raw_items.sort(key=_item_sort_ts, reverse=True)
    items: list[dict] = []
    for raw in raw_items:
        parsed = parse_kuaishou_item(raw)
        if parsed:
            items.append(parsed)
        if len(items) >= limit:
            break
    return items


async def _fetch_traffic_for_item(page, item_id: str) -> dict:
    """Open 作品数据详情 and parse overview + traffic source intercepts."""
    payloads: list[dict] = []

    async def on_response(response):
        try:
            if not is_kuaishou_traffic_api_url(response.url):
                return
            if response.status != 200:
                return
            data = await response.json()
            if isinstance(data, dict):
                payloads.append(data)
        except Exception as exc:
            kuaishou_logger.debug("traffic intercept parse failed: %s", exc)

    page.on("response", on_response)
    try:
        await page.goto(traffic_page_url(item_id), wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        for label in ("流量来源", "核心数据", "观看分析"):
            tab = page.get_by_text(label, exact=False)
            if await _safe_locator_count(tab):
                try:
                    await tab.first.click(timeout=3000)
                    await page.wait_for_timeout(1200)
                except Exception:
                    pass
        for _ in range(24):
            if payloads:
                break
            await page.wait_for_timeout(500)
        await page.wait_for_timeout(800)
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
        "boost_play_count": None,
        "boost_reason": None,
        "content_diagnose": None,
        "metric_trends": None,
    }
    if not payloads:
        return metrics

    sources: list[dict] | None = None
    for payload in payloads:
        parsed = parse_traffic_metrics(payload)
        for k, v in parsed.items():
            if metrics.get(k) is None and v is not None:
                metrics[k] = v
        parsed_sources = parse_traffic_sources(payload)
        if parsed_sources and sources is None:
            sources = parsed_sources
        boost = parse_boost_info(payload)
        if metrics.get("boost_play_count") is None and boost.get("boost_play_count") is not None:
            metrics["boost_play_count"] = boost["boost_play_count"]
        if metrics.get("boost_reason") is None and boost.get("boost_reason"):
            metrics["boost_reason"] = boost["boost_reason"]
        diagnose = parse_content_diagnose(payload)
        if diagnose and not metrics.get("content_diagnose"):
            metrics["content_diagnose"] = diagnose
        trends = parse_metric_trends(payload)
        if trends and not metrics.get("metric_trends"):
            metrics["metric_trends"] = trends
    metrics["traffic_sources"] = sources if sources is not None else []
    return metrics


async def sync_recent_items(account_file: str | Path, limit: int = 5, headless: bool | None = None) -> list[dict]:
    account_file = Path(account_file)
    if not account_file.exists():
        raise KuaishouStatsSyncError("cookie 文件不存在，请先在账号管理中登录快手", code=401)

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
                    if not is_kuaishou_list_api_url(url):
                        return
                    if response.status != 200:
                        return
                    data = await response.json()
                    if isinstance(data, dict):
                        payloads.append(data)
                except Exception as exc:
                    kuaishou_logger.debug("intercept response parse failed: %s", exc)
                    return

            page.on("response", on_response)
            await page.goto(MANAGE_URL, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass

            for _ in range(40):
                # Prefer URL over DOM text: SPA redirects destroy locator execution context.
                if is_kuaishou_login_url(page.url):
                    raise KuaishouStatsSyncError("快手 cookie 已失效，请重新登录", code=401)
                scan_n = await _safe_locator_count(page.get_by_text("扫码登录"))
                phone_n = await _safe_locator_count(page.get_by_text("手机号登录"))
                if scan_n or phone_n:
                    raise KuaishouStatsSyncError("快手 cookie 已失效，请重新登录", code=401)
                if any(_extract_list(p) for p in payloads):
                    break
                await page.wait_for_timeout(500)
            else:
                await page.reload(wait_until="domcontentloaded", timeout=60000)
                for _ in range(20):
                    if is_kuaishou_login_url(page.url):
                        raise KuaishouStatsSyncError("快手 cookie 已失效，请重新登录", code=401)
                    if any(_extract_list(p) for p in payloads):
                        break
                    await page.wait_for_timeout(500)

            await page.wait_for_timeout(800)

            if not payloads:
                raise KuaishouStatsSyncError("未拦截到快手作品列表接口，页面结构可能已变化", code=500)

            merged = merge_intercepted_payloads(payloads)
            # Empty list with result=1 is valid (no works)
            if merged.get("result") not in (1, "1", None) and not _extract_list(merged):
                raise KuaishouStatsSyncError(
                    f"快手作品列表返回异常: {merged.get('message') or merged.get('result')}",
                    code=500,
                )

            items = parse_kuaishou_list_payload(merged, limit=limit)
            enriched: list[dict] = []
            for item in items:
                try:
                    traffic = await _fetch_traffic_for_item(page, item["item_id"])
                    enriched.append(merge_traffic_into_item(item, traffic))
                except Exception as exc:
                    kuaishou_logger.warning(
                        "traffic fetch failed for %s: %s", item.get("item_id"), exc
                    )
                    enriched.append(merge_traffic_into_item(item, None))
                await page.wait_for_timeout(400)

            kuaishou_logger.info(
                f"快手作品同步完成: {len(enriched)} 条 (limit={limit}, with traffic)"
            )
            return enriched
        finally:
            await browser.close()


def sync_recent_items_sync(account_file: str | Path, limit: int = 5, headless: bool | None = None) -> list[dict]:
    return asyncio.run(sync_recent_items(account_file, limit=limit, headless=headless))

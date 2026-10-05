"""后端排期使用明确时区，平台执行器始终接收立即发布快照。"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .model import ArticleError
from .platforms import PLATFORMS


def supports_server_schedule(platform):
    """所有可用的文章/图文执行器共用后端排期，真实账号验收状态独立保留。"""
    if not isinstance(platform, str):
        return False
    rules = PLATFORMS.get(platform)
    return rules is not None and rules.get("available") is not False


def normalize_schedule(value):
    """解析排期；重复请求即使已到期仍可读取原批次，未来检查由创建事务完成。"""
    if value is None:
        return None, ""
    if not isinstance(value, dict) or set(value) != {"publish_at", "timezone"}:
        raise ArticleError("schedule 必须包含 publish_at 和 timezone，立即发布请传 null 或省略")
    raw, zone_name = value["publish_at"], value["timezone"]
    if not isinstance(zone_name, str) or not zone_name or len(zone_name) > 100:
        raise ArticleError("请提供有效的 IANA 时区，例如 Asia/Shanghai")
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ArticleError("时区无效；请使用 Asia/Shanghai 等 IANA 时区并安装项目时区依赖") from exc
    if not isinstance(raw, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?", raw):
        raise ArticleError("发布时间须包含日期和时间，例如 2026-10-06T10:00:00")
    try:
        local = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if local.tzinfo is not None:
            # 显式偏移用于区分夏令时回拨的两次同名时间；必须符合所选时区。
            instant = local.astimezone(timezone.utc)
            converted = instant.astimezone(zone)
            if converted.replace(tzinfo=None) != local.replace(tzinfo=None) or converted.utcoffset() != local.utcoffset():
                raise ArticleError("发布时间的 UTC 偏移与所选时区不一致")
        else:
            instants = {candidate.astimezone(timezone.utc) for fold in (0, 1)
                        if (candidate := local.replace(tzinfo=zone, fold=fold)).astimezone(timezone.utc)
                        .astimezone(zone).replace(tzinfo=None) == local}
            if not instants:
                raise ArticleError("该本地时间因夏令时切换不存在，请选择其他时间")
            if len(instants) != 1:
                raise ArticleError("该本地时间因夏令时回拨出现两次，请在发布时间中明确 UTC 偏移")
            instant = instants.pop()
    except (ValueError, OverflowError) as exc:
        raise ArticleError("发布时间无效，请检查日期和时间") from exc
    return instant.isoformat(timespec="microseconds"), zone_name

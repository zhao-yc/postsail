# myUtils/dingtalk.py
"""DingTalk group robot helpers (webhook markdown push)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import time
import urllib.parse
from typing import Any, Mapping, Optional, Sequence

import requests

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore


class DingTalkPushError(Exception):
    """Raised when push cannot proceed or DingTalk rejects the message."""

    def __init__(self, message: str, *, code: int = 502):
        super().__init__(message)
        self.message = message
        self.code = code


_DIM_SHORT = {"SCREEN": "画质", "TITLE": "标题", "CONTENT": "内容", "AUDIO": "声音"}


def truncate_title(title: str, max_len: int = 40) -> str:
    text = (title or "").strip() or "（无标题）"
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


def _fmt_num(v: Any) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if n == int(n):
        return str(int(n))
    return str(n)


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "—"
    return f"{_fmt_num(v)}%"


def _md_escape_cell(text: Any) -> str:
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def _short_boost_reason(reason: Optional[str]) -> str:
    s = (reason or "").strip()
    if "「" in s and "」" in s:
        inner = s.split("「", 1)[1].split("」", 1)[0]
        inner = inner.replace("清晰度", "").replace("质量", "")
        if "超过" in s:
            tail = s[s.find("超过") :]
            return inner + tail.replace("超过", "超")
    return s or "—"


def _diagnose_text(items: Any) -> str:
    bits: list[str] = []
    for d in items or []:
        if not isinstance(d, dict) or d.get("score") is None:
            continue
        dim = str(d.get("dimension") or "").upper()
        name = _DIM_SHORT.get(dim) or str(d.get("title") or "").replace("评估", "")
        bits.append(f"{name}{_fmt_num(d.get('score'))}")
    return " / ".join(bits) if bits else ""


def _ratio_table(title: str, items: Any) -> list[str]:
    rows = [x for x in (items or []) if isinstance(x, dict) and str(x.get("name") or "").strip()]
    if not rows:
        return []
    lines = [
        f"**{title}**",
        "",
        "| 名称 | 占比 |",
        "| --- | ---: |",
    ]
    for row in rows:
        lines.append(f"| {_md_escape_cell(row.get('name'))} | {_fmt_pct(row.get('ratio'))} |")
    lines.append("")
    return lines


def _format_item_metric_lines(item: Mapping[str, Any]) -> list[str]:
    """Compact metric lines — avoid wide DingTalk tables (they render poorly)."""
    lines = [
        "浏览 {play} · 点赞 {like} · 评论 {comment} · 分享 {share} · 收藏 {collect}".format(
            play=int(item.get("playCount") or 0),
            like=int(item.get("likeCount") or 0),
            comment=int(item.get("commentCount") or 0),
            share=int(item.get("shareCount") or 0),
            collect=int(item.get("collectCount") or 0),
        )
    ]
    traffic: list[str] = []
    if item.get("completionRate") is not None:
        traffic.append(f"完播率 {_fmt_pct(item.get('completionRate'))}")
    if item.get("avgPlayDurationSec") is not None:
        traffic.append(f"平均时长 {_fmt_num(item.get('avgPlayDurationSec'))}秒")
    if item.get("bounceRate2s") is not None:
        traffic.append(f"2s跳出 {_fmt_pct(item.get('bounceRate2s'))}")
    if item.get("completionRate5s") is not None:
        traffic.append(f"5s完播 {_fmt_pct(item.get('completionRate5s'))}")
    if traffic:
        lines.append(" · ".join(traffic))
    diag = _diagnose_text(item.get("contentDiagnose"))
    if diag:
        lines.append(f"诊断：{diag}")
    return lines


def rehost_cover_for_dingtalk(cover_url: str, *, timeout: float = 25.0) -> Optional[str]:
    """Download a platform cover, convert to JPEG, upload to a temporary public host.

    DingTalk's crawler cannot reliably fetch Douyin/XHS signed CDNs (and may reject webp).
    Rehosting gives a short-lived public JPEG URL. Returns None on any failure.
    """
    url = (cover_url or "").strip()
    if not url or Image is None:
        return None
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.douyin.com/",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        jpeg = buf.getvalue()
        # litterbox: anonymous temporary host (24h). Used so DingTalk can fetch the image.
        up = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            files={
                "reqtype": (None, "fileupload"),
                "time": (None, "24h"),
                "fileToUpload": ("cover.jpg", jpeg, "image/jpeg"),
            },
            timeout=timeout,
        )
        if up.status_code != 200:
            return None
        public = (up.text or "").strip()
        if public.startswith("https://") and public.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
            return public
        return None
    except Exception:
        return None


def format_content_stats_markdown(
    *,
    platform_label: str,
    account_name: str,
    last_synced_at: Optional[str],
    items: Sequence[Mapping[str, Any]],
    rehost_covers: bool = False,
    include_covers: bool = True,
) -> tuple[str, str]:
    if not items:
        raise DingTalkPushError("请先同步", code=400)
    return format_multi_account_stats_markdown(
        sections=[
            {
                "platform_label": platform_label,
                "account_name": account_name,
                "last_synced_at": last_synced_at,
                "items": items,
            }
        ],
        rehost_covers=rehost_covers,
        include_covers=include_covers,
    )


def format_multi_account_stats_markdown(
    *,
    sections: Sequence[Mapping[str, Any]],
    rehost_covers: bool = False,
    include_covers: bool = True,
) -> tuple[str, str]:
    """Combine multiple account sections into one DingTalk markdown message."""
    usable = []
    for section in sections:
        items = list(section.get("items") or [])
        if not items:
            continue
        usable.append({**section, "items": items})
    if not usable:
        raise DingTalkPushError("请先同步", code=400)

    if len(usable) == 1:
        s0 = usable[0]
        heading = (
            f"{s0.get('platform_label') or ''} · {s0.get('account_name') or ''} · 内容数据"
        ).strip(" ·")
    else:
        heading = f"内容数据推送（{len(usable)} 个账号）"

    blocks: list[str] = []
    for section in usable:
        platform_label = str(section.get("platform_label") or "").strip() or "平台"
        account_name = str(section.get("account_name") or "").strip() or "账号"
        last_synced_at = section.get("last_synced_at")
        items = section["items"]
        lines = [
            f"### {platform_label} · {account_name} · 内容数据",
            f"同步时间：{last_synced_at or '—'}",
            "",
        ]
        for idx, item in enumerate(items, start=1):
            title = truncate_title(str(item.get("title") or ""))
            status = str(item.get("status") or "").strip()
            status_part = f"（{status}）" if status else ""
            lines.append(f"{idx}. **{title}**{status_part}")
            if include_covers:
                cover = str(item.get("coverUrl") or "").strip()
                if cover:
                    embed = rehost_cover_for_dingtalk(cover) if rehost_covers else cover
                    if embed:
                        lines.append(f"![封面]({embed})")
            lines.extend(_format_item_metric_lines(item))
            published = str(item.get("publishedAt") or "").strip()
            if published:
                lines.append(f"发布时间：{published}")
            boost = item.get("boostPlayCount")
            if boost:
                reason = _short_boost_reason(
                    None if item.get("boostReason") is None else str(item.get("boostReason"))
                )
                lines.append(
                    f"助推：+{int(boost)}"
                    + (f" · {reason}" if reason and reason != "—" else "")
                )
            lines.append("")
            lines.extend(_ratio_table("来源", item.get("trafficSources")))
            lines.extend(_ratio_table("性别", item.get("audienceGender")))
            lines.extend(_ratio_table("年龄", item.get("audienceAge")))
            lines.extend(_ratio_table("地域", item.get("audienceRegion")))
        blocks.append("\n".join(lines).rstrip())

    text = ("\n\n---\n\n".join(blocks) + "\n")
    return heading, text


def build_signed_webhook_url(webhook_url: str, secret: Optional[str]) -> str:
    if not secret:
        return webhook_url
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    sign = urllib.parse.quote_plus(
        base64.b64encode(
            hmac.new(
                secret.encode("utf-8"),
                string_to_sign.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
        )
    )
    sep = "&" if ("?" in webhook_url) else "?"
    return f"{webhook_url}{sep}timestamp={timestamp}&sign={sign}"


def send_markdown(
    *,
    webhook_url: str,
    secret: Optional[str],
    title: str,
    text: str,
    timeout: float = 10.0,
) -> None:
    if not (webhook_url or "").strip():
        raise DingTalkPushError("未配置 DINGTALK_WEBHOOK_URL", code=400)
    url = build_signed_webhook_url(webhook_url.strip(), (secret or "").strip() or None)
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise DingTalkPushError(f"钉钉请求失败: {e}", code=502) from e

    try:
        body = resp.json()
    except Exception:
        body = {}
    errcode = body.get("errcode", None if resp.ok else -1)
    if errcode not in (0, None) or not resp.ok:
        errmsg = body.get("errmsg") or resp.text or f"HTTP {resp.status_code}"
        raise DingTalkPushError(f"钉钉返回错误: {errmsg}", code=502)

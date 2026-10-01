"""文章素材的校验、下载和引用保护；外链下载固定解析后的公网地址。"""
from __future__ import annotations

import hashlib
import http.client
import io
import ipaddress
import socket
import ssl
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.parse import quote

from PIL import Image, UnidentifiedImageError

from .model import ArticleError


def utc_now():
    """数据库时间统一保存 UTC，界面自行按用户时区显示。"""
    return datetime.now(timezone.utc).isoformat()


def public_url(url: str):
    """校验全部解析地址，防止回环、内网、混合 DNS 和凭据 URL。"""
    if not isinstance(url, str) or not url.strip() or len(url) > 8192:
        raise ArticleError("图片链接必须为有效文本，且不能超过 8192 字")
    try:
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise ArticleError("图片链接端口无效") from exc
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ArticleError("图片链接必须为不含账号密码的公开 HTTP/HTTPS 地址")
    if port not in {80, 443}:
        raise ArticleError("公开图片链接只允许 80 或 443 端口")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parts.hostname, port, type=socket.SOCK_STREAM)}
    except (OSError, UnicodeError) as exc:
        raise ArticleError("图片链接域名无法解析") from exc
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ArticleError("图片链接不能指向本机、内网或保留地址")
    return parts, port, sorted(addresses)[0]


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """连接固定公网 IP，同时保留原始主机名的 TLS 证书与 SNI 校验。"""

    def __init__(self, hostname, address, port):
        super().__init__(hostname, port, timeout=15, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def download_image(url: str, max_bytes: int) -> bytes:
    """每次重定向重新校验目标；流式读取，拒绝超大或非图片响应。"""
    for _ in range(4):
        parts, port, address = public_url(url)
        conn = (PinnedHTTPSConnection(parts.hostname, address, port) if parts.scheme == "https"
                else http.client.HTTPConnection(address, port, timeout=15))
        host = parts.hostname.encode("idna").decode("ascii")
        if ":" in host:
            host = "[" + host + "]"
        if port != (443 if parts.scheme == "https" else 80):
            host += f":{port}"
        try:
            # 对中文文件名进行 URL 编码，保留调用者已有的编码和查询分隔符。
            target = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
            if parts.query:
                target += "?" + quote(parts.query, safe="/%?:@!$&'()*+,;=-._~")
            conn.request("GET", target,
                         headers={"Host": host, "User-Agent": "PostSail/Article", "Accept": "image/*"})
            response = conn.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise ArticleError("图片链接重定向缺少目标地址")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ArticleError(f"图片链接返回 HTTP {response.status}")
            if not (response.getheader("Content-Type") or "").lower().startswith("image/"):
                raise ArticleError("链接响应不是图片")
            try:
                size = int(response.getheader("Content-Length") or "0")
            except ValueError:
                size = 0
            if size > max_bytes:
                raise ArticleError("图片超过大小限制")
            chunks, count = [], 0
            while True:
                chunk = response.read(min(65536, max_bytes + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
                if count > max_bytes:
                    raise ArticleError("图片超过大小限制")
                chunks.append(chunk)
            return b"".join(chunks)
        except (OSError, http.client.HTTPException) as exc:
            raise ArticleError("公开图片下载失败或超时") from exc
        finally:
            conn.close()
    raise ArticleError("图片链接重定向次数过多")


class ArticleAssets:
    """正文图片单独注册，不与旧视频素材删除操作混用。"""

    def __init__(self, store, directory: Path, max_bytes=20 * 1024 * 1024):
        self.store, self.directory, self.max_bytes = store, Path(directory), max_bytes
        self.directory.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, filename="图片") -> dict:
        """解码验证真实图片，将 WebP 转为 PNG，按哈希去重。"""
        if not data or len(data) > self.max_bytes:
            raise ArticleError("图片为空或超过大小限制")
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ArticleError("文章图片仅支持 PNG、JPEG、WebP")
                if image.width * image.height > 40_000_000:
                    raise ArticleError("图片像素总量不能超过四千万")
                image.load()
                width, height, image_format = image.width, image.height, image.format
                if image_format == "WEBP":
                    output = io.BytesIO()
                    image.convert("RGBA").save(output, format="PNG")
                    data, image_format = output.getvalue(), "PNG"
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ArticleError("无法解码图片文件") from exc
        if len(data) > self.max_bytes:
            raise ArticleError("转换后的图片超过大小限制")
        digest = hashlib.sha256(data).hexdigest()
        with self.store.connect(write=True) as conn:
            existing = conn.execute("SELECT * FROM article_assets WHERE sha256=?", (digest,)).fetchone()
            if existing:
                return self.serialize(existing)
            asset_id = uuid.uuid4().hex
            extension = ".png" if image_format == "PNG" else ".jpg"
            path = self.directory / (asset_id + extension)
            path.write_bytes(data)
            conn.execute("INSERT INTO article_assets VALUES (?,?,?,?,?,?,?,?,?)",
                         (asset_id, Path(filename).name[:255], path.name, "image/png" if extension == ".png" else "image/jpeg",
                          len(data), width, height, digest, utc_now()))
            row = conn.execute("SELECT * FROM article_assets WHERE id=?", (asset_id,)).fetchone()
            return self.serialize(row)

    def import_url(self, url):
        """公网链接只作为素材输入，不在平台正文中保留外链依赖。"""
        return self.save(download_image(url, self.max_bytes), Path(urlsplit(url).path).name or "远程图片")

    def get(self, asset_id):
        """只有已登记的素材 ID 能解析为后端文件。"""
        with self.store.connect() as conn:
            row = conn.execute("SELECT * FROM article_assets WHERE id=?", (str(asset_id),)).fetchone()
        if not row:
            raise ArticleError("图片素材不存在", 404)
        result = dict(row)
        result["path"] = str(self.storage_path(row))
        return result

    def storage_path(self, row):
        """文件定位跟随当前配置目录，跨系统备份迁移不依赖历史绝对路径。"""
        suffix = ".png" if row["mime_type"] == "image/png" else ".jpg"
        path = (self.directory / (row["id"] + suffix)).resolve()
        if not path.is_relative_to(self.directory.resolve()):
            raise ArticleError("素材存储路径无效")
        return path

    @staticmethod
    def serialize(row):
        """不向 API 调用者泄露服务器文件路径。"""
        return {key: row[key] for key in ("id", "filename", "mime_type", "size", "width", "height", "created_at")} | {
            "url": f"/api/article-assets/{row['id']}/content"}

    def delete(self, asset_id):
        """草稿或任何发布快照引用的图片禁止删除。"""
        with self.store.connect(write=True) as conn:
            if conn.execute("SELECT 1 FROM article_asset_refs WHERE asset_id=?", (asset_id,)).fetchone():
                raise ArticleError("素材被文章或发布快照引用，不能删除", 409)
            row = conn.execute("SELECT * FROM article_assets WHERE id=?", (asset_id,)).fetchone()
            if not row:
                raise ArticleError("素材不存在", 404)
            self.storage_path(row).unlink(missing_ok=True)
            conn.execute("DELETE FROM article_assets WHERE id=?", (asset_id,))

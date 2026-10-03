import asyncio
import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from queue import Queue
from flask_cors import CORS
from myUtils.auth import check_cookie
from utils.platform_accounts import ACCOUNT_PLATFORMS, ARTICLE_ACCOUNT_TYPES, ARTICLE_ONLY_ACCOUNT_TYPES, ACCOUNT_UNAVAILABLE_REASONS, resolve_account_type, validate_imported_cookie, validate_bilibili_cookie_replacement
from utils.articles.model import ArticleError
from utils.articles.routes import register_article_routes
from utils.interactions.routes import register_interaction_routes
from utils.analytics.routes import register_analytics_routes
from utils.analytics.push import register_analytics_push_routes
from flask import Flask, request, jsonify, Response, render_template, send_from_directory
from conf import BASE_DIR
from myUtils.login import get_tencent_cookie, douyin_cookie_gen, get_ks_cookie, xiaohongshu_cookie_gen, baijiahao_cookie_gen, bilibili_cookie_gen, toutiao_cookie_gen, sohu_cookie_gen, zhihu_cookie_gen, weibo_cookie_gen, qiehao_cookie_gen, article_account_cookie_gen
from myUtils.postVideo import post_video_tencent, post_video_DouYin, post_video_ks, post_video_xhs, post_video_baijiahao, post_video_bilibili, post_video_toutiao, post_article_toutiao, post_article_baijiahao, post_article_sohu, post_article_zhihu
from uploader.douyin_uploader.content_stats import (
    DouyinStatsSyncError,
    ensure_content_stats_table,
    replace_account_stats,
    row_to_stat_item,
    sync_recent_items_sync as sync_douyin_content_stats,
)
from uploader.ks_uploader.content_stats import (
    KuaishouStatsSyncError,
    sync_recent_items_sync as sync_kuaishou_content_stats,
)
from uploader.xiaohongshu_uploader.content_stats import (
    XiaohongshuStatsSyncError,
    sync_recent_items_sync as sync_xiaohongshu_content_stats,
)
from uploader.bilibili_uploader.content_stats import (
    BilibiliStatsSyncError,
    sync_recent_items_sync as sync_bilibili_content_stats,
)

SUPPORTED_STATS_PLATFORMS = {
    "douyin": {"type": 3, "label": "抖音"},
    "kuaishou": {"type": 4, "label": "快手"},
    "xiaohongshu": {"type": 1, "label": "小红书"},
    "bilibili": {"type": 6, "label": "B站"},
}

import conf as app_conf
from myUtils.dingtalk import (
    DingTalkPushError,
    format_multi_account_stats_markdown,
    send_markdown,
)


def _dingtalk_webhook_url() -> str:
    return (getattr(app_conf, "DINGTALK_WEBHOOK_URL", None) or "").strip()


def _dingtalk_secret() -> str:
    return (getattr(app_conf, "DINGTALK_SECRET", None) or "").strip()


def _dingtalk_rehost_covers() -> bool:
    return bool(getattr(app_conf, "DINGTALK_REHOST_COVERS", True))


def _dingtalk_push_covers() -> bool:
    return bool(getattr(app_conf, "DINGTALK_PUSH_COVERS", True))


active_queues = {}
app = Flask(__name__)


def _db_path():
    """保留默认数据库位置，允许测试和自部署实例显式使用隔离数据库。"""
    return Path(app.config.get("OMNIPOST_DB_PATH", BASE_DIR / "db" / "database.db"))


def _row_to_stat_item(row):
    return row_to_stat_item(row)


def _load_stats_payload(conn, platform: str, account_id: int):
    ensure_content_stats_table(conn)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM content_stats
        WHERE platform = ? AND account_id = ?
        ORDER BY published_at DESC, id DESC
        """,
        (platform, account_id),
    )
    rows = cur.fetchall()
    last = rows[0]["synced_at"] if rows else None
    return {"items": [_row_to_stat_item(r) for r in rows], "lastSyncedAt": last}

#允许所有来源跨域访问
CORS(app)

# 限制上传文件大小为160MB
app.config['MAX_CONTENT_LENGTH'] = 160 * 1024 * 1024

# 获取当前目录（假设 index.html 和 assets 在这里）
current_dir = os.path.dirname(os.path.abspath(__file__))

# 处理所有静态资源请求（未来打包用）
@app.route('/assets/<filename>')
def custom_static(filename):
    return send_from_directory(os.path.join(current_dir, 'assets'), filename)

# 统一返回项目图标；保留旧地址兼容已缓存的页面。
@app.route('/favicon.ico')
@app.route('/postsail.svg')
@app.route('/vite.svg')
def favicon():
    """容器构建只保留 PostSail 图标，三个入口共用同一静态文件。"""
    return send_from_directory(os.path.join(current_dir, 'assets'), 'postsail.svg')

# （未来打包用）
@app.route('/')
def index():  # put application's code here
    return send_from_directory(current_dir, 'index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({
            "code": 400,
            "data": None,
            "msg": "No file part in the request"
        }), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({
            "code": 400,
            "data": None,
            "msg": "No selected file"
        }), 400
    try:
        # 保存文件到指定位置
        uuid_v1 = uuid.uuid1()
        print(f"UUID v1: {uuid_v1}")
        filepath = Path(BASE_DIR / "videoFile" / f"{uuid_v1}_{file.filename}")
        file.save(filepath)
        return jsonify({"code":200,"msg": "File uploaded successfully", "data": f"{uuid_v1}_{file.filename}"}), 200
    except Exception as e:
        return jsonify({"code":500,"msg": str(e),"data":None}), 500

@app.route('/getFile', methods=['GET'])
def get_file():
    # 获取 filename 参数
    filename = request.args.get('filename')

    if not filename:
        return jsonify({"code": 400, "msg": "filename is required", "data": None}), 400

    # 防止路径穿越攻击
    if '..' in filename or filename.startswith('/'):
        return jsonify({"code": 400, "msg": "Invalid filename", "data": None}), 400

    # 拼接完整路径
    file_path = str(Path(BASE_DIR / "videoFile"))

    # 返回文件
    return send_from_directory(file_path,filename)


@app.route('/uploadSave', methods=['POST'])
def upload_save():
    if 'file' not in request.files:
        return jsonify({
            "code": 400,
            "data": None,
            "msg": "No file part in the request"
        }), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({
            "code": 400,
            "data": None,
            "msg": "No selected file"
        }), 400

    # 获取表单中的自定义文件名（可选）
    custom_filename = request.form.get('filename', None)
    if custom_filename:
        filename = custom_filename + "." + file.filename.split('.')[-1]
    else:
        filename = file.filename

    try:
        # 生成 UUID v1
        uuid_v1 = uuid.uuid1()
        print(f"UUID v1: {uuid_v1}")

        # 构造文件名和路径
        final_filename = f"{uuid_v1}_{filename}"
        filepath = Path(BASE_DIR / "videoFile" / f"{uuid_v1}_{filename}")

        # 保存文件
        file.save(filepath)

        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                                INSERT INTO file_records (filename, filesize, file_path)
            VALUES (?, ?, ?)
                                ''', (filename, round(float(os.path.getsize(filepath)) / (1024 * 1024),2), final_filename))
            conn.commit()
            print("✅ 上传文件已记录")

        return jsonify({
            "code": 200,
            "msg": "File uploaded and saved successfully",
            "data": {
                "filename": filename,
                "filepath": final_filename
            }
        }), 200

    except Exception as e:
        print(f"Upload failed: {e}")
        return jsonify({
            "code": 500,
            "msg": f"upload failed: {e}",
            "data": None
        }), 500

@app.route('/getFiles', methods=['GET'])
def get_all_files():
    try:
        # 使用 with 自动管理数据库连接
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row  # 允许通过列名访问结果
            cursor = conn.cursor()

            # 查询所有记录
            cursor.execute("SELECT * FROM file_records")
            rows = cursor.fetchall()
            
            # 将结果转为字典列表，并提取UUID
            data = []
            for row in rows:
                row_dict = dict(row)
                # 从 file_path 中提取 UUID (文件名的第一部分，下划线前)
                if row_dict.get('file_path'):
                    file_path_parts = row_dict['file_path'].split('_', 1)  # 只分割第一个下划线
                    if len(file_path_parts) > 0:
                        row_dict['uuid'] = file_path_parts[0]  # UUID 部分
                    else:
                        row_dict['uuid'] = ''
                else:
                    row_dict['uuid'] = ''
                data.append(row_dict)

            return jsonify({
                "code": 200,
                "msg": "success",
                "data": data
            }), 200
    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": str("get file failed!"),
            "data": None
        }), 500


@app.route("/getAccounts", methods=['GET'])
def getAccounts():
    """快速获取所有账号信息，不进行cookie验证"""
    try:
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
            SELECT * FROM user_info''')
            rows = cursor.fetchall()
            rows_list = [list(row) for row in rows]

            print("\n📋 当前数据表内容（快速获取）：")
            for row in rows:
                print(row)

            return jsonify(
                {
                    "code": 200,
                    "msg": None,
                    "data": rows_list
                }), 200
    except Exception as e:
        print(f"获取账号列表时出错: {str(e)}")
        return jsonify({
            "code": 500,
            "msg": f"获取账号列表失败: {str(e)}",
            "data": None
        }), 500


@app.route("/getValidAccounts",methods=['GET'])
async def getValidAccounts():
    platform_type = request.args.get('type')
    if platform_type is not None:
        try:
            platform_type = int(platform_type)
        except ValueError:
            return jsonify({
                "code": 400,
                "msg": "Invalid platform type",
                "data": None
            }), 400

    with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
        cursor = conn.cursor()
        if platform_type is not None:
            cursor.execute('SELECT * FROM user_info WHERE type = ?', (platform_type,))
        else:
            cursor.execute('SELECT * FROM user_info')
        rows = cursor.fetchall()
        rows_list = [list(row) for row in rows]
        scope = f"type={platform_type}" if platform_type is not None else "all"
        print(f"\n📋 校验账号 ({scope})，共 {len(rows_list)} 条：")
        for row in rows:
            print(row)
        for row in rows_list:
            if row[1] in ACCOUNT_UNAVAILABLE_REASONS:
                continue
            flag = await check_cookie(row[1],row[2])
            new_status = 1 if flag else 0
            row[4] = new_status
            cursor.execute('''
            UPDATE user_info 
            SET status = ? 
            WHERE id = ?
            ''', (new_status, row[0]))
            conn.commit()
            print(f"✅ 用户状态已更新 id={row[0]} status={new_status}")
        return jsonify(
                        {
                            "code": 200,
                            "msg": None,
                            "data": rows_list
                        }),200

@app.route('/deleteFile', methods=['GET'])
def delete_file():
    file_id = request.args.get('id')

    if not file_id or not file_id.isdigit():
        return jsonify({
            "code": 400,
            "msg": "Invalid or missing file ID",
            "data": None
        }), 400

    try:
        # 获取数据库连接
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 查询要删除的记录
            cursor.execute("SELECT * FROM file_records WHERE id = ?", (file_id,))
            record = cursor.fetchone()

            if not record:
                return jsonify({
                    "code": 404,
                    "msg": "File not found",
                    "data": None
                }), 404

            record = dict(record)

            # 获取文件路径并删除实际文件
            file_path = Path(BASE_DIR / "videoFile" / record['file_path'])
            if file_path.exists():
                try:
                    file_path.unlink()  # 删除文件
                    print(f"✅ 实际文件已删除: {file_path}")
                except Exception as e:
                    print(f"⚠️ 删除实际文件失败: {e}")
                    # 即使删除文件失败，也要继续删除数据库记录，避免数据不一致
            else:
                print(f"⚠️ 实际文件不存在: {file_path}")

            # 删除数据库记录
            cursor.execute("DELETE FROM file_records WHERE id = ?", (file_id,))
            conn.commit()

        return jsonify({
            "code": 200,
            "msg": "File deleted successfully",
            "data": {
                "id": record['id'],
                "filename": record['filename']
            }
        }), 200

    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": str("delete failed!"),
            "data": None
        }), 500

@app.route('/deleteAccount', methods=['GET'])
def delete_account():
    account_id = request.args.get('id')

    if not account_id or not account_id.isdigit():
        return jsonify({
            "code": 400,
            "msg": "Invalid or missing account ID",
            "data": None
        }), 400

    account_id = int(account_id)

    try:
        # 获取数据库连接
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 查询要删除的记录
            cursor.execute("SELECT * FROM user_info WHERE id = ?", (account_id,))
            record = cursor.fetchone()

            if not record:
                return jsonify({
                    "code": 404,
                    "msg": "account not found",
                    "data": None
                }), 404

            record = dict(record)

            # 删除关联的cookie文件
            if record.get('filePath'):
                cookie_file_path = Path(BASE_DIR / "cookiesFile" / record['filePath'])
                if cookie_file_path.exists():
                    try:
                        cookie_file_path.unlink()
                        print(f"✅ Cookie文件已删除: {cookie_file_path}")
                    except Exception as e:
                        print(f"⚠️ 删除Cookie文件失败: {e}")

            # 删除数据库记录
            cursor.execute("DELETE FROM user_info WHERE id = ?", (account_id,))
            conn.commit()

        return jsonify({
            "code": 200,
            "msg": "account deleted successfully",
            "data": None
        }), 200

    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": f"delete failed: {str(e)}",
            "data": None
        }), 500


# SSE 登录接口
@app.route('/login')
def login():
    # 原有类型兼容，新增文章账号独立编号；2 始终是微信视频号。
    type = request.args.get('type')
    # 账号名
    id = request.args.get('id')
    try:
        type = str(resolve_account_type(type))
        if int(type) in ACCOUNT_UNAVAILABLE_REASONS:
            raise ValueError(ACCOUNT_UNAVAILABLE_REASONS[int(type)])
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    if not isinstance(id, str) or not id.strip() or len(id) > 100:
        return jsonify({"code": 400, "msg": "账号名称不能为空且不能超过 100 字", "data": None}), 400
    print(f"登录请求: type={type}, id={id}")

    # 模拟一个用于异步通信的队列
    status_queue = Queue()
    active_queues[id] = status_queue

    def on_close():
        print(f"清理队列: {id}")
        del active_queues[id]
    # 启动异步任务线程
    thread = threading.Thread(target=run_async_function, args=(type,id,status_queue), daemon=True)
    thread.start()
    response = Response(sse_stream(status_queue,), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'  # 关键：禁用 Nginx 缓冲
    response.headers['Content-Type'] = 'text/event-stream'
    response.headers['Connection'] = 'keep-alive'
    return response

def _is_article_request(data):
    """按明确文章能力分派；原有视频类型默认仍走视频，文章专用类型只走文章。"""
    if not isinstance(data, dict):
        return False
    try:
        platform_type = resolve_account_type(data.get('type'))
    except (TypeError, ValueError):
        return False
    return platform_type in ARTICLE_ONLY_ACCOUNT_TYPES or (platform_type in ARTICLE_ACCOUNT_TYPES and str(data.get('contentType', '')).strip().lower() == 'article')


def _validate_publish_capability(data):
    """显式文章请求不可回落到视频执行器，文章专用账号也不可误发视频。"""
    if not isinstance(data, dict):
        raise ArticleError("发布请求必须为 JSON 对象")
    try:
        kind = resolve_account_type(data.get("type"))
    except ValueError as exc:
        raise ArticleError(str(exc)) from exc
    mode = str(data.get("contentType") or "").strip().lower()
    if mode == "article" and kind not in ARTICLE_ACCOUNT_TYPES:
        raise ArticleError("该账号平台不支持统一文章发布")
    if mode == "video" and kind in ARTICLE_ONLY_ACCOUNT_TYPES:
        raise ArticleError("该账号平台当前仅支持文章发布")
    if kind in ACCOUNT_UNAVAILABLE_REASONS:
        raise ArticleError(ACCOUNT_UNAVAILABLE_REASONS[kind])


def _submit_legacy_article(data):
    """保留旧响应结构，同时返回批次 ID，供旧管理台查询真实结果。"""
    try:
        normalized = {**data, "type": resolve_account_type(data.get("type"))}
        batch = app.extensions['legacy_article_publish'](normalized)
        return jsonify({"code": 200, "msg": "文章任务已受理，请查看各平台实际结果",
                        "data": {**batch, "batchId": batch['id']}}), 200
    except ArticleError as exc:
        return jsonify({"code": exc.status, "msg": str(exc), "data": None}), exc.status


@app.route('/postVideo', methods=['POST'])
def postVideo():
    # 获取JSON数据
    data = request.get_json()

    if not data:
        return jsonify({"code": 400, "msg": "请求数据不能为空", "data": None}), 400

    try:
        _validate_publish_capability(data)
    except ArticleError as exc:
        return jsonify({"code": exc.status, "msg": str(exc), "data": None}), exc.status

    # 旧文章调用也走持久化任务；HTTP 200 仅表示受理，不再使用视频后台线程。
    if _is_article_request(data):
        return _submit_legacy_article(data)

    # 从JSON数据中提取fileList和accountList
    file_list = data.get('fileList', [])
    account_list = data.get('accountList', [])
    type = data.get('type')
    title = data.get('title')
    tags = data.get('tags')
    category = data.get('category')
    enableTimer = data.get('enableTimer')
    if category == 0:
        category = None
    productLink = data.get('productLink', '')
    productTitle = data.get('productTitle', '')
    thumbnail_path = data.get('thumbnail', '') or data.get('coverImage', '')
    cover_images = data.get('coverImages') or data.get('cover_images') or []
    if isinstance(cover_images, str):
        cover_images = [x.strip() for x in cover_images.split(',') if x.strip()]
    elif not isinstance(cover_images, list):
        cover_images = []
    else:
        cover_images = [str(x).strip() for x in cover_images if str(x).strip()]
    # 兼容：仅传单图时并入 coverImages
    if thumbnail_path and str(thumbnail_path).strip() and str(thumbnail_path).strip() not in cover_images:
        if not cover_images:
            cover_images = [str(thumbnail_path).strip()]
    is_draft = data.get('isDraft', False)  # 新增参数：是否保存为草稿
    ai_generated = data.get('aiGenerated', False)  # 抖音/快手/小红书/视频号 AI 内容声明
    dry_run = data.get('dryRun', False)  # 仅预览不发布：填完表后不点发布
    # B站创作声明 id：-1/1/2/3/4；None 表示不传
    bilibili_creation_statement = data.get('bilibiliCreationStatement', None)
    # 今日头条内容类型：video（默认）| article
    content_type = (data.get('contentType') or 'video').strip().lower()
    article_body = data.get('articleBody') or data.get('body') or ''
    # 今日头条图文作品声明（单选）
    work_statement = data.get('workStatement') or data.get('work_statement') or ''
    work_statements = data.get('workStatements') or data.get('work_statements') or []
    if work_statement and str(work_statement).strip():
        work_statements = [str(work_statement).strip()]
    elif isinstance(work_statements, str):
        work_statements = [work_statements] if work_statements.strip() else []
    elif not isinstance(work_statements, list):
        work_statements = []
    else:
        work_statements = [str(x).strip() for x in work_statements if str(x).strip()]
    # 单选：最多保留第一项
    work_statements = work_statements[:1]

    videos_per_day = data.get('videosPerDay')
    daily_times = data.get('dailyTimes')
    start_days = data.get('startDays')

    if type is None or type == "":
        return jsonify({"code": 400, "msg": "平台类型不能为空", "data": None}), 400
    try:
        type = int(type)
    except (TypeError, ValueError):
        return jsonify({"code": 400, "msg": f"不支持的平台类型: {type}", "data": None}), 400

    # 支持图文文章的平台：5=百家号，7=今日头条，8=搜狐号，9=知乎
    ARTICLE_CAPABLE_PLATFORMS = (5, 7, 8, 9)
    # 搜狐号/知乎第一期仅支持图文
    if type == 8:
        content_type = 'article'
    if type == 9:
        content_type = 'article'
    is_article = (type in ARTICLE_CAPABLE_PLATFORMS and content_type == 'article')
    is_toutiao_article = (type == 7 and content_type == 'article')
    is_baijiahao_article = (type == 5 and content_type == 'article')
    is_sohu_article = (type == 8)
    is_zhihu_article = (type == 9)

    # 参数校验
    if not is_article and not file_list:
        return jsonify({"code": 400, "msg": "文件列表不能为空", "data": None}), 400
    if not account_list:
        return jsonify({"code": 400, "msg": "账号列表不能为空", "data": None}), 400
    if is_article:
        if not title or not str(title).strip():
            return jsonify({"code": 400, "msg": "文章标题不能为空", "data": None}), 400
        if is_sohu_article:
            title_len = len(str(title).strip())
            if title_len < 5 or title_len > 72:
                return jsonify({"code": 400, "msg": "搜狐号文章标题需 5-72 个字", "data": None}), 400
        if is_zhihu_article:
            title_len = len(str(title).strip())
            if title_len > 100:
                return jsonify({"code": 400, "msg": "知乎文章标题最多 100 个字", "data": None}), 400
        if not article_body or not str(article_body).strip():
            return jsonify({"code": 400, "msg": "文章正文不能为空", "data": None}), 400
        # 百家号图文标题下限 2 字
        if is_baijiahao_article and len(str(title).strip()) < 2:
            return jsonify({"code": 400, "msg": "百家号图文标题至少 2 个字", "data": None}), 400
        if is_baijiahao_article and not str(thumbnail_path or "").strip():
            return jsonify({"code": 400, "msg": "百家号图文展示封面不能为空", "data": None}), 400
    # 小红书（1）、视频号（2）、抖音（3）、快手（4）标题非必填，其它平台仍必填
    elif type not in (1, 2, 3, 4) and not title:
        return jsonify({"code": 400, "msg": "标题不能为空", "data": None}), 400
    if title is None:
        title = ""
    if is_sohu_article:
        title = str(title).strip()[:72]
    if is_zhihu_article:
        title = str(title).strip()[:100]
    if bilibili_creation_statement is not None and bilibili_creation_statement != "":
        try:
            bilibili_creation_statement = int(bilibili_creation_statement)
        except (TypeError, ValueError):
            return jsonify({"code": 400, "msg": f"非法的创作声明: {bilibili_creation_statement}", "data": None}), 400
    else:
        bilibili_creation_statement = None

    # 打印获取到的数据（仅作为示例）
    print("File List:", file_list)
    print("Account List:", account_list)
    print(
        f"enableTimer={enableTimer}, dryRun={dry_run}, aiGenerated={ai_generated}, "
        f"bilibiliCreationStatement={bilibili_creation_statement}, "
        f"contentType={content_type}, cover={thumbnail_path}, workStatements={work_statements}",
        flush=True,
    )

    # 参数校验通过后，在后台线程中执行发布任务，避免阻塞Flask主线程。
    # 前端拿到的 200 只表示“任务已提交”，不代表平台已经发布成功。
    def run_publish_task():
        try:
            print(
                f"🧵 后台发布线程启动: type={type}, title={title}, dryRun={dry_run}, contentType={content_type}",
                flush=True,
            )
            match type:
                case 1:
                    post_video_xhs(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                                       start_days, dry_run, ai_generated)
                case 2:
                    post_video_tencent(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                                       start_days, is_draft, dry_run, ai_generated)
                case 3:
                    post_video_DouYin(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                              start_days, thumbnail_path, productLink, productTitle, ai_generated, dry_run)
                case 4:
                    post_video_ks(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                              start_days, dry_run, ai_generated)
                case 5:
                    if content_type == 'article':
                        post_article_baijiahao(
                            title,
                            article_body,
                            tags,
                            account_list,
                            enableTimer,
                            videos_per_day,
                            daily_times,
                            start_days,
                            dry_run,
                            thumbnail_path,
                        )
                    else:
                        post_video_baijiahao(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                                  start_days, dry_run)
                case 6:
                    post_video_bilibili(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                              start_days, dry_run, bilibili_creation_statement)
                case 7:
                    if content_type == 'article':
                        post_article_toutiao(
                            title,
                            article_body,
                            tags,
                            account_list,
                            enableTimer,
                            videos_per_day,
                            daily_times,
                            start_days,
                            dry_run,
                            thumbnail_path,
                            work_statements,
                        )
                    else:
                        post_video_toutiao(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                                  start_days, dry_run)
                case 8:
                    post_article_sohu(
                        title,
                        article_body,
                        tags,
                        account_list,
                        enableTimer,
                        videos_per_day,
                        daily_times,
                        start_days,
                        dry_run,
                        thumbnail_path,
                        work_statements[0] if work_statements else (work_statement or None),
                        cover_images,
                    )
                case 9:
                    post_article_zhihu(
                        title,
                        article_body,
                        tags,
                        account_list,
                        enableTimer,
                        videos_per_day,
                        daily_times,
                        start_days,
                        dry_run,
                        thumbnail_path,
                        work_statements[0] if work_statements else (work_statement or None),
                    )
            print(f"✅ 发布任务完成: type={type}, title={title}", flush=True)
        except Exception as e:
            print(f"❌ 发布视频时出错: {str(e)}", flush=True)
            import traceback
            traceback.print_exc()

    thread = threading.Thread(target=run_publish_task, daemon=True)
    thread.start()

    if type == 6 and dry_run:
        submit_msg = "B站仅预览模式不会实际上传（无浏览器可预览）"
    elif type == 6:
        submit_msg = "B站上传任务已提交，后台通过 biliup 执行（不会打开浏览器）"
    elif is_toutiao_article and dry_run:
        submit_msg = "今日头条文章任务已提交：仅预览不发布"
    elif is_toutiao_article:
        submit_msg = "今日头条文章发布任务已提交，正在后台执行"
    elif is_sohu_article and dry_run:
        submit_msg = "搜狐号文章任务已提交：仅预览不发布"
    elif is_sohu_article:
        submit_msg = "搜狐号文章发布任务已提交，正在后台执行"
    elif is_zhihu_article and dry_run:
        submit_msg = "知乎文章任务已提交：仅预览不发布"
    elif is_zhihu_article:
        submit_msg = "知乎文章发布任务已提交，正在后台执行"
    elif type == 5 and content_type == 'article' and dry_run:
        submit_msg = "百家号图文文章任务已提交：仅预览不发布（可能出现自动保存草稿，不等于已发布）"
    elif type == 5 and content_type == 'article':
        submit_msg = "百家号图文文章发布任务已提交，浏览器将自动打开"
    elif type == 5:
        submit_msg = "百家号视频发布任务已提交，浏览器将自动打开上传"
    else:
        submit_msg = "发布任务已提交，正在后台执行"

    return jsonify(
        {
            "code": 200,
            "msg": submit_msg,
            "data": None
        }), 200


@app.route('/updateUserinfo', methods=['POST'])
def updateUserinfo():
    # 获取JSON数据
    data = request.get_json()

    # 从JSON数据中提取 type 和 userName
    user_id = data.get('id')
    type = data.get('type')
    userName = data.get('userName')
    try:
        # 获取数据库连接
        with sqlite3.connect(Path(BASE_DIR / "db" / "database.db")) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 更新数据库记录
            cursor.execute('''
                           UPDATE user_info
                           SET type     = ?,
                               userName = ?
                           WHERE id = ?;
                           ''', (type, userName, user_id))
            conn.commit()

        return jsonify({
            "code": 200,
            "msg": "account update successfully",
            "data": None
        }), 200

    except Exception as e:
        return jsonify({
            "code": 500,
            "msg": str("update failed!"),
            "data": None
        }), 500

@app.route('/postVideoBatch', methods=['POST'])
def postVideoBatch():
    data_list = request.get_json()

    if not isinstance(data_list, list):
        return jsonify({"code": 400, "msg": "Expected a JSON array", "data": None}), 400
    # 批次先核对全部能力，避免后续条目类型错误时前面的内容已开始发送。
    try:
        for item in data_list:
            _validate_publish_capability(item)
    except ArticleError as exc:
        return jsonify({"code": exc.status, "msg": str(exc), "data": None}), exc.status
    # 在创建任何任务之前拒绝文章定时，避免半个批次已发布才发现不支持。
    if any(_is_article_request(item) and (item.get('enableTimer') or item.get('schedule') or item.get('publish_date'))
           for item in data_list):
        return jsonify({"code": 400, "msg": "首版文章仅支持立即发布，不支持定时", "data": None}), 400
    article_batches = []
    for data in data_list:
        if _is_article_request(data):
            try:
                normalized = {**data, "type": resolve_account_type(data.get("type"))}
                article_batches.append(app.extensions['legacy_article_publish'](normalized))
            except ArticleError as exc:
                return jsonify({"code": exc.status, "msg": str(exc), "data": {"batches": article_batches}}), exc.status
            continue
        # 从JSON数据中提取fileList和accountList
        file_list = data.get('fileList', [])
        account_list = data.get('accountList', [])
        type = data.get('type')
        title = data.get('title')
        tags = data.get('tags')
        category = data.get('category')
        enableTimer = data.get('enableTimer')
        if category == 0:
            category = None
        productLink = data.get('productLink', '')
        productTitle = data.get('productTitle', '')
        is_draft = data.get('isDraft', False)
        ai_generated = data.get('aiGenerated', False)
        dry_run = data.get('dryRun', False)
        thumbnail_path = data.get('thumbnail', '') or data.get('coverImage', '')
        cover_images = data.get('coverImages') or data.get('cover_images') or []
        if isinstance(cover_images, str):
            cover_images = [x.strip() for x in cover_images.split(',') if x.strip()]
        elif not isinstance(cover_images, list):
            cover_images = []
        else:
            cover_images = [str(x).strip() for x in cover_images if str(x).strip()]
        if thumbnail_path and str(thumbnail_path).strip() and str(thumbnail_path).strip() not in cover_images:
            if not cover_images:
                cover_images = [str(thumbnail_path).strip()]
        content_type = (data.get('contentType') or 'video').strip().lower()
        article_body = data.get('articleBody') or data.get('body') or ''
        work_statement = data.get('workStatement') or data.get('work_statement') or ''
        work_statements = data.get('workStatements') or data.get('work_statements') or []
        if work_statement and str(work_statement).strip():
            work_statements = [str(work_statement).strip()]
        elif isinstance(work_statements, str):
            work_statements = [work_statements] if work_statements.strip() else []
        elif not isinstance(work_statements, list):
            work_statements = []
        else:
            work_statements = [str(x).strip() for x in work_statements if str(x).strip()]
        work_statements = work_statements[:1]
        bilibili_creation_statement = data.get('bilibiliCreationStatement', None)
        if bilibili_creation_statement is not None and bilibili_creation_statement != "":
            try:
                bilibili_creation_statement = int(bilibili_creation_statement)
            except (TypeError, ValueError):
                bilibili_creation_statement = None
        else:
            bilibili_creation_statement = None

        videos_per_day = data.get('videosPerDay')
        daily_times = data.get('dailyTimes')
        start_days = data.get('startDays')
        # 搜狐号/知乎第一期仅支持图文
        if type == 8:
            content_type = 'article'
            title_text = str(title or "").strip()
            if len(title_text) < 5 or len(title_text) > 72:
                return jsonify({"code": 400, "msg": "搜狐号文章标题需 5-72 个字", "data": None}), 400
            title = title_text[:72]
        if type == 9:
            content_type = 'article'
            title_text = str(title or "").strip()
            if len(title_text) > 100:
                return jsonify({"code": 400, "msg": "知乎文章标题最多 100 个字", "data": None}), 400
            title = title_text[:100]
        is_baijiahao_article = (type == 5 and content_type == 'article')
        if is_baijiahao_article and not str(thumbnail_path or "").strip():
            return jsonify({"code": 400, "msg": "百家号图文展示封面不能为空", "data": None}), 400
        # 打印获取到的数据（仅作为示例）
        print("File List:", file_list)
        print("Account List:", account_list)
        match type:
            case 1:
                post_video_xhs(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                               start_days, dry_run, ai_generated)
            case 2:
                post_video_tencent(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                                   start_days, is_draft, dry_run, ai_generated)
            case 3:
                post_video_DouYin(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                          start_days, thumbnail_path, productLink, productTitle, ai_generated, dry_run)
            case 4:
                post_video_ks(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                          start_days, dry_run)
            case 5:
                if content_type == 'article':
                    post_article_baijiahao(
                        title,
                        article_body,
                        tags,
                        account_list,
                        enableTimer,
                        videos_per_day,
                        daily_times,
                        start_days,
                        dry_run,
                        thumbnail_path,
                    )
                else:
                    post_video_baijiahao(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                              start_days, dry_run)
            case 6:
                post_video_bilibili(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                          start_days, dry_run, bilibili_creation_statement)
            case 7:
                if content_type == 'article':
                    post_article_toutiao(
                        title,
                        article_body,
                        tags,
                        account_list,
                        enableTimer,
                        videos_per_day,
                        daily_times,
                        start_days,
                        dry_run,
                        thumbnail_path,
                        work_statements,
                    )
                else:
                    post_video_toutiao(title, file_list, tags, account_list, category, enableTimer, videos_per_day, daily_times,
                              start_days, dry_run)
            case 8:
                post_article_sohu(
                    title,
                    article_body,
                    tags,
                    account_list,
                    enableTimer,
                    videos_per_day,
                    daily_times,
                    start_days,
                    dry_run,
                    thumbnail_path,
                    work_statements[0] if work_statements else (work_statement or None),
                    cover_images,
                )
            case 9:
                post_article_zhihu(
                    title,
                    article_body,
                    tags,
                    account_list,
                    enableTimer,
                    videos_per_day,
                    daily_times,
                    start_days,
                    dry_run,
                    thumbnail_path,
                    work_statements[0] if work_statements else (work_statement or None),
                )
    # 返回响应给客户端
    return jsonify(
        {
            "code": 200,
            "msg": "文章任务已受理，请查看各平台实际结果" if article_batches else None,
            "data": {"batches": article_batches} if article_batches else None
        }), 200

def _import_account_cookie(create_new=False):
    """结构和真实平台会话校验通过后原子替换，失败不会损坏已有账号凭据。"""
    temporary = None
    try:
        uploaded = request.files.get("file")
        if uploaded is None or not uploaded.filename or not uploaded.filename.lower().endswith(".json"):
            raise ValueError("请上传 JSON 格式的 Cookie 文件")
        account_type = resolve_account_type(request.form.get("platform"))
        if account_type in ACCOUNT_UNAVAILABLE_REASONS:
            raise ValueError(ACCOUNT_UNAVAILABLE_REASONS[account_type])
        root = Path(BASE_DIR / "cookiesFile").resolve()
        root.mkdir(parents=True, exist_ok=True)
        database = Path(BASE_DIR / "db" / "database.db")
        if create_new:
            name = (request.form.get("name") or "").strip()
            if not name or len(name) > 100:
                raise ValueError("账号名称不能为空且不能超过 100 字")
            destination = root / f"{ACCOUNT_PLATFORMS[account_type]}_{uuid.uuid4().hex}.json"
        else:
            account_id = request.form.get("id")
            if not account_id or not account_id.isdigit():
                raise ValueError("账号 ID 无效")
            with sqlite3.connect(database) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT type,filePath,userName FROM user_info WHERE id=?", (account_id,)).fetchone()
            if row is None:
                return jsonify({"code": 404, "msg": "账号不存在", "data": None}), 404
            if row["type"] != account_type:
                raise ValueError("上传平台与账号平台不一致")
            destination = (root / row["filePath"]).resolve()
            if not destination.is_relative_to(root) or destination == root:
                raise ValueError("账号 Cookie 路径无效")
            name = row["userName"]
        raw = uploaded.stream.read(5 * 1024 * 1024 + 1)
        if len(raw) > 5 * 1024 * 1024:
            raise ValueError("Cookie 文件不能超过 5MB")
        try:
            payload = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeError, ValueError) as exc:
            raise ValueError("Cookie 文件不是有效的 UTF-8 JSON") from exc
        state = validate_imported_cookie(account_type, payload)
        if account_type == 6 and not create_new:
            validate_bilibili_cookie_replacement(destination, payload)
        # B站保留 biliup 的原始数据，避免文章导入破坏视频 token_info 等字段。
        saved_payload = payload if account_type == 6 else state
        temporary = root / f".import-{uuid.uuid4().hex}.json"
        temporary.write_text(json.dumps(saved_payload, ensure_ascii=False), encoding="utf-8")
        temporary.chmod(0o600)
        if not asyncio.run(check_cookie(account_type, temporary.name)):
            raise ValueError("Cookie 登录状态校验未通过，请重新登录；浏览器依赖不可用时请检查配置")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(database) as conn:
            if create_new:
                cursor = conn.execute("INSERT INTO user_info(type,filePath,userName,status) VALUES(?,?,?,1)",
                                      (account_type, destination.name, name))
                account_id = cursor.lastrowid
            else:
                conn.execute("UPDATE user_info SET status=1 WHERE id=?", (account_id,))
            # 平台校验可能耗时，落盘前再次保护期间更新的 biliup 凭据。
            if account_type == 6 and not create_new:
                validate_bilibili_cookie_replacement(destination, payload)
            temporary.replace(destination)
        return jsonify({"code": 200, "msg": "Cookie 已导入并通过登录校验", "data": {
            "id": int(account_id), "type": account_type, "filePath": destination.name, "userName": name, "status": 1}}), 200
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc), "data": None}), 400
    except Exception:
        return jsonify({"code": 500, "msg": "Cookie 导入失败，请检查数据库和浏览器配置", "data": None}), 500
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


@app.route('/uploadCookie', methods=['POST'])
def upload_cookie():
    """兼容既有账号凭据替换，并校验请求平台与数据库账号类型一致。"""
    return _import_account_cookie()


@app.route('/importCookie', methods=['POST'])
def import_cookie():
    """直接从已登录会话添加账号，支持无图形终端环境中的 Cookie 导入。"""
    return _import_account_cookie(create_new=True)


# Cookie文件下载API
@app.route('/downloadCookie', methods=['GET'])
def download_cookie():
    try:
        file_path = request.args.get('filePath')
        if not file_path:
            return jsonify({
                "code": 500,
                "msg": "缺少文件路径参数",
                "data": None
            }), 400

        # 验证文件路径的安全性，防止路径遍历攻击
        cookie_file_path = Path(BASE_DIR / "cookiesFile" / file_path).resolve()
        base_path = Path(BASE_DIR / "cookiesFile").resolve()

        if not cookie_file_path.is_relative_to(base_path):
            return jsonify({
                "code": 500,
                "msg": "非法文件路径",
                "data": None
            }), 400

        if not cookie_file_path.exists():
            return jsonify({
                "code": 500,
                "msg": "Cookie文件不存在",
                "data": None
            }), 404

        # 返回文件
        return send_from_directory(
            directory=str(cookie_file_path.parent),
            path=cookie_file_path.name,
            as_attachment=True
        )

    except Exception as e:
        print(f"下载Cookie文件时出错: {str(e)}")
        return jsonify({
            "code": 500,
            "msg": f"下载Cookie文件失败: {str(e)}",
            "data": None
        }), 500


@app.route("/proxyImage", methods=["GET"])
def proxy_image():
    """代理外链封面图，规避 B 站等 CDN 防盗链。"""
    from urllib.parse import urlparse

    import requests as http_requests

    raw_url = (request.args.get("url") or "").strip()
    if not raw_url:
        return jsonify({"code": 400, "msg": "url 不能为空", "data": None}), 400
    try:
        parsed = urlparse(raw_url)
    except Exception:
        return jsonify({"code": 400, "msg": "url 无效", "data": None}), 400
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return jsonify({"code": 400, "msg": "仅支持 http/https 图片地址", "data": None}), 400
    host = parsed.hostname
    if not host:
        return jsonify({"code": 400, "msg": "url 无效", "data": None}), 400
    host = host.lower()
    allowed_suffixes = (".hdslb.com",)
    allowed_exact = {"hdslb.com"}
    if not (host in allowed_exact or any(host.endswith(suf) for suf in allowed_suffixes)):
        return jsonify({"code": 403, "msg": "该图片域名不允许代理", "data": None}), 403

    try:
        upstream = http_requests.get(
            raw_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.bilibili.com/",
            },
            timeout=20,
            stream=True,
        )
    except Exception as e:
        return jsonify({"code": 502, "msg": f"拉取图片失败: {e}", "data": None}), 502
    if upstream.status_code != 200:
        return jsonify({"code": 502, "msg": f"上游返回 {upstream.status_code}", "data": None}), 502

    content_type = (upstream.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
    if not content_type.startswith("image/"):
        return jsonify({"code": 502, "msg": "上游不是图片", "data": None}), 502

    # cap ~5MB
    chunks = []
    total = 0
    for chunk in upstream.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > 5 * 1024 * 1024:
            return jsonify({"code": 502, "msg": "图片过大", "data": None}), 502
        chunks.append(chunk)
    body = b"".join(chunks)
    return Response(body, status=200, mimetype=content_type, headers={
        "Cache-Control": "public, max-age=86400",
    })


@app.route("/getContentStats", methods=["GET"])
def get_content_stats():
    account_id = request.args.get("accountId", type=int)
    platform = (request.args.get("platform") or "douyin").strip().lower()
    if not account_id:
        return jsonify({"code": 400, "msg": "accountId 不能为空", "data": None}), 400
    if platform not in SUPPORTED_STATS_PLATFORMS:
        return jsonify({"code": 400, "msg": "仅支持 platform=douyin|kuaishou|xiaohongshu|bilibili", "data": None}), 400
    try:
        with sqlite3.connect(_db_path()) as conn:
            payload = _load_stats_payload(conn, platform, account_id)
        return jsonify({"code": 200, "msg": None, "data": payload}), 200
    except Exception as e:
        return jsonify({"code": 500, "msg": f"读取失败: {e}", "data": None}), 500


@app.route("/syncContentStats", methods=["POST"])
def sync_content_stats():
    body = request.get_json(silent=True) or {}
    account_id = body.get("accountId")
    platform = str(body.get("platform") or "douyin").strip().lower()
    try:
        limit = int(body.get("limit") or 5)
    except (TypeError, ValueError):
        return jsonify({"code": 400, "msg": "limit 无效", "data": None}), 400
    try:
        account_id = int(account_id)
    except (TypeError, ValueError):
        return jsonify({"code": 400, "msg": "accountId 无效", "data": None}), 400
    meta = SUPPORTED_STATS_PLATFORMS.get(platform)
    if not meta:
        return jsonify({"code": 400, "msg": "仅支持 platform=douyin|kuaishou|xiaohongshu|bilibili", "data": None}), 400
    if limit < 1 or limit > 20:
        return jsonify({"code": 400, "msg": "limit 需在 1-20", "data": None}), 400

    try:
        with sqlite3.connect(_db_path()) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT id, type, filePath FROM user_info WHERE id = ?", (account_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({"code": 404, "msg": "账号不存在", "data": None}), 404
            if int(row["type"]) != meta["type"]:
                return jsonify({"code": 400, "msg": f"该账号不是{meta['label']}账号", "data": None}), 400
            cookie_path = Path(BASE_DIR / "cookiesFile" / row["filePath"])
    except Exception as e:
        return jsonify({"code": 500, "msg": f"查询账号失败: {e}", "data": None}), 500

    try:
        if platform == "douyin":
            items = sync_douyin_content_stats(cookie_path, limit=limit)
        elif platform == "kuaishou":
            items = sync_kuaishou_content_stats(cookie_path, limit=limit)
        elif platform == "xiaohongshu":
            items = sync_xiaohongshu_content_stats(cookie_path, limit=limit)
        else:
            items = sync_bilibili_content_stats(cookie_path, limit=limit)
    except (
        DouyinStatsSyncError,
        KuaishouStatsSyncError,
        XiaohongshuStatsSyncError,
        BilibiliStatsSyncError,
    ) as e:
        return jsonify({"code": e.code, "msg": e.message, "data": None}), e.code
    except Exception as e:
        return jsonify({"code": 500, "msg": f"同步失败: {e}", "data": None}), 500

    from utils.analytics.store import business_now
    synced_at = business_now().isoformat(timespec="microseconds")
    try:
        with sqlite3.connect(_db_path()) as conn:
            replace_account_stats(
                conn,
                platform=platform,
                account_id=account_id,
                items=items,
                synced_at=synced_at,
            )
            payload = _load_stats_payload(conn, platform, account_id)
        return jsonify({"code": 200, "msg": "同步成功", "data": payload}), 200
    except Exception as e:
        return jsonify({"code": 500, "msg": f"写入失败: {e}", "data": None}), 500


@app.route("/pushContentStatsToDingTalk", methods=["POST"])
def push_content_stats_to_dingtalk():
    body = request.get_json(silent=True) or {}
    webhook = _dingtalk_webhook_url()
    if not webhook:
        return jsonify({"code": 400, "msg": "未配置 DINGTALK_WEBHOOK_URL", "data": None}), 400

    raw_accounts = body.get("accounts")
    targets = []
    if isinstance(raw_accounts, list) and raw_accounts:
        for entry in raw_accounts:
            if not isinstance(entry, dict):
                return jsonify({"code": 400, "msg": "accounts 项无效", "data": None}), 400
            platform = str(entry.get("platform") or "").strip().lower()
            try:
                account_id = int(entry.get("accountId"))
            except (TypeError, ValueError):
                return jsonify({"code": 400, "msg": "accountId 无效", "data": None}), 400
            if platform not in SUPPORTED_STATS_PLATFORMS:
                return jsonify(
                    {
                        "code": 400,
                        "msg": "仅支持 platform=douyin|kuaishou|xiaohongshu|bilibili",
                        "data": None,
                    }
                ), 400
            targets.append({"accountId": account_id, "platform": platform})
    else:
        platform = str(body.get("platform") or "douyin").strip().lower()
        try:
            account_id = int(body.get("accountId"))
        except (TypeError, ValueError):
            return jsonify({"code": 400, "msg": "accountId 无效", "data": None}), 400
        if platform not in SUPPORTED_STATS_PLATFORMS:
            return jsonify(
                {
                    "code": 400,
                    "msg": "仅支持 platform=douyin|kuaishou|xiaohongshu|bilibili",
                    "data": None,
                }
            ), 400
        targets.append({"accountId": account_id, "platform": platform})

    # de-dupe while preserving order
    seen = set()
    unique_targets = []
    for t in targets:
        key = (t["platform"], t["accountId"])
        if key in seen:
            continue
        seen.add(key)
        unique_targets.append(t)
    targets = unique_targets

    if not targets:
        return jsonify({"code": 400, "msg": "请选择账号", "data": None}), 400
    if len(targets) > 20:
        return jsonify({"code": 400, "msg": "一次最多推送 20 个账号", "data": None}), 400

    sections = []
    skipped = []
    try:
        with sqlite3.connect(_db_path()) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            for t in targets:
                platform = t["platform"]
                account_id = t["accountId"]
                meta = SUPPORTED_STATS_PLATFORMS[platform]
                cur.execute(
                    "SELECT id, type, userName FROM user_info WHERE id = ?",
                    (account_id,),
                )
                row = cur.fetchone()
                if not row:
                    skipped.append({"accountId": account_id, "platform": platform, "reason": "账号不存在"})
                    continue
                if int(row["type"]) != meta["type"]:
                    skipped.append(
                        {
                            "accountId": account_id,
                            "platform": platform,
                            "reason": f"不是{meta['label']}账号",
                        }
                    )
                    continue
                payload = _load_stats_payload(conn, platform, account_id)
                items = payload.get("items") or []
                if not items:
                    skipped.append(
                        {
                            "accountId": account_id,
                            "platform": platform,
                            "accountName": row["userName"] or str(account_id),
                            "reason": "尚未同步",
                        }
                    )
                    continue
                sections.append(
                    {
                        "platform_label": meta["label"],
                        "account_name": row["userName"] or str(account_id),
                        "last_synced_at": payload.get("lastSyncedAt"),
                        "items": items,
                        "accountId": account_id,
                        "platform": platform,
                    }
                )
    except Exception as e:
        return jsonify({"code": 500, "msg": f"读取失败: {e}", "data": None}), 500

    if not sections:
        return jsonify(
            {
                "code": 400,
                "msg": "所选账号均无已同步数据，请先同步",
                "data": {"skipped": skipped},
            }
        ), 400

    try:
        title, text = format_multi_account_stats_markdown(
            sections=sections,
            rehost_covers=_dingtalk_rehost_covers(),
            include_covers=_dingtalk_push_covers(),
        )
        send_markdown(
            webhook_url=webhook,
            secret=_dingtalk_secret(),
            title=title,
            text=text,
        )
    except DingTalkPushError as e:
        return jsonify({"code": e.code, "msg": e.message, "data": None}), e.code
    except Exception as e:
        return jsonify({"code": 502, "msg": f"推送失败: {e}", "data": None}), 502

    item_count = sum(len(s["items"]) for s in sections)
    return jsonify(
        {
            "code": 200,
            "msg": "推送成功",
            "data": {
                "accountCount": len(sections),
                "itemCount": item_count,
                "skipped": skipped,
            },
        }
    ), 200


# 包装函数：在线程中运行异步函数
def run_async_function(type,id,status_queue):
    print(f"🧵 登录线程启动: type={type}, id={id}", flush=True)
    try:
        if str(type).isdigit() and int(type) in ACCOUNT_UNAVAILABLE_REASONS:
            status_queue.put("500")
            return
        match str(type):
            case '1':
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(xiaohongshu_cookie_gen(id, status_queue))
                loop.close()
            case '2':
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(get_tencent_cookie(id,status_queue))
                loop.close()
            case '3':
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(douyin_cookie_gen(id,status_queue))
                loop.close()
            case '4':
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(get_ks_cookie(id,status_queue))
                loop.close()
            case '5':
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(baijiahao_cookie_gen(id, status_queue))
                loop.close()
            case '6':
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(bilibili_cookie_gen(id, status_queue))
                loop.close()
            case '7':
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(toutiao_cookie_gen(id, status_queue))
                loop.close()
            case '8':
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(sohu_cookie_gen(id, status_queue))
                loop.close()
            case '9':
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(zhihu_cookie_gen(id, status_queue))
                loop.close()
            case '10':
                asyncio.run(weibo_cookie_gen(id, status_queue))
            case '11':
                asyncio.run(qiehao_cookie_gen(id, status_queue))
            case kind if kind.isdigit() and int(kind) in ARTICLE_ONLY_ACCOUNT_TYPES:
                account_type = int(kind)
                asyncio.run(article_account_cookie_gen(id, status_queue, ACCOUNT_PLATFORMS[account_type], account_type))
            case _:
                print(f"❌ 不支持的登录平台类型: {type}", flush=True)
                status_queue.put("500")
    except Exception as e:
        print(f"❌ 登录线程异常 type={type}, id={id}: {e}", flush=True)
        import traceback
        traceback.print_exc()
        try:
            status_queue.put("500")
        except Exception:
            pass

# SSE 流生成器函数
def sse_stream(status_queue):
    while True:
        if not status_queue.empty():
            msg = status_queue.get()
            yield f"data: {msg}\n\n"
        else:
            # 避免 CPU 占满
            time.sleep(0.1)

def _refresh_analytics_account(account_id, platform, limit):
    """复用现有作品采集与登录态，同时采集真实账号粉丝资料。"""
    from utils.analytics.collectors.profile import collect_account_profile_sync
    from utils.analytics.service import AnalyticsError
    meta = SUPPORTED_STATS_PLATFORMS.get(platform)
    if not meta:
        raise AnalyticsError("该平台尚未接入作品数据采集", 501)
    with sqlite3.connect(_db_path()) as conn:
        row = conn.execute("SELECT type,filePath FROM user_info WHERE id=?", (account_id,)).fetchone()
    if not row or int(row[0]) != meta["type"]:
        raise AnalyticsError("账号不存在或平台不匹配", 404)
    root = Path(BASE_DIR / "cookiesFile").resolve()
    cookie = (root / row[1]).resolve()
    if not cookie.is_relative_to(root) or not cookie.is_file():
        raise AnalyticsError("账号会话不存在，请先重新登录", 401)
    collector = {"douyin": sync_douyin_content_stats, "kuaishou": sync_kuaishou_content_stats,
                 "xiaohongshu": sync_xiaohongshu_content_stats, "bilibili": sync_bilibili_content_stats}[platform]
    items = collector(cookie, limit=limit)
    try:
        profile = collect_account_profile_sync(cookie, platform)
    except Exception:
        # 粉丝资料依赖额外网页能力，失败不丢弃已经成功采集的作品。
        profile = {"followerCount": None, "evidence": [], "warnings": ["粉丝资料读取失败，作品数据已采集；请检查浏览器和账号页面权限"]}
    return {"items": items, "followerCount": profile.get("followerCount"), "evidence": profile.get("evidence", []),
            "warnings": profile.get("warnings", []), "scope": "partial"}


register_article_routes(app, app_conf)
register_interaction_routes(app, app_conf)
register_analytics_routes(app, _db_path, account_refresher=_refresh_analytics_account)
register_analytics_push_routes(app, _db_path, app_conf)

if __name__ == '__main__':
    # 正常启动即恢复持久化文章队列；模块导入本身不创建线程或写数据库。
    app.extensions['article_service']()
    # 运行器恢复已有显式启用配置，新安装默认不采集也不发送。
    if app.config.get('INTERACTION_WORKER_ENABLED', getattr(app_conf, 'INTERACTION_WORKER_ENABLED', True)):
        app.extensions['interaction_service']().start()
    if app.config.get('ANALYTICS_PUSH_WORKER_ENABLED', getattr(app_conf, 'ANALYTICS_PUSH_WORKER_ENABLED', True)):
        app.extensions['analytics_push_service']().start()
    app.run(host='0.0.0.0' ,port=5409)

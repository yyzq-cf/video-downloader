#!/usr/bin/env python3
"""
ywsj Video Downloader - Web UI for yt-dlp
基于 yt-dlp 的视频下载器，支持 Cloudflare 绕过、多线程下载、实时进度
"""

import os
import re
import json
import uuid
import hashlib
import secrets
import sqlite3
import threading
import subprocess
import time
import mimetypes
from functools import wraps
from flask import Flask, request, jsonify, send_file, render_template, session
from pathlib import Path

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.permanent_session_lifetime = 7 * 24 * 3600  # 7 days

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)
DB_PATH = BASE_DIR / "data" / "users.db"
DB_PATH.parent.mkdir(exist_ok=True)

# 存储下载任务状态
tasks = {}
tasks_lock = threading.Lock()

# === 认证相关 ===
MAX_LOGIN_ATTEMPTS = 5
LOCK_TIME = 300  # 5 minutes
login_attempts = {}  # ip -> {count, lock_until}


def init_db():
    """初始化用户数据库"""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    ''')
    conn.commit()
    # 检查是否有用户，没有则创建默认用户
    c.execute('SELECT COUNT(*) FROM users')
    if c.fetchone()[0] == 0:
        default_user = os.environ.get('AUTH_USERNAME', 'admin')
        default_pass = os.environ.get('AUTH_PASSWORD', 'admin123')
        create_user(default_user, default_pass)
    conn.close()


def create_user(username, password):
    """创建用户"""
    salt = secrets.token_hex(16)
    password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    try:
        c.execute(
            'INSERT INTO users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)',
            (username, password_hash, salt, time.time())
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # 用户已存在
    conn.close()


def verify_user(username, password):
    """验证用户名密码"""
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute('SELECT password_hash, salt FROM users WHERE username = ?', (username,))
    row = c.fetchone()
    conn.close()
    if not row:
        return False
    stored_hash, salt = row
    password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    return password_hash == stored_hash


def change_password(username, old_password, new_password):
    """修改密码"""
    if not verify_user(username, old_password):
        return False
    salt = secrets.token_hex(16)
    password_hash = hashlib.sha256((new_password + salt).encode()).hexdigest()
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute('UPDATE users SET password_hash = ?, salt = ? WHERE username = ?',
              (password_hash, salt, username))
    conn.commit()
    conn.close()
    return True


def change_username(old_username, new_username, password):
    """修改用户名"""
    if not verify_user(old_username, password):
        return False
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    try:
        c.execute('UPDATE users SET username = ? WHERE username = ?', (new_username, old_username))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def get_client_ip():
    """获取客户端 IP"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    return request.remote_addr or 'unknown'


def check_login_lock(ip):
    """检查 IP 是否被锁定"""
    info = login_attempts.get(ip)
    if not info:
        return False
    if info.get('lock_until') and time.time() < info['lock_until']:
        return True
    if info.get('lock_until') and time.time() >= info['lock_until']:
        del login_attempts[ip]
    return False


def record_failed_login(ip):
    """记录失败登录"""
    info = login_attempts.setdefault(ip, {'count': 0, 'lock_until': None})
    info['count'] += 1
    if info['count'] >= MAX_LOGIN_ATTEMPTS:
        info['lock_until'] = time.time() + LOCK_TIME


def clear_login_attempts(ip):
    """清除登录尝试记录"""
    login_attempts.pop(ip, None)


def login_required(f):
    """认证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return jsonify({'error': '未登录', 'auth_required': True}), 401
        return f(*args, **kwargs)
    return decorated_function

# 初始化数据库
init_db()


def sanitize_filename(name):
    """清理文件名中的非法字符"""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip()[:200]


def get_file_size_str(size_bytes):
    """将字节数转为人类可读格式"""
    if size_bytes == 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def parse_ytdlp_progress(line):
    """解析 yt-dlp 的进度输出行"""
    result = {}
    # [download] 12.34% of ~1.23GiB at 1.50MiB/s ETA 03:20 (frag 250/2084)
    m = re.search(
        r'\[download\]\s+([\d.]+)%\s+of\s+~?\s*([\d.]+)(\w+)\s+at\s+([\d.]+)(\w+)/s\s+ETA\s+([\d:]+)(?:\s+\(frag\s+(\d+)/(\d+)\))?',
        line
    )
    if m:
        result['percent'] = float(m.group(1))
        result['total_size'] = f"{m.group(2)}{m.group(3)}"
        result['speed'] = f"{m.group(4)}{m.group(5)}/s"
        result['eta'] = m.group(6)
        if m.group(7):
            result['frag_current'] = int(m.group(7))
            result['frag_total'] = int(m.group(8))
        return result

    # [download] 100% of ~1.23GiB in 05:30 at 4.50MiB/s
    m = re.search(
        r'\[download\]\s+100%\s+of\s+~?\s*([\d.]+)(\w+)\s+in\s+([\d:]+)\s+at\s+([\d.]+)(\w+)/s',
        line
    )
    if m:
        result['percent'] = 100.0
        result['total_size'] = f"{m.group(1)}{m.group(2)}"
        result['speed'] = f"{m.group(4)}{m.group(5)}/s"
        result['eta'] = '00:00'
        result['status'] = 'merging'
        return result

    # [Merger] Merging formats into ...
    if '[Merger]' in line or '[ffmpeg]' in line:
        result['status'] = 'merging'
        result['percent'] = 100.0
        return result

    # [download] Destination: ...
    m = re.search(r'\[download\]\s+Destination:\s+(.+)', line)
    if m:
        result['status'] = 'starting'
        result['filename'] = m.group(1).strip()
        return result

    # [info] Downloading 1 format(s)
    if '[info]' in line:
        result['status'] = 'preparing'
        return result

    return None


def run_download(task_id, url, options):
    """在后台线程中运行 yt-dlp"""
    task = tasks[task_id]
    cmd = [
        'yt-dlp',
        '--extractor-args', 'generic:impersonate',
        '--newline',
        '--progress',
        '--continue',
        '--progress-template', 'P|%(progress._percent_str)s|%(progress._total_bytes_estimate_str)s|%(progress._speed_str)s|%(progress._eta_str)s|%(progress.fragment_index)s|%(progress.fragment_count)s',
        '-o', str(DOWNLOAD_DIR / '%(title)s.%(ext)s'),
    ]

    # 格式选择 — 优先选最佳视频+音频合并，回退到预合并单文件
    fmt = options.get('format', 'best')
    if fmt == 'audio':
        cmd.extend(['-x', '--audio-format', 'mp3', '--audio-quality', '0'])
    elif fmt == '720p':
        cmd.extend(['-f', 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'])
    elif fmt == '1080p':
        cmd.extend(['-f', 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best'])
    else:
        cmd.extend(['-f', 'bestvideo+bestaudio/best'])

    # 并发下载
    concurrent = int(options.get('concurrent', 10))
    cmd.extend(['--concurrent-fragments', str(concurrent)])
    cmd.extend(['--throttled-rate', '100K'])

    cmd.append(url)

    task['status'] = 'downloading'
    task['started_at'] = time.time()

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(DOWNLOAD_DIR),
        )

        task['pid'] = process.pid
        task['process'] = process

        last_update = 0
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue

            # 解析进度模板行: P|  0.1%|   1.84GiB| 300.89KiB/s|91:13:53|1|2084
            if line.startswith('P|'):
                parts = line.split('|')
                if len(parts) >= 7:
                    with tasks_lock:
                        pct_str = parts[1].strip().replace('%', '')
                        try:
                            task['percent'] = float(pct_str)
                        except ValueError:
                            pass
                        task['total_size'] = parts[2].strip() if parts[2] != 'NA' else ''
                        task['speed'] = parts[3].strip() if parts[3] != 'NA' else ''
                        task['eta'] = parts[4].strip() if parts[4] != 'NA' else ''
                        frag_cur = parts[5].strip()
                        frag_total = parts[6].strip()
                        if frag_cur and frag_cur != 'NA':
                            try:
                                task['frag_current'] = int(frag_cur)
                            except ValueError:
                                pass
                        if frag_total and frag_total != 'NA':
                            try:
                                task['frag_total'] = int(frag_total)
                            except ValueError:
                                pass

            # 检测错误
            if line.startswith("ERROR:") or line.startswith("ffmpeg error"):
                with tasks_lock:
                    task["error"] = line.replace("ERROR:", "").replace("ffmpeg error", "").strip()
                    task["status"] = "failed"

            # 检测合并/完成状态
            if '[Merger]' in line or '[ffmpeg]' in line:
                with tasks_lock:
                    task['status'] = 'merging'
                    task['percent'] = 100.0

            # 检测最终文件名
            m = re.search(r'\[(?:Merger|download)\].*?"([^"]+)"', line)
            if m:
                with tasks_lock:
                    task['output_file'] = m.group(1)

            # 检测已完成
            if 'has already been downloaded' in line:
                m = re.search(r'"([^"]+)"', line)
                if m:
                    with tasks_lock:
                        task['status'] = 'completed'
                        task['percent'] = 100.0
                        task['output_file'] = m.group(1)

            # 检测 [download] Destination 行获取文件名
            m2 = re.search(r'\[download\]\s+Destination:\s+(.+)', line)
            if m2:
                with tasks_lock:
                    task['output_file'] = m2.group(1).strip()

            now = time.time()
            if now - last_update > 0.5:
                last_update = now

        process.wait()
        ret = process.returncode

        with tasks_lock:
            if ret == 0:
                task['status'] = 'completed'
                task['percent'] = 100.0
                task['completed_at'] = time.time()

                # 尝试找到输出文件
                if 'output_file' not in task or not task['output_file']:
                    # 查找最近修改的文件
                    files = sorted(DOWNLOAD_DIR.glob('*'), key=lambda f: f.stat().st_mtime, reverse=True)
                    for f in files:
                        if f.is_file() and f.suffix in ['.mp4', '.mkv', '.webm', '.mp3', '.m4a']:
                            task['output_file'] = f.name
                            break
            else:
                task['status'] = 'failed'
                task['error'] = f'yt-dlp 退出码 {ret}'

    except FileNotFoundError:
        with tasks_lock:
            task['status'] = 'failed'
            task['error'] = 'yt-dlp 未安装'
    except Exception as e:
        with tasks_lock:
            task['status'] = 'failed'
            task['error'] = str(e)


@app.route('/')
def index():
    return render_template('index.html')


# === 认证接口 ===
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    ip = get_client_ip()

    if check_login_lock(ip):
        return jsonify({'error': '尝试次数过多，请 5 分钟后再试'}), 429

    if not username or not password:
        return jsonify({'error': '请输入用户名和密码'}), 400

    if verify_user(username, password):
        clear_login_attempts(ip)
        session.permanent = True
        session['username'] = username
        return jsonify({'status': 'ok', 'username': username})
    else:
        record_failed_login(ip)
        remaining = MAX_LOGIN_ATTEMPTS - login_attempts.get(ip, {}).get('count', 0)
        if remaining > 0:
            return jsonify({'error': f'用户名或密码错误，剩余 {remaining} 次尝试'}), 401
        else:
            return jsonify({'error': '尝试次数过多，请 5 分钟后再试'}), 429


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'status': 'ok'})


@app.route('/api/auth/check')
def auth_check():
    if 'username' in session:
        return jsonify({'logged_in': True, 'username': session['username']})
    return jsonify({'logged_in': False}), 401


@app.route('/api/change-password', methods=['POST'])
@login_required
def change_pw():
    data = request.json or {}
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')

    if not old_password or not new_password:
        return jsonify({'error': '请填写完整'}), 400
    if len(new_password) < 6:
        return jsonify({'error': '新密码至少 6 位'}), 400

    if change_password(session['username'], old_password, new_password):
        return jsonify({'status': 'ok'})
    return jsonify({'error': '原密码错误'}), 400


@app.route('/api/change-username', methods=['POST'])
@login_required
def change_un():
    data = request.json or {}
    new_username = data.get('new_username', '').strip()
    password = data.get('password', '')

    if not new_username or not password:
        return jsonify({'error': '请填写完整'}), 400
    if len(new_username) < 3:
        return jsonify({'error': '用户名至少 3 个字符'}), 400

    if change_username(session['username'], new_username, password):
        session['username'] = new_username
        return jsonify({'status': 'ok', 'username': new_username})
    return jsonify({'error': '密码错误或用户名已存在'}), 400


@app.route('/api/download', methods=['POST'])
@login_required
def start_download():
    data = request.json or {}
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': '请输入 URL'}), 400

    if not re.match(r'https?://', url):
        return jsonify({'error': 'URL 格式错误'}), 400

    task_id = str(uuid.uuid4())[:8]
    with tasks_lock:
        tasks[task_id] = {
            'id': task_id,
            'url': url,
            'status': 'queued',
            'percent': 0,
            'speed': '',
            'eta': '',
            'total_size': '',
            'frag_current': 0,
            'frag_total': 0,
            'output_file': '',
            'error': '',
            'file_size': '',
            'started_at': None,
            'completed_at': None,
            'format': data.get('format', 'best'),
            'concurrent': data.get('concurrent', 10),
        }

    thread = threading.Thread(target=run_download, args=(task_id, url, data), daemon=True)
    thread.start()

    return jsonify({'task_id': task_id, 'status': 'queued'})


@app.route('/api/status/<task_id>')
@login_required
def get_status(task_id):
    with tasks_lock:
        task = tasks.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404

    # 获取文件大小
    result = dict(task)
    if result.get('output_file'):
        filepath = DOWNLOAD_DIR / result['output_file']
        if filepath.exists():
            result['file_size'] = get_file_size_str(filepath.stat().st_size)
            result['file_size_bytes'] = filepath.stat().st_size
        # basename
        result['output_file'] = os.path.basename(result['output_file'])

    # 计算耗时
    if result.get('started_at'):
        end = result.get('completed_at') or time.time()
        elapsed = int(end - result['started_at'])
        m, s = divmod(elapsed, 60)
        result['elapsed'] = f"{m:02d}:{s:02d}"

    # 清理不可序列化的字段
    result.pop('process', None)
    result.pop('pid', None)

    return jsonify(result)


@app.route('/api/tasks')
@login_required
def list_tasks():
    with tasks_lock:
        all_tasks = []
        for t in tasks.values():
            result = dict(t)
            result.pop('process', None)
            result.pop('pid', None)
            if result.get('output_file'):
                result['output_file'] = os.path.basename(result['output_file'])
                filepath = DOWNLOAD_DIR / result['output_file']
                if filepath.exists():
                    result['file_size'] = get_file_size_str(filepath.stat().st_size)
            all_tasks.append(result)
    # 按时间倒序
    all_tasks.sort(key=lambda x: x.get('started_at') or 0, reverse=True)
    return jsonify(all_tasks)


@app.route('/api/cancel/<task_id>', methods=['POST'])
@login_required
def cancel_download(task_id):
    with tasks_lock:
        task = tasks.get(task_id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404

    if 'process' in task and task['process']:
        task['process'].terminate()
        task['status'] = 'cancelled'
        return jsonify({'status': 'cancelled'})
    return jsonify({'error': '无法取消任务'}), 400


@app.route('/api/delete/<task_id>', methods=['POST'])
@login_required
def delete_task(task_id):
    with tasks_lock:
        task = tasks.get(task_id)
        if not task:
            return jsonify({'error': '任务不存在'}), 404

        # 如果有文件，删除文件
        if task.get('output_file'):
            filepath = DOWNLOAD_DIR / task['output_file']
            if filepath.exists():
                filepath.unlink()

        del tasks[task_id]
    return jsonify({'status': 'deleted'})


@app.route('/api/files')
@login_required
def list_files():
    files = []
    for f in sorted(DOWNLOAD_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.is_file() and not f.name.startswith('.'):
            stat = f.stat()
            files.append({
                'name': f.name,
                'size': get_file_size_str(stat.st_size),
                'size_bytes': stat.st_size,
                'modified': stat.st_mtime,
            })
    return jsonify(files)


@app.route('/api/file/<path:filename>')
@login_required
def download_file(filename):
    filepath = DOWNLOAD_DIR / filename
    if not filepath.exists():
        return jsonify({'error': '文件不存在'}), 404

    mime_type, _ = mimetypes.guess_type(str(filepath))
    return send_file(str(filepath), as_attachment=True, download_name=filename)


@app.route('/api/file/<path:filename>/stream')
@login_required
def stream_file(filename):
    filepath = DOWNLOAD_DIR / filename
    if not filepath.exists():
        return jsonify({'error': '文件不存在'}), 404

    mime_type, _ = mimetypes.guess_type(str(filepath))
    return send_file(str(filepath), mimetype=mime_type)


@app.route('/api/file/<path:filename>', methods=['DELETE'])
@login_required
def delete_file(filename):
    filepath = DOWNLOAD_DIR / filename
    if not filepath.exists():
        return jsonify({'error': '文件不存在'}), 404
    filepath.unlink()
    return jsonify({'status': 'deleted'})




@app.route('/api/clear-cache', methods=['POST'])
@login_required
def clear_cache():
    """清除下载缓存: 删除所有 .part/.ytdl 临时文件, 清除已取消/失败的任务记录"""
    deleted_files = []
    freed_bytes = 0

    # 删除临时文件 (.part, .part-Frag*, .ytdl)
    for f in DOWNLOAD_DIR.iterdir():
        if f.is_file() and (f.name.endswith('.part') or f.name.endswith('.ytdl') or '.part-Frag' in f.name):
            size = f.stat().st_size
            freed_bytes += size
            deleted_files.append(f.name)
            f.unlink()

    # 清除已取消/失败的任务记录 (保留 downloading/completed/queued/merging)
    removed_tasks = []
    with tasks_lock:
        to_remove = []
        for tid, t in tasks.items():
            if t.get('status') in ('cancelled', 'failed'):
                to_remove.append(tid)
                removed_tasks.append(tid)
        for tid in to_remove:
            del tasks[tid]

    return jsonify({
        'status': 'ok',
        'deleted_files': deleted_files,
        'freed_space': get_file_size_str(freed_bytes),
        'removed_tasks': removed_tasks,
        'files_count': len(deleted_files),
        'tasks_count': len(removed_tasks),
    })


@app.route('/api/clear-tasks', methods=['POST'])
@login_required
def clear_tasks():
    """清除所有已完成/取消/失败的任务记录 (不删文件)"""
    removed = []
    with tasks_lock:
        to_remove = []
        for tid, t in tasks.items():
            if t.get('status') in ('completed', 'cancelled', 'failed'):
                to_remove.append(tid)
                removed.append(tid)
        for tid in to_remove:
            del tasks[tid]
    return jsonify({'status': 'ok', 'removed_tasks': removed, 'count': len(removed)})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5200))
    print(f"🚀 ywsj Video Downloader 启动于 http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)

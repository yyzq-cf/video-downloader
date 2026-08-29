#!/usr/bin/env python3
"""
ywsj Video Downloader - Web UI for yt-dlp
基于 yt-dlp 的视频下载器，支持.Cloudflare 绕过、多线程下载、实时进度
"""

import os
import re
import json
import uuid
import threading
import subprocess
import time
import mimetypes
from flask import Flask, request, jsonify, send_file, render_template
from pathlib import Path

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# 存储下载任务状态
tasks = {}
tasks_lock = threading.Lock()


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
        '--progress-template', 'P|%(progress._percent_str)s|%(progress._total_bytes_estimate_str)s|%(progress._speed_str)s|%(progress._eta_str)s|%(progress.fragment_index)s|%(progress.fragment_count)s',
        '-o', str(DOWNLOAD_DIR / '%(title)s.%(ext)s'),
    ]

    # 格式选择
    fmt = options.get('format', 'best')
    if fmt == 'audio':
        cmd.extend(['-x', '--audio-format', 'mp3', '--audio-quality', '0'])
    elif fmt == '720p':
        cmd.extend(['-f', 'best[height<=720]/best'])
    elif fmt == '1080p':
        cmd.extend(['-f', 'best[height<=1080]/best'])
    else:
        cmd.extend(['-f', 'best'])

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


@app.route('/api/download', methods=['POST'])
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
def download_file(filename):
    filepath = DOWNLOAD_DIR / filename
    if not filepath.exists():
        return jsonify({'error': '文件不存在'}), 404

    mime_type, _ = mimetypes.guess_type(str(filepath))
    return send_file(str(filepath), as_attachment=True, download_name=filename)


@app.route('/api/file/<path:filename>/stream')
def stream_file(filename):
    filepath = DOWNLOAD_DIR / filename
    if not filepath.exists():
        return jsonify({'error': '文件不存在'}), 404

    mime_type, _ = mimetypes.guess_type(str(filepath))
    return send_file(str(filepath), mimetype=mime_type)


@app.route('/api/file/<path:filename>', methods=['DELETE'])
def delete_file(filename):
    filepath = DOWNLOAD_DIR / filename
    if not filepath.exists():
        return jsonify({'error': '文件不存在'}), 404
    filepath.unlink()
    return jsonify({'status': 'deleted'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5200))
    print(f"🚀 ywsj Video Downloader 启动于 http://0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)

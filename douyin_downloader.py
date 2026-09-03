"""
抖音视频下载器
通过抖音 web API 获取无水印视频地址, 绕过 yt-dlp 的 cookie 限制
参考: stream-bridge 项目的 ttwid cookie 方案
"""
import re
import json
import os
import subprocess
import logging

logger = logging.getLogger(__name__)

# 抖音 web cookie (ttwid 匿名标识, 无需登录, 与 stream-bridge 共用)
DOUYIN_COOKIE = 'ttwid=1%7C2iDIYVmjzMcpZ20fcaFde0VghXAA3NaNXE_SLR68IyE%7C1761045455%7Cab35197d5cfb21df6cbb2fa7ef1c9262206b062c315b9d04da746d0b37dfbc7d'

DOUYIN_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' \
             '(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'


def is_douyin_url(url):
    """判断是否为抖音视频链接"""
    return 'douyin.com' in url and ('/video/' in url or '/note/' in url)


def extract_aweme_id(url):
    """从URL中提取抖音视频ID"""
    # https://www.douyin.com/video/7574659948187279013
    m = re.search(r'douyin\.com/(?:video|note)/(\d+)', url)
    if m:
        return m.group(1)
    # https://www.iesdouyin.com/share/video/7574659948187279013/
    m = re.search(r'iesdouyin\.com/share/video/(\d+)', url)
    if m:
        return m.group(1)
    # 纯数字
    if url.strip().isdigit():
        return url.strip()
    # v.douyin.com 短链接需要重定向解析, 这里返回None让调用方处理
    if 'v.douyin.com' in url:
        return None
    return None


def get_video_info(aweme_id):
    """
    通过抖音 web API 获取视频详情
    返回: {'ok': bool, 'title': str, 'author': str, 'duration': float,
           'width': int, 'height': int, 'size': int, 'download_url': str,
           'cover': str, 'error': str}
    """
    try:
        from curl_cffi import requests
    except ImportError:
        return {'ok': False, 'error': 'curl_cffi 未安装'}

    api_url = 'https://www.douyin.com/aweme/v1/web/aweme/detail/'
    params = {
        'aweme_id': aweme_id,
        'aid': '6383',
        'cookie_enabled': 'true',
        'platform': 'PC',
        'downlink': '10',
    }

    for attempt in range(3):
        try:
            r = requests.get(
                api_url,
                params=params,
                headers={
                    'User-Agent': DOUYIN_UA,
                    'Cookie': DOUYIN_COOKIE,
                    'Referer': f'https://www.douyin.com/video/{aweme_id}',
                },
                impersonate='chrome',
                timeout=15,
            )

            if not r.text or len(r.text) < 50:
                raise Exception(f'API返回内容过少({len(r.text)}字节)')

            data = json.loads(r.text)

            if data.get('status_code') != 0:
                status_msg = data.get('status_msg', '')
                # 1101 = 视频不存在/已删除
                if data.get('status_code') == 1101:
                    return {'ok': False, 'error': '视频不存在或已删除'}
                raise Exception(f'抖音API错误: status_code={data.get("status_code")} msg={status_msg}')

            detail = data.get('aweme_detail')
            if not detail:
                return {'ok': False, 'error': '未返回视频详情'}

            video = detail.get('video', {})
            play_addr = video.get('play_addr', {})
            url_list = play_addr.get('url_list', [])

            if not url_list:
                return {'ok': False, 'error': '未找到视频下载地址'}

            # 选第一个URL (一般是最优的)
            download_url = url_list[0]

            # 如果URL是 http, 升级为 https
            if download_url.startswith('http://'):
                download_url = 'https://' + download_url[7:]

            # 获取封面
            cover_url = ''
            cover_obj = video.get('cover') or video.get('origin_cover') or {}
            if cover_obj.get('url_list'):
                cover_url = cover_obj['url_list'][0]

            # 标题: desc 为空时用 author + aweme_id
            desc = detail.get('desc', '').strip()
            author = detail.get('author', {}).get('nickname', '抖音视频')

            info = {
                'ok': True,
                'title': desc or f'{author}_{aweme_id}',
                'author': author,
                'duration': video.get('duration', 0) / 1000.0,
                'width': play_addr.get('width', video.get('width', 0)),
                'height': play_addr.get('height', video.get('height', 0)),
                'size': play_addr.get('data_size', 0),
                'download_url': download_url,
                'cover': cover_url,
                'aweme_id': aweme_id,
                'error': None,
            }
            logger.info(f"抖音视频获取成功: [{author}] {desc[:50] if desc else '(无标题)'} "
                        f"{info['width']}x{info['height']} {info['size']/1024/1024:.1f}MB")
            return info

        except json.JSONDecodeError:
            logger.warning(f"抖音API返回非JSON, 第{attempt+1}次重试...")
            if attempt < 2:
                import time
                time.sleep(2)
                continue
            return {'ok': False, 'error': '抖音API返回非JSON'}
        except Exception as e:
            logger.warning(f"抖音API请求失败, 第{attempt+1}次: {e}")
            if attempt < 2:
                import time
                time.sleep(2)
                continue
            return {'ok': False, 'error': str(e)}

    return {'ok': False, 'error': '多次请求失败'}


def download_douyin_video(url, output_dir, filename=None):
    """
    下载抖音视频到指定目录
    返回: {'ok': bool, 'filepath': str, 'filename': str, 'info': dict, 'error': str}
    """
    from pathlib import Path
    from curl_cffi import requests

    aweme_id = extract_aweme_id(url)
    if not aweme_id:
        return {'ok': False, 'error': f'无法提取抖音视频ID: {url}'}

    # 获取视频信息
    info = get_video_info(aweme_id)
    if not info['ok']:
        return {'ok': False, 'error': info['error']}

    # 构建文件名
    if not filename:
        # 清理标题中的非法字符
        title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', info['title']).strip()[:150]
        filename = f'{title}.mp4'

    output_path = Path(output_dir) / filename

    # 用 curl/curl_cffi 下载 (带 Referer 防止403)
    try:
        r = requests.get(
            info['download_url'],
            headers={
                'User-Agent': DOUYIN_UA,
                'Referer': 'https://www.douyin.com/',
                'Cookie': DOUYIN_COOKIE,
            },
            impersonate='chrome',
            timeout=300,
            stream=True,
        )

        if r.status_code != 200:
            return {'ok': False, 'error': f'下载失败: HTTP {r.status_code}'}

        total = int(r.headers.get('content-length', 0))
        downloaded = 0

        with open(output_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

        if downloaded == 0:
            return {'ok': False, 'error': '下载文件为空'}

        result = {
            'ok': True,
            'filepath': str(output_path),
            'filename': filename,
            'info': info,
            'error': None,
        }
        logger.info(f"抖音视频下载完成: {filename} ({downloaded/1024/1024:.1f}MB)")
        return result

    except Exception as e:
        # 清理不完整文件
        if output_path.exists():
            output_path.unlink()
        return {'ok': False, 'error': f'下载异常: {e}'}


def resolve_short_url(url):
    """
    解析 v.douyin.com 短链接, 获取实际视频URL
    返回解析后的完整URL或原URL
    """
    if 'v.douyin.com' not in url:
        return url
    try:
        from curl_cffi import requests
        r = requests.get(url, impersonate='chrome', timeout=10, allow_redirects=True)
        return r.url
    except:
        return url

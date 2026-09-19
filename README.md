# 🎬 ywsj Video Downloader

基于 yt-dlp 的 Web 视频下载器，支持 TLS 指纹伪装绕过基础 Cloudflare 拦截、多线程下载、实时进度显示、抖音无水印、明暗主题切换。

## ✨ 功能特性

### 下载能力
- 🔗 **粘贴链接即下载** — 支持 yt-dlp 所有兼容站点（YouTube、B站、各类视频站等）
- 🛡️ **TLS 指纹伪装** — 内置 `curl_cffi` 模拟 Chrome 指纹，可绕过 Cloudflare Bot Fight Mode 等 TLS 层 403 拦截（不支持 JS 质询/Turnstile）
- ⚡ **多线程并发** — 支持 5-20 线程同时下载分片，速度拉满
- 🎵 **分离流自动合并** — 智能选择 `bestvideo+bestaudio` 方案，支持 m3u8/HLS 等只有分离流的源
- 🎬 **画质选择** — 最高画质 / 1080p / 720p / 仅音频(MP3)
- 🎵 **抖音无水印下载** — 专用 API 获取无水印视频，不走 yt-dlp，无需登录

### 下载与保存
- 🖥️ **存服务器模式** — 视频下载到服务器硬盘，完成后自动触发浏览器下载，也可在「已下载文件」中在线播放或手动保存
- 📥 **直传本地接口** — 后端提供流式直传接口（`/api/stream-download`），服务器零磁盘占用；当前前端尚未暴露入口

### 界面交互
- 📊 **实时进度百分比** — 进度条内嵌白色百分比文字 + 右侧数字，保留 1 位小数实时更新
- 📦 **详细下载信息** — 文件大小、下载速度、剩余时间、分片进度、已耗时
- 🎬 **在线播放** — 内置视频播放器，下载完直接预览
- 📁 **文件管理** — 下载列表、文件大小、删除、下载到本地
- 🎨 **明暗主题切换** — 默认亮色主题，一键切换暗色，`localStorage` 记住选择
- ❌ **错误信息** — yt-dlp 报错直接显示在任务列表，不再只显示退出码
- 🧹 **缓存清理** — 一键清除临时文件和失效任务记录
- 🐳 **Docker 部署** — 一键 `docker-compose up -d` 启动

## 🚀 快速开始

### Docker 部署（推荐）

```bash
git clone https://github.com/yyzq-cf/video-downloader.git
cd video-downloader
docker-compose up -d
```

访问 `http://localhost:5200`

默认账号 `admin` / `admin123`

### 本地运行

```bash
# 安装系统依赖
sudo apt install ffmpeg

# 安装 Python 依赖
pip install -r requirements.txt

# 启动
python app.py
```

访问 `http://localhost:5200`

## 📖 使用说明

1. 在输入框粘贴视频链接
2. 选择画质（最高画质 / 1080p / 720p / 仅音频）
3. 选择并发线程数（默认 10）
4. 点击「下载」按钮
5. 在「下载队列」查看实时进度（进度条显示百分比）
6. 下载完成后自动触发浏览器下载；也可在「已下载文件」中在线播放或手动保存

## 🛠️ 技术栈

| 组件 | 说明 |
|---|---|
| **Flask** | Web 后端框架 |
| **gunicorn** | 生产级 WSGI 服务器（单 worker 多线程） |
| **yt-dlp** | 视频下载核心引擎 |
| **curl_cffi** | TLS 指纹伪装（绕过基础 Cloudflare 拦截）/ 抖音API请求 |
| **douyin_downloader** | 抖音无水印视频下载模块 |
| **ffmpeg** | 视频合并/转码 |
| **原生 JS** | 前端，无框架依赖 |

## ⚙️ 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `PORT` | 5200 | Web 服务端口 |
| `AUTH_USERNAME` | admin | 登录用户名 |
| `AUTH_PASSWORD` | admin123 | 登录密码 |
| `SECRET_KEY` | 随机生成 | Flask Session 密钥 |

## 📂 目录结构

```
video-downloader/
├── app.py                 # Flask 后端
├── douyin_downloader.py   # 抖音无水印下载模块
├── templates/
│   └── index.html         # Web UI（明暗主题）
├── downloads/             # 下载文件目录
├── data/                  # 用户数据库
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .dockerignore
└── README.md
```

## 📋 版本与更新日志

本项目采用**日期版本号**格式：`vYYYYMMDD-N`（北京时间 UTC+8）

- 每次 push 到 master 分支自动生成新版本号（同一天多次 push 自动递增 N）
- CI 构建时将版本号注入 Docker 镜像环境变量，Web 界面显示该版本
- GitHub Release 自动记录更新日志（基于 commit messages）
- Docker Hub 同步推送对应版本 tag + `latest`
- **容器重启不会改变版本号**，只有代码更新才会

查看所有版本：[Releases](https://github.com/yyzq-cf/video-downloader/releases)

### 历史更新

- **抖音无水印下载** — 专用 API 获取无水印视频，自动检测抖音链接，预览视频信息
- **主题切换** — 默认亮色主题，支持暗色切换，`localStorage` 记住选择
- **流式直传接口** — 后端新增 `/api/stream-download` 流式直传接口，yt-dlp 边下边传不落盘（当前前端尚未暴露入口）
- **自动下载** — 存服务器模式完成后自动触发浏览器下载
- **进度百分比** — 进度条内嵌百分比文字，实时显示下载进度
- **分离流修复** — 修复 m3u8 等只有 video-only+audio-only 的源下载失败问题
- **进度不显示修复** — 修复 gunicorn 多 worker 导致 tasks 字典不共享的进度显示问题
- **错误信息** — 捕获 yt-dlp ERROR 行，前端显示具体错误原因

## License

MIT

# 🎬 ywsj Video Downloader

基于 yt-dlp 的 Web 视频下载器，支持自动绕过 Cloudflare 验证、多线程下载、实时进度显示、流式直传本地、明暗主题切换。

## ✨ 功能特性

### 下载能力
- 🔗 **粘贴链接即下载** — 支持 yt-dlp 所有兼容站点（YouTube、B站、各类视频站等）
- 🛡️ **自动绕过 Cloudflare** — 内置 `curl_cffi` 指纹模拟，突破 403 拦截
- ⚡ **多线程并发** — 支持 5-20 线程同时下载分片，速度拉满
- 🎵 **分离流自动合并** — 智能选择 `bestvideo+bestaudio` 方案，支持 m3u8/HLS 等只有分离流的源
- 🎬 **画质选择** — 最高画质 / 1080p / 720p / 仅音频(MP3)
- 🎵 **抖音无水印下载** — 专用 API 获取无水印视频，不走 yt-dlp，无需登录

### 下载模式
- 🖥️ **存服务器模式** — 视频下载到服务器硬盘，可在线播放、手动保存
  - ✅ **完成后自动下载** — 勾选后下载完成自动触发浏览器下载，无需手动点保存
- 📥 **直传本地模式** — yt-dlp 边下边传给浏览器，服务器零磁盘占用，浏览器直接弹下载框

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
4. 选择下载模式：
   - **🖥 存服务器** — 下载到服务器，可在线播放（勾选「完成后自动下载」可自动传到本地）
   - **📥 直传本地** — 直接流式传输到浏览器，服务器不存文件
5. 点击「下载」按钮
6. 在「下载队列」查看实时进度（进度条显示百分比）
7. 存服务器模式下载完成后可在「已下载文件」中播放或保存

## 🛠️ 技术栈

| 组件 | 说明 |
|---|---|
| **Flask** | Web 后端框架 |
| **gunicorn** | 生产级 WSGI 服务器（单 worker 多线程） |
| **yt-dlp** | 视频下载核心引擎 |
| **curl_cffi** | Cloudflare 指纹绕过 / 抖音API请求 |
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

## 📋 更新日志

- **抖音无水印下载** — 专用 API 获取无水印视频，自动检测抖音链接，预览视频信息
- **主题切换** — 默认亮色主题，支持暗色切换，`localStorage` 记住选择
- **流式直传** — 新增直传本地模式，yt-dlp 边下边传，服务器零磁盘占用
- **自动下载** — 存服务器模式完成后自动触发浏览器下载
- **进度百分比** — 进度条内嵌百分比文字，实时显示下载进度
- **分离流修复** — 修复 m3u8 等只有 video-only+audio-only 的源下载失败问题
- **进度不显示修复** — 修复 gunicorn 多 worker 导致 tasks 字典不共享的进度显示问题
- **错误信息** — 捕获 yt-dlp ERROR 行，前端显示具体错误原因

## License

MIT

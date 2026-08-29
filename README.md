# 🎬 ywsj Video Downloader

基于 yt-dlp 的 Web 视频下载器，支持自动绕过 Cloudflare 验证、多线程下载、实时进度显示。

## ✨ 功能特性

- 🔗 **粘贴链接即下载** — 支持 yt-dlp 所有兼容站点（YouTube、B站、各类视频站等）
- 🛡️ **自动绕过 Cloudflare** — 内置 `curl_cffi` 指纹模拟，突破 403 拦截
- ⚡ **多线程并发** — 支持 5-20 线程同时下载分片，速度拉满
- 📊 **实时进度** — 进度条、速度、ETA、分片数实时更新
- 🎬 **在线播放** — 内置视频播放器，下载完直接预览
- 📁 **文件管理** — 下载列表、文件大小、删除、下载到本地
- 🎨 **暗色主题** — 现代化 UI，支持手机端
- 🐳 **Docker 部署** — 一键 `docker-compose up -d` 启动

## 🚀 快速开始

### Docker 部署（推荐）

```bash
git clone https://github.com/yyzq-cf/video-downloader.git
cd video-downloader
docker-compose up -d
```

访问 `http://localhost:5200`

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
5. 在「下载队列」查看实时进度
6. 下载完成后可在「已下载文件」中播放或下载

## 🛠️ 技术栈

| 组件 | 说明 |
|---|---|
| **Flask** | Web 后端框架 |
| **yt-dlp** | 视频下载核心引擎 |
| **curl_cffi** | Cloudflare 指纹绕过 |
| **ffmpeg** | 视频合并/转码 |
| **原生 JS** | 前端，无框架依赖 |

## ⚙️ 配置

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `PORT` | 5200 | Web 服务端口 |

## 📂 目录结构

```
video-downloader/
├── app.py                 # Flask 后端
├── templates/
│   └── index.html         # Web UI
├── downloads/             # 下载文件目录
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## License

MIT

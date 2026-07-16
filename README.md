# 🎬 ffmepgGui - 视频处理工

[![Python](https://img.shields.io/badge/Python-3.7+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows-blue.svg)](https://www.microsoft.com/windows)

一个简单易用的本地视频处理工具，**专为国内视频爱好者设计**，无需任何命令行操作！

> 🇨🇳 作者是一名中国初中生，这个项目是为没有编程经验的视频爱好者准备的。

## ✨ 特性

- 🚀 **自动GPU加速** - 自动识别 NVIDIA/AMD/Intel 显卡，启用硬件编码
- ⏹ **支持随时取消** - 处理过程中可以随时中断
- 📦 **多种处理方式** - 压缩、转码、缩放、拼接、调整帧率、提取音频
- 📁 **批量处理** - 支持同时处理多个文件
- 🖥 **纯本地运行** - 无需网络，保护隐私
- 🎯 **无需命令行** - 全图形化界面，简单易用

## 📋 功能列表

| 功能 | 说明 |
|------|------|
| 📦 压缩 (H265) | 使用 H265 编码高效压缩视频 |
| 🔄 转 H264/H265 | 转换视频编码格式 |
| 📄 转 MP4/MOV/WebM | 转换视频容器格式 |
| 🎵 提取音频 | 从视频中提取音频 (M4A) |
| 📐 缩放 720p/1080p | 调整视频分辨率 |
| 🔗 拼接视频 | 按顺序合并多个视频文件 |
| ⏱ 调整帧率 | 改变视频帧率 |

## 🖼 截图

![主界面](screenshots/main.png)

## 📦 下载与使用

### 方式一：直接下载 EXE（推荐）

1. 从 [Releases](https://github.com/kalitang666/ffmepgGui/releases) 下载最新版本的 `ffGui.exe`
2. 下载 FFmpeg：
   - 访问 https://www.gyan.dev/ffmpeg/builds/
   - 下载 `ffmpeg-release-essentials.zip`
   - 解压后，将 `bin/ffmpeg.exe` 放到和 `ffGui.exe` 同一目录
3. 双击 `ffGui.exe` 运行

### 方式二：运行 Python 源码

```bash
# 1. 克隆仓库
git clone https://github.com/kalitang666/ffmepgGui.git
cd ffmepgGui

# 2. 安装依赖（仅需 Python 3.7+）
# Tkinter 通常已随 Python 安装

# 3. 下载 FFmpeg 并放到同目录

# 4. 运行
python server.py

🔧 系统要求
Windows 7/10/11

建议 4GB 以上内存

如需 GPU 加速，需要安装对应显卡驱动

🤝 贡献
欢迎提交 Issue 和 Pull Request！

如果你觉得这个项目对你有帮助，请给个 ⭐ Star 支持一下！

📄 许可证
本项目采用 MIT 许可证

📧 联系方式
作者: kalitang666

GitHub: @kalitang666

⭐ 如果这个项目对你有帮助，请给个 Star！
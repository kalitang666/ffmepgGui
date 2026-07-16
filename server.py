# video_processor_gui.py (带中断功能)
"""
视频处理工具 v3.0 (GUI版)
功能：视频转码/压缩/拼接/调整帧率
特性：自动检测GPU（NVIDIA/Intel/AMD），硬件加速失败时自动回退CPU模式
支持：实时中断/取消处理
"""

import os
import sys
import subprocess
import json
import uuid
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime
from pathlib import Path

# ============ FFmpeg 路径配置 ============
def get_base_dir():
    """获取程序所在目录（兼容exe打包和源码运行）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()

def get_ffmpeg_path():
    """获取 ffmpeg 路径，优先使用程序同目录下的版本"""
    ffmpeg_exe = os.path.join(BASE_DIR, 'ffmpeg.exe')
    if os.path.exists(ffmpeg_exe):
        return ffmpeg_exe
    ffmpeg_bin = os.path.join(BASE_DIR, 'bin', 'ffmpeg.exe')
    if os.path.exists(ffmpeg_bin):
        return ffmpeg_bin
    ffmpeg_dir = os.path.join(BASE_DIR, 'ffmpeg', 'bin', 'ffmpeg.exe')
    if os.path.exists(ffmpeg_dir):
        return ffmpeg_dir
    return 'ffmpeg'

def get_ffprobe_path():
    """获取 ffprobe 路径"""
    ffprobe_exe = os.path.join(BASE_DIR, 'ffprobe.exe')
    if os.path.exists(ffprobe_exe):
        return ffprobe_exe
    ffprobe_bin = os.path.join(BASE_DIR, 'bin', 'ffprobe.exe')
    if os.path.exists(ffprobe_bin):
        return ffprobe_bin
    ffprobe_dir = os.path.join(BASE_DIR, 'ffmpeg', 'bin', 'ffprobe.exe')
    if os.path.exists(ffprobe_dir):
        return ffprobe_dir
    return 'ffprobe'

FFMPEG_PATH = get_ffmpeg_path()
FFPROBE_PATH = get_ffprobe_path()

# ============ GPU 检测 ============
def detect_gpu():
    """检测系统中的显卡类型"""
    result = {
        'type': 'unknown',
        'name': '未知',
        'has_amf': False,
        'has_nvenc': False,
        'has_qsv': False,
        'has_cuda': False,
        'has_vaapi': False,
        'has_d3d11va': False,
        'ffmpeg_hwaccels': []
    }
    
    try:
        cmd = [FFMPEG_PATH, '-hwaccels']
        output = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if output.returncode == 0:
            hwaccels = output.stdout.lower()
            result['ffmpeg_hwaccels'] = hwaccels
            if 'cuda' in hwaccels or 'cuvid' in hwaccels:
                result['has_cuda'] = True
            if 'nvenc' in hwaccels:
                result['has_nvenc'] = True
            if 'amf' in hwaccels:
                result['has_amf'] = True
            if 'qsv' in hwaccels:
                result['has_qsv'] = True
            if 'vaapi' in hwaccels:
                result['has_vaapi'] = True
            if 'd3d11va' in hwaccels:
                result['has_d3d11va'] = True
    except Exception as e:
        print(f"⚠️ FFmpeg 硬件检测失败: {e}")
    
    if sys.platform == 'win32':
        try:
            ps_cmd = '''
            Get-WmiObject -Class Win32_VideoController | 
            Where-Object { $_.Name -notlike "*Remote*" -and $_.Name -notlike "*Virtual*" } | 
            Select-Object -ExpandProperty Name
            '''
            result_pw = subprocess.run(
                ['powershell', '-Command', ps_cmd],
                capture_output=True, text=True, timeout=10
            )
            if result_pw.returncode == 0:
                gpu_names = result_pw.stdout.strip().split('\n')
                for name in gpu_names:
                    name_lower = name.lower()
                    if 'nvidia' in name_lower:
                        result['type'] = 'nvidia'
                        result['name'] = name.strip()
                        break
                    elif 'amd' in name_lower or 'radeon' in name_lower:
                        result['type'] = 'amd'
                        result['name'] = name.strip()
                        break
                    elif 'intel' in name_lower or 'iris' in name_lower or 'uhd' in name_lower:
                        result['type'] = 'intel'
                        result['name'] = name.strip()
                        break
        except Exception as e:
            print(f"⚠️ GPU 检测失败: {e}")
    
    if result['type'] == 'nvidia' and result['has_cuda']:
        result['has_nvenc'] = True
    if result['type'] == 'amd' and result['has_amf']:
        result['has_amf'] = True
    if result['type'] == 'intel' and result['has_qsv']:
        result['has_qsv'] = True
    
    return result

GPU_INFO = detect_gpu()

# ============ 全局中断标志 ============
STOP_PROCESSING = False

def set_stop_flag():
    """设置停止标志"""
    global STOP_PROCESSING
    STOP_PROCESSING = True

def reset_stop_flag():
    """重置停止标志"""
    global STOP_PROCESSING
    STOP_PROCESSING = False

def is_stopped():
    """检查是否被中断"""
    return STOP_PROCESSING

# ============ 根据 GPU 选择编码参数 ============
def get_best_hw_params(task_type='compress'):
    """根据当前 GPU 返回最优的硬件加速参数"""
    result = {
        'hwaccel': None,
        'encoder': 'libx264',
        'use_hw': False,
        'gpu_type': GPU_INFO['type']
    }
    
    is_hevc = task_type in ['compress', 'to_h265']
    is_h264 = task_type in ['to_h264', 'resize_720p', 'resize_1080p']
    is_copy = task_type in ['to_mp4', 'to_mov']
    
    if is_copy:
        result['encoder'] = 'copy'
        result['use_hw'] = False
        return result
    
    if sys.platform == 'win32':
        if GPU_INFO['type'] == 'nvidia' and GPU_INFO['has_nvenc']:
            result['hwaccel'] = 'cuda'
            result['encoder'] = 'h264_nvenc' if is_h264 else 'hevc_nvenc'
            result['use_hw'] = True
        elif GPU_INFO['type'] == 'amd' and GPU_INFO['has_amf']:
            result['hwaccel'] = 'd3d11va'
            result['encoder'] = 'h264_amf' if is_h264 else 'hevc_amf'
            result['use_hw'] = True
        elif GPU_INFO['type'] == 'intel' and GPU_INFO['has_qsv']:
            result['hwaccel'] = 'qsv'
            result['encoder'] = 'h264_qsv' if is_h264 else 'hevc_qsv'
            result['use_hw'] = True
        elif GPU_INFO['has_d3d11va']:
            result['hwaccel'] = 'd3d11va'
            result['encoder'] = 'h264_amf' if is_h264 else 'hevc_amf'
            result['use_hw'] = True
        else:
            result['use_hw'] = False
            result['encoder'] = 'libx265' if is_hevc else 'libx264'
    elif sys.platform.startswith('linux'):
        if GPU_INFO['has_vaapi']:
            result['hwaccel'] = 'vaapi'
            result['encoder'] = 'h264_vaapi' if is_h264 else 'hevc_vaapi'
            result['use_hw'] = True
        else:
            result['use_hw'] = False
            result['encoder'] = 'libx265' if is_hevc else 'libx264'
    elif sys.platform == 'darwin':
        result['hwaccel'] = 'videotoolbox'
        result['encoder'] = 'h264_videotoolbox' if is_h264 else 'hevc_videotoolbox'
        result['use_hw'] = True
    else:
        result['use_hw'] = False
        result['encoder'] = 'libx265' if is_hevc else 'libx264'
    
    return result

# ============ 辅助函数 ============
ALLOWED_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.webm', '.m4v', '.mpg', '.mpeg'}

def allowed_file(filename):
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS

def get_file_size_mb(filepath):
    try:
        size = os.path.getsize(filepath)
        return round(size / (1024 * 1024), 2)
    except:
        return 0

def get_video_info(filepath):
    try:
        cmd = [
            FFPROBE_PATH, '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', filepath
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            info = {}
            if 'format' in data and 'duration' in data['format']:
                info['duration'] = float(data['format']['duration'])
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video':
                    if 'r_frame_rate' in stream:
                        num, den = stream['r_frame_rate'].split('/')
                        if float(den) > 0:
                            info['fps'] = round(float(num) / float(den), 2)
                    if 'codec_name' in stream:
                        info['codec'] = stream['codec_name']
                    if 'width' in stream and 'height' in stream:
                        info['width'] = stream['width']
                        info['height'] = stream['height']
                    break
            return info
    except Exception as e:
        print(f"获取视频信息失败: {e}")
    return {}

def generate_output_filename(original_name, task_type, suffix=None):
    name, ext = os.path.splitext(original_name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    task_labels = {
        'compress': '_compressed',
        'to_h264': '_h264',
        'to_h265': '_h265',
        'to_mp4': '_mp4',
        'to_mov': '_mov',
        'to_webm': '_webm',
        'extract_audio': '_audio',
        'resize_720p': '_720p',
        'resize_1080p': '_1080p',
        'concat': '_merged',
        'change_fps': '_fps'
    }
    label = task_labels.get(task_type, '_processed')
    if suffix:
        label += f"_{suffix}"
    return f"{name}{label}_{timestamp}.mp4"

# ============ FFmpeg 处理函数（支持中断） ============
def process_video(input_path, output_path, task_type, log_callback=None, **kwargs):
    """调用 FFmpeg 处理视频，支持中断"""
    global STOP_PROCESSING
    
    if not os.path.exists(input_path):
        return False, f"输入文件不存在: {input_path}", None
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    fps = kwargs.get('fps', None)
    concat_files = kwargs.get('concat_files', [])
    
    hw_params = get_best_hw_params(task_type)
    encoder = hw_params['encoder']
    hwaccel = hw_params['hwaccel']
    use_hw = hw_params['use_hw']
    gpu_type = hw_params['gpu_type']
    
    log_msg = f"🔧 GPU: {gpu_type}, 硬件加速: {use_hw}, 编码器: {encoder}"
    if log_callback:
        log_callback(log_msg)
    else:
        print(log_msg)
    
    cmd = None
    
    # 拼接任务
    if task_type == 'concat' and concat_files:
        concat_list_path = os.path.join(os.path.dirname(output_path), 'concat_list.txt')
        with open(concat_list_path, 'w', encoding='utf-8') as f:
            for file_path in concat_files:
                abs_path = os.path.abspath(file_path).replace('\\', '/')
                f.write(f"file '{abs_path}'\n")
        
        if use_hw and hwaccel:
            cmd = [
                FFMPEG_PATH, '-hwaccel', hwaccel,
                '-f', 'concat', '-safe', '0', '-i', concat_list_path,
                '-c:v', encoder, '-preset', 'quality' if gpu_type != 'nvidia' else 'p4',
                '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart',
                output_path, '-y'
            ]
        else:
            cmd = [
                FFMPEG_PATH,
                '-f', 'concat', '-safe', '0', '-i', concat_list_path,
                '-c:v', encoder, '-crf', '23',
                '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart',
                output_path, '-y'
            ]
        try:
            os.remove(concat_list_path)
        except:
            pass
    
    # 调整帧率
    elif task_type == 'change_fps' and fps:
        if use_hw and hwaccel:
            cmd = [
                FFMPEG_PATH, '-hwaccel', hwaccel, '-i', input_path,
                '-vf', f'fps={fps}',
                '-c:v', encoder, '-preset', 'quality' if gpu_type != 'nvidia' else 'p4',
                '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart',
                output_path, '-y'
            ]
        else:
            cmd = [
                FFMPEG_PATH, '-i', input_path,
                '-vf', f'fps={fps}',
                '-c:v', encoder, '-crf', '23',
                '-c:a', 'aac', '-b:a', '128k',
                '-movflags', '+faststart',
                output_path, '-y'
            ]
    
    # 标准任务
    else:
        if use_hw and hwaccel:
            base_cmd = [FFMPEG_PATH, '-hwaccel', hwaccel, '-i', input_path]
        else:
            base_cmd = [FFMPEG_PATH, '-i', input_path]
        
        if task_type == 'compress':
            if use_hw:
                cmd = base_cmd + ['-c:v', encoder, '-preset', 'quality' if gpu_type != 'nvidia' else 'p4', '-crf', '23']
            else:
                cmd = base_cmd + ['-c:v', 'libx265', '-crf', '23']
        
        elif task_type == 'to_h264':
            if use_hw:
                cmd = base_cmd + ['-c:v', encoder, '-preset', 'quality' if gpu_type != 'nvidia' else 'p4']
            else:
                cmd = base_cmd + ['-c:v', 'libx264', '-crf', '23']
        
        elif task_type == 'to_h265':
            if use_hw:
                cmd = base_cmd + ['-c:v', encoder, '-preset', 'quality' if gpu_type != 'nvidia' else 'p4']
            else:
                cmd = base_cmd + ['-c:v', 'libx265', '-crf', '23']
        
        elif task_type == 'to_mp4':
            cmd = [FFMPEG_PATH, '-i', input_path, '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart']
        
        elif task_type == 'to_mov':
            output_path = output_path.replace('.mp4', '.mov')
            cmd = [FFMPEG_PATH, '-i', input_path, '-c:v', 'copy', '-c:a', 'copy']
        
        elif task_type == 'to_webm':
            output_path = output_path.replace('.mp4', '.webm')
            cmd = [FFMPEG_PATH, '-i', input_path, '-c:v', 'libvpx-vp9', '-crf', '30', '-b:v', '0', '-c:a', 'libopus']
        
        elif task_type == 'extract_audio':
            output_path = output_path.replace('.mp4', '.m4a')
            cmd = [FFMPEG_PATH, '-i', input_path, '-vn', '-c:a', 'aac', '-b:a', '192k']
        
        elif task_type == 'resize_720p':
            vf = 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2'
            if use_hw and hwaccel:
                cmd = base_cmd + ['-vf', vf, '-c:v', encoder, '-preset', 'quality' if gpu_type != 'nvidia' else 'p4']
            else:
                cmd = base_cmd + ['-vf', vf, '-c:v', 'libx264', '-crf', '23']
        
        elif task_type == 'resize_1080p':
            vf = 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2'
            if use_hw and hwaccel:
                cmd = base_cmd + ['-vf', vf, '-c:v', encoder, '-preset', 'quality' if gpu_type != 'nvidia' else 'p4']
            else:
                cmd = base_cmd + ['-vf', vf, '-c:v', 'libx264', '-crf', '23']
        
        else:
            cmd = base_cmd + ['-c:v', 'copy']
        
        if cmd and task_type not in ['to_mov', 'to_webm', 'extract_audio']:
            cmd += ['-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', output_path, '-y']
        elif cmd and task_type == 'to_mov':
            cmd += [output_path, '-y']
        elif cmd and task_type == 'to_webm':
            cmd += [output_path, '-y']
        elif cmd and task_type == 'extract_audio':
            cmd += [output_path, '-y']
    
    if cmd is None:
        return False, f"不支持的任务类型: {task_type}", None
    
    try:
        log_msg = f"执行命令: {' '.join(cmd)}"
        if log_callback:
            log_callback(log_msg)
        else:
            print(log_msg)
        
        # 使用 subprocess.Popen 以便能够终止进程
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        
        # 轮询检查是否被中断
        while process.poll() is None:
            if STOP_PROCESSING:
                # 中断处理
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                
                # 删除未完成的输出文件
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except:
                        pass
                
                return False, "处理已取消", None
            # 每0.5秒检查一次
            threading.Event().wait(0.5)
        
        # 获取输出
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr or stdout or "未知错误"
            if use_hw and 'hardware' in error_msg.lower():
                log_msg = "⚠️ 硬件加速失败，尝试回退CPU模式..."
                if log_callback:
                    log_callback(log_msg)
                # 重置停止标志再尝试CPU模式
                if STOP_PROCESSING:
                    return False, "处理已取消", None
                return process_video_cpu_fallback(input_path, output_path, task_type, log_callback, **kwargs)
            return False, f"FFmpeg处理失败: {error_msg[:200]}", None
        
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            return False, "输出文件未生成或为空", None
        
        return True, "处理成功", output_path
        
    except subprocess.TimeoutExpired:
        return False, "处理超时（超过1小时）", None
    except FileNotFoundError:
        return False, f"FFmpeg未找到，请将 ffmpeg.exe 放在程序同目录或添加到系统PATH", None
    except Exception as e:
        return False, f"处理异常: {str(e)}", None

def process_video_cpu_fallback(input_path, output_path, task_type, log_callback=None, **kwargs):
    """CPU回退模式，支持中断"""
    global STOP_PROCESSING
    
    log_msg = "🔄 使用CPU软件编码模式..."
    if log_callback:
        log_callback(log_msg)
    
    fps = kwargs.get('fps', None)
    
    if task_type == 'compress':
        cmd = [FFMPEG_PATH, '-i', input_path, '-c:v', 'libx265', '-crf', '23', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', output_path, '-y']
    elif task_type == 'to_h264':
        cmd = [FFMPEG_PATH, '-i', input_path, '-c:v', 'libx264', '-crf', '23', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', output_path, '-y']
    elif task_type == 'to_h265':
        cmd = [FFMPEG_PATH, '-i', input_path, '-c:v', 'libx265', '-crf', '23', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', output_path, '-y']
    elif task_type == 'change_fps' and fps:
        cmd = [FFMPEG_PATH, '-i', input_path, '-vf', f'fps={fps}', '-c:v', 'libx264', '-crf', '23', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', output_path, '-y']
    elif task_type == 'resize_720p':
        cmd = [FFMPEG_PATH, '-i', input_path, '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2', '-c:v', 'libx264', '-crf', '23', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', output_path, '-y']
    elif task_type == 'resize_1080p':
        cmd = [FFMPEG_PATH, '-i', input_path, '-vf', 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2', '-c:v', 'libx264', '-crf', '23', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', output_path, '-y']
    else:
        cmd = [FFMPEG_PATH, '-i', input_path, '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', output_path, '-y']
    
    try:
        log_msg = f"执行CPU模式命令: {' '.join(cmd)}"
        if log_callback:
            log_callback(log_msg)
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        
        while process.poll() is None:
            if STOP_PROCESSING:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except:
                        pass
                return False, "处理已取消", None
            threading.Event().wait(0.5)
        
        stdout, stderr = process.communicate()
        
        if process.returncode != 0:
            return False, f"CPU模式失败: {stderr[:200]}", None
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            return False, "输出文件未生成", None
        return True, "处理成功(CPU模式)", output_path
    except Exception as e:
        return False, f"CPU模式异常: {str(e)}", None


# ============ GUI 主程序 ============
class VideoProcessorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🎬 视频处理工具 v3.0")
        self.root.geometry("850x780")
        self.root.minsize(800, 680)
        
        # 颜色主题
        self.colors = {
            'bg': '#f0f2f5',
            'card': '#ffffff',
            'primary': '#4a90d9',
            'success': '#28a745',
            'danger': '#dc3545',
            'warning': '#ffc107',
            'text': '#1a1a2e',
            'text_secondary': '#6c757d',
            'border': '#dee2e6'
        }
        
        self.root.configure(bg=self.colors['bg'])
        
        # 数据
        self.selected_files = []
        self.concat_files = []
        self.output_dir = os.path.expanduser("~")
        self.is_processing = False
        self.current_process = None
        self.processing_thread = None
        
        # 初始化界面
        self.setup_ui()
        self.update_gpu_info()
        self.load_ffmpeg_check()
        
    def setup_ui(self):
        """构建UI"""
        main_frame = tk.Frame(self.root, bg=self.colors['bg'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)
        
        # 标题
        title_frame = tk.Frame(main_frame, bg=self.colors['bg'])
        title_frame.pack(fill=tk.X, pady=(0, 15))
        
        title_label = tk.Label(
            title_frame,
            text="🎬 视频处理工具 v3.0",
            font=('Segoe UI', 20, 'bold'),
            bg=self.colors['bg'],
            fg=self.colors['text']
        )
        title_label.pack(side=tk.LEFT)
        
        self.gpu_label = tk.Label(
            title_frame,
            text="检测中...",
            font=('Segoe UI', 11),
            bg=self.colors['bg'],
            fg=self.colors['text_secondary']
        )
        self.gpu_label.pack(side=tk.RIGHT)
        
        # ---- 文件选择区域 ----
        file_frame = tk.LabelFrame(
            main_frame,
            text=" 📁 选择文件 ",
            font=('Segoe UI', 11, 'bold'),
            bg=self.colors['card'],
            fg=self.colors['text'],
            relief=tk.RIDGE,
            bd=2
        )
        file_frame.pack(fill=tk.X, pady=(0, 15))
        
        file_inner = tk.Frame(file_frame, bg=self.colors['card'])
        file_inner.pack(fill=tk.X, padx=15, pady=12)
        
        btn_frame = tk.Frame(file_inner, bg=self.colors['card'])
        btn_frame.pack(fill=tk.X)
        
        self.select_btn = tk.Button(
            btn_frame,
            text="📤 选择视频文件",
            font=('Segoe UI', 10),
            bg=self.colors['primary'],
            fg='white',
            padx=15,
            pady=6,
            relief=tk.RAISED,
            cursor='hand2',
            command=self.select_files
        )
        self.select_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.clear_btn = tk.Button(
            btn_frame,
            text="🗑 清空列表",
            font=('Segoe UI', 10),
            bg=self.colors['text_secondary'],
            fg='white',
            padx=15,
            pady=6,
            relief=tk.RAISED,
            cursor='hand2',
            command=self.clear_files
        )
        self.clear_btn.pack(side=tk.LEFT)
        
        self.output_dir_label = tk.Label(
            btn_frame,
            text=f"输出目录: {self.output_dir}",
            font=('Segoe UI', 9),
            bg=self.colors['card'],
            fg=self.colors['text_secondary']
        )
        self.output_dir_label.pack(side=tk.RIGHT)
        
        self.output_btn = tk.Button(
            btn_frame,
            text="📂 输出目录",
            font=('Segoe UI', 9),
            bg=self.colors['primary'],
            fg='white',
            padx=10,
            pady=4,
            relief=tk.RAISED,
            cursor='hand2',
            command=self.select_output_dir
        )
        self.output_btn.pack(side=tk.RIGHT, padx=(0, 10))
        
        # 文件列表
        list_frame = tk.Frame(file_inner, bg=self.colors['card'])
        list_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.file_listbox = tk.Listbox(
            list_frame,
            height=4,
            font=('Segoe UI', 9),
            bg='#f8f9fa',
            fg=self.colors['text'],
            selectmode=tk.EXTENDED,
            relief=tk.SUNKEN,
            bd=1
        )
        self.file_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.config(yscrollcommand=scrollbar.set)
        
        self.file_count_label = tk.Label(
            file_inner,
            text="已选择 0 个文件",
            font=('Segoe UI', 9),
            bg=self.colors['card'],
            fg=self.colors['text_secondary']
        )
        self.file_count_label.pack(anchor=tk.W, pady=(5, 0))
        
        # ---- 任务类型选择 ----
        task_frame = tk.LabelFrame(
            main_frame,
            text=" 📌 选择处理方式 ",
            font=('Segoe UI', 11, 'bold'),
            bg=self.colors['card'],
            fg=self.colors['text'],
            relief=tk.RIDGE,
            bd=2
        )
        task_frame.pack(fill=tk.X, pady=(0, 15))
        
        task_inner = tk.Frame(task_frame, bg=self.colors['card'])
        task_inner.pack(fill=tk.X, padx=15, pady=12)
        
        self.task_var = tk.StringVar(value='compress')
        task_options = [
            ('压缩 (H265)', 'compress'),
            ('转 H264', 'to_h264'),
            ('转 H265', 'to_h265'),
            ('转 MP4', 'to_mp4'),
            ('转 MOV', 'to_mov'),
            ('转 WebM', 'to_webm'),
            ('提取音频', 'extract_audio'),
            ('缩放 720p', 'resize_720p'),
            ('缩放 1080p', 'resize_1080p'),
            ('拼接视频', 'concat'),
            ('调整帧率', 'change_fps')
        ]
        
        row, col = 0, 0
        for text, value in task_options:
            rb = tk.Radiobutton(
                task_inner,
                text=text,
                variable=self.task_var,
                value=value,
                font=('Segoe UI', 9),
                bg=self.colors['card'],
                fg=self.colors['text'],
                selectcolor='#e8f0fe',
                activebackground=self.colors['card'],
                command=self.on_task_changed
            )
            rb.grid(row=row, column=col, sticky='w', padx=5, pady=3)
            col += 1
            if col >= 4:
                col = 0
                row += 1
        
        # ---- 拼接文件列表 ----
        self.concat_frame = tk.LabelFrame(
            main_frame,
            text=" 🔗 拼接文件列表（按顺序） ",
            font=('Segoe UI', 10, 'bold'),
            bg=self.colors['card'],
            fg=self.colors['text'],
            relief=tk.RIDGE,
            bd=2
        )
        self.concat_frame.pack(fill=tk.X, pady=(0, 15))
        self.concat_frame.pack_forget()
        
        concat_inner = tk.Frame(self.concat_frame, bg=self.colors['card'])
        concat_inner.pack(fill=tk.X, padx=15, pady=10)
        
        self.concat_listbox = tk.Listbox(
            concat_inner,
            height=3,
            font=('Segoe UI', 9),
            bg='#f8f9fa',
            fg=self.colors['text'],
            relief=tk.SUNKEN,
            bd=1
        )
        self.concat_listbox.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        concat_scroll = tk.Scrollbar(concat_inner, orient=tk.VERTICAL, command=self.concat_listbox.yview)
        concat_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.concat_listbox.config(yscrollcommand=concat_scroll.set)
        
        concat_btn_frame = tk.Frame(concat_inner, bg=self.colors['card'])
        concat_btn_frame.pack(fill=tk.X, pady=(8, 0))
        
        self.concat_up_btn = tk.Button(
            concat_btn_frame,
            text="⬆ 上移",
            font=('Segoe UI', 9),
            bg=self.colors['primary'],
            fg='white',
            padx=10,
            pady=3,
            relief=tk.RAISED,
            cursor='hand2',
            command=self.move_concat_up
        )
        self.concat_up_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.concat_down_btn = tk.Button(
            concat_btn_frame,
            text="⬇ 下移",
            font=('Segoe UI', 9),
            bg=self.colors['primary'],
            fg='white',
            padx=10,
            pady=3,
            relief=tk.RAISED,
            cursor='hand2',
            command=self.move_concat_down
        )
        self.concat_down_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        self.concat_remove_btn = tk.Button(
            concat_btn_frame,
            text="✕ 移除选中",
            font=('Segoe UI', 9),
            bg=self.colors['danger'],
            fg='white',
            padx=10,
            pady=3,
            relief=tk.RAISED,
            cursor='hand2',
            command=self.remove_concat_selected
        )
        self.concat_remove_btn.pack(side=tk.LEFT)
        
        # ---- 帧率设置 ----
        self.fps_frame = tk.Frame(main_frame, bg=self.colors['card'], relief=tk.RIDGE, bd=2)
        self.fps_frame.pack(fill=tk.X, pady=(0, 15))
        self.fps_frame.pack_forget()
        
        fps_inner = tk.Frame(self.fps_frame, bg=self.colors['card'])
        fps_inner.pack(fill=tk.X, padx=15, pady=10)
        
        tk.Label(
            fps_inner,
            text="🎯 目标帧率 (FPS):",
            font=('Segoe UI', 10),
            bg=self.colors['card'],
            fg=self.colors['text']
        ).pack(side=tk.LEFT)
        
        self.fps_entry = tk.Entry(
            fps_inner,
            width=8,
            font=('Segoe UI', 10),
            justify='center',
            relief=tk.SUNKEN,
            bd=1
        )
        self.fps_entry.pack(side=tk.LEFT, padx=(10, 10))
        self.fps_entry.insert(0, "30")
        
        tk.Label(
            fps_inner,
            text="常见值: 24(电影) / 30(电视) / 60(高帧率)",
            font=('Segoe UI', 9),
            bg=self.colors['card'],
            fg=self.colors['text_secondary']
        ).pack(side=tk.LEFT)
        
        self.fps_info_label = tk.Label(
            fps_inner,
            text="",
            font=('Segoe UI', 9),
            bg=self.colors['card'],
            fg=self.colors['text_secondary']
        )
        self.fps_info_label.pack(side=tk.RIGHT)
        
        # ---- 按钮区域（处理 + 取消） ----
        btn_main_frame = tk.Frame(main_frame, bg=self.colors['bg'])
        btn_main_frame.pack(fill=tk.X, pady=(0, 10))
        
        button_row = tk.Frame(btn_main_frame, bg=self.colors['bg'])
        button_row.pack(fill=tk.X)
        
        self.process_btn = tk.Button(
            button_row,
            text="🚀 开始处理",
            font=('Segoe UI', 13, 'bold'),
            bg=self.colors['success'],
            fg='white',
            padx=30,
            pady=10,
            relief=tk.RAISED,
            cursor='hand2',
            command=self.start_processing
        )
        self.process_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        self.cancel_btn = tk.Button(
            button_row,
            text="⏹ 取消处理",
            font=('Segoe UI', 13, 'bold'),
            bg=self.colors['danger'],
            fg='white',
            padx=30,
            pady=10,
            relief=tk.RAISED,
            cursor='hand2',
            command=self.cancel_processing,
            state=tk.DISABLED
        )
        self.cancel_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        
        # 进度条
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            main_frame,
            variable=self.progress_var,
            maximum=100,
            mode='determinate'
        )
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))
        self.progress_bar.pack_forget()
        
        # ---- 日志区域 ----
        log_frame = tk.LabelFrame(
            main_frame,
            text=" 📋 处理日志 ",
            font=('Segoe UI', 10, 'bold'),
            bg=self.colors['card'],
            fg=self.colors['text'],
            relief=tk.RIDGE,
            bd=2
        )
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        log_inner = tk.Frame(log_frame, bg=self.colors['card'])
        log_inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.log_text = scrolledtext.ScrolledText(
            log_inner,
            height=10,
            font=('Consolas', 9),
            bg='#1a1a2e',
            fg='#00ff88',
            insertbackground='white',
            relief=tk.SUNKEN,
            bd=1
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log_text.config(state=tk.DISABLED)
        
        clear_log_btn = tk.Button(
            log_frame,
            text="🗑 清空日志",
            font=('Segoe UI', 9),
            bg=self.colors['text_secondary'],
            fg='white',
            padx=10,
            pady=3,
            relief=tk.RAISED,
            cursor='hand2',
            command=self.clear_log
        )
        clear_log_btn.pack(anchor=tk.E, padx=10, pady=(0, 8))
        
        # ---- 底部状态栏 ----
        self.status_bar = tk.Label(
            main_frame,
            text="就绪",
            font=('Segoe UI', 9),
            bg=self.colors['bg'],
            fg=self.colors['text_secondary'],
            anchor=tk.W
        )
        self.status_bar.pack(fill=tk.X, pady=(8, 0))
    
    def update_gpu_info(self):
        """更新GPU信息显示"""
        if GPU_INFO['type'] != 'unknown':
            gpu_text = f"🖥 {GPU_INFO['name']} ({GPU_INFO['type'].upper()})"
            if GPU_INFO['has_nvenc'] or GPU_INFO['has_amf'] or GPU_INFO['has_qsv']:
                gpu_text += " ✅ 硬件加速"
        else:
            gpu_text = "🖥 CPU模式 (未检测到GPU)"
        self.gpu_label.config(text=gpu_text)
        
        if not os.path.exists(FFMPEG_PATH):
            self.log(f"⚠️ 警告: 未找到 ffmpeg.exe，请确保它和本程序在同一目录")
    
    def load_ffmpeg_check(self):
        """检查FFmpeg是否可用"""
        try:
            result = subprocess.run([FFMPEG_PATH, '-version'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                version_line = result.stdout.split('\n')[0]
                self.log(f"✅ {version_line}")
            else:
                self.log("⚠️ FFmpeg 不可用，请检查安装")
        except:
            self.log("⚠️ FFmpeg 不可用，请确保 ffmpeg.exe 在本程序同目录")
    
    def log(self, message):
        """向日志区域添加消息"""
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()
    
    def clear_log(self):
        """清空日志"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def set_status(self, text, is_error=False):
        """设置状态栏"""
        self.status_bar.config(text=text, fg=self.colors['danger'] if is_error else self.colors['text_secondary'])
    
    def select_files(self):
        """选择视频文件"""
        files = filedialog.askopenfilenames(
            title="选择视频文件",
            filetypes=[
                ("视频文件", "*.mp4 *.avi *.mov *.mkv *.flv *.wmv *.webm *.m4v *.mpg *.mpeg"),
                ("所有文件", "*.*")
            ]
        )
        if files:
            for f in files:
                if f not in self.selected_files:
                    self.selected_files.append(f)
            self.update_file_list()
    
    def select_output_dir(self):
        """选择输出目录"""
        dir_path = filedialog.askdirectory(title="选择输出目录", initialdir=self.output_dir)
        if dir_path:
            self.output_dir = dir_path
            self.output_dir_label.config(text=f"输出目录: {self.output_dir}")
    
    def clear_files(self):
        """清空文件列表"""
        self.selected_files = []
        self.concat_files = []
        self.update_file_list()
        self.update_concat_list()
    
    def update_file_list(self):
        """更新文件列表显示"""
        self.file_listbox.delete(0, tk.END)
        for f in self.selected_files:
            name = os.path.basename(f)
            size = get_file_size_mb(f)
            self.file_listbox.insert(tk.END, f"{name} ({size} MB)")
        self.file_count_label.config(text=f"已选择 {len(self.selected_files)} 个文件")
        
        if self.task_var.get() == 'concat':
            self.concat_files = self.selected_files.copy()
            self.update_concat_list()
    
    def update_concat_list(self):
        """更新拼接列表显示"""
        self.concat_listbox.delete(0, tk.END)
        for i, f in enumerate(self.concat_files):
            name = os.path.basename(f)
            size = get_file_size_mb(f)
            self.concat_listbox.insert(tk.END, f"{i+1}. {name} ({size} MB)")
    
    def move_concat_up(self):
        """拼接列表上移"""
        selection = self.concat_listbox.curselection()
        if selection and selection[0] > 0:
            idx = selection[0]
            self.concat_files[idx], self.concat_files[idx-1] = self.concat_files[idx-1], self.concat_files[idx]
            self.update_concat_list()
            self.concat_listbox.selection_set(idx-1)
    
    def move_concat_down(self):
        """拼接列表下移"""
        selection = self.concat_listbox.curselection()
        if selection and selection[0] < len(self.concat_files) - 1:
            idx = selection[0]
            self.concat_files[idx], self.concat_files[idx+1] = self.concat_files[idx+1], self.concat_files[idx]
            self.update_concat_list()
            self.concat_listbox.selection_set(idx+1)
    
    def remove_concat_selected(self):
        """从拼接列表中移除选中"""
        selection = self.concat_listbox.curselection()
        if selection:
            idx = selection[0]
            del self.concat_files[idx]
            self.selected_files = self.concat_files.copy()
            self.update_concat_list()
            self.update_file_list()
    
    def on_task_changed(self):
        """任务类型切换"""
        task = self.task_var.get()
        if task == 'concat':
            self.concat_frame.pack(fill=tk.X, pady=(0, 15), before=self.fps_frame)
            self.fps_frame.pack_forget()
            self.concat_files = self.selected_files.copy()
            self.update_concat_list()
            self.log("🔗 拼接模式: 请按顺序添加视频文件")
        elif task == 'change_fps':
            self.concat_frame.pack_forget()
            self.fps_frame.pack(fill=tk.X, pady=(0, 15))
            if self.selected_files and len(self.selected_files) == 1:
                self.show_video_info(self.selected_files[0])
        else:
            self.concat_frame.pack_forget()
            self.fps_frame.pack_forget()
    
    def show_video_info(self, filepath):
        """显示视频信息"""
        info = get_video_info(filepath)
        if info and info.get('fps'):
            self.fps_info_label.config(text=f"📊 原帧率: {info['fps']} FPS")
            self.fps_entry.delete(0, tk.END)
            self.fps_entry.insert(0, str(info['fps']))
        else:
            self.fps_info_label.config(text="")
    
    def cancel_processing(self):
        """取消处理"""
        if not self.is_processing:
            return
        
        self.log("⏹ 正在取消处理...")
        set_stop_flag()
        self.cancel_btn.config(text="⏳ 正在取消...", state=tk.DISABLED)
        self.set_status("正在取消...")
    
    def start_processing(self):
        """开始处理"""
        if self.is_processing:
            return
        
        task = self.task_var.get()
        
        if task == 'concat':
            if len(self.concat_files) < 2:
                messagebox.showerror("错误", "拼接模式至少需要选择2个视频文件")
                return
            input_files = self.concat_files
        else:
            if len(self.selected_files) == 0:
                messagebox.showerror("错误", "请选择至少1个视频文件")
                return
            input_files = self.selected_files
        
        if not os.path.exists(FFMPEG_PATH):
            messagebox.showerror("错误", f"未找到 ffmpeg.exe，请将它放在:\n{os.path.dirname(FFMPEG_PATH)}")
            return
        
        if not os.path.exists(self.output_dir):
            try:
                os.makedirs(self.output_dir)
            except:
                messagebox.showerror("错误", f"无法创建输出目录: {self.output_dir}")
                return
        
        if task == 'change_fps':
            try:
                fps = float(self.fps_entry.get())
                if fps <= 0:
                    raise ValueError
            except:
                messagebox.showerror("错误", "请输入有效的帧率 (大于0)")
                return
        
        # 重置停止标志
        reset_stop_flag()
        
        self.is_processing = True
        self.process_btn.config(text="⏳ 处理中...", bg=self.colors['warning'], state=tk.DISABLED)
        self.cancel_btn.config(text="⏹ 取消处理", state=tk.NORMAL)
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))
        self.progress_var.set(0)
        self.set_status("处理中...")
        
        self.processing_thread = threading.Thread(
            target=self.process_files,
            args=(task, input_files),
            daemon=True
        )
        self.processing_thread.start()
    
    def process_files(self, task, input_files):
        """在后台线程中处理文件"""
        try:
            if task == 'concat':
                self.log("🔗 开始拼接视频...")
                self.log(f"📁 文件数: {len(input_files)}")
                
                output_name = f"merged_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
                output_path = os.path.join(self.output_dir, output_name)
                
                self.root.after(0, lambda: self.progress_var.set(20))
                
                success, msg, result_path = process_video(
                    input_files[0], output_path, 'concat',
                    log_callback=self.log,
                    concat_files=input_files
                )
                
                self.root.after(0, lambda: self.progress_var.set(90))
                
                if success:
                    size = get_file_size_mb(result_path)
                    self.log(f"✅ 拼接完成! 输出: {os.path.basename(result_path)} ({size} MB)")
                    self.root.after(0, lambda: self.progress_var.set(100))
                    self.root.after(0, lambda: self.show_result(result_path))
                else:
                    if msg == "处理已取消":
                        self.log("⏹ 处理已取消")
                        self.root.after(0, lambda: self.set_status("已取消"))
                    else:
                        self.log(f"❌ 拼接失败: {msg}")
                        self.root.after(0, lambda: self.set_status("处理失败", True))
            
            elif task == 'change_fps':
                fps = float(self.fps_entry.get())
                info = get_video_info(input_files[0])
                orig_fps = info.get('fps', '未知')
                self.log(f"⏱ 调整帧率: {orig_fps} FPS → {fps} FPS")
                
                output_name = generate_output_filename(os.path.basename(input_files[0]), task, f"{fps}fps")
                output_path = os.path.join(self.output_dir, output_name)
                
                self.root.after(0, lambda: self.progress_var.set(20))
                
                success, msg, result_path = process_video(
                    input_files[0], output_path, 'change_fps',
                    log_callback=self.log,
                    fps=fps
                )
                
                self.root.after(0, lambda: self.progress_var.set(90))
                
                if success:
                    size = get_file_size_mb(result_path)
                    self.log(f"✅ 处理完成! 输出: {os.path.basename(result_path)} ({size} MB)")
                    self.root.after(0, lambda: self.progress_var.set(100))
                    self.root.after(0, lambda: self.show_result(result_path))
                else:
                    if msg == "处理已取消":
                        self.log("⏹ 处理已取消")
                        self.root.after(0, lambda: self.set_status("已取消"))
                    else:
                        self.log(f"❌ 处理失败: {msg}")
                        self.root.after(0, lambda: self.set_status("处理失败", True))
            
            elif task == 'extract_audio':
                for i, filepath in enumerate(input_files):
                    if is_stopped():
                        self.log("⏹ 处理已取消")
                        self.root.after(0, lambda: self.set_status("已取消"))
                        break
                    
                    self.log(f"🎵 提取音频 ({i+1}/{len(input_files)}): {os.path.basename(filepath)}")
                    
                    base_name = os.path.splitext(os.path.basename(filepath))[0]
                    output_name = f"{base_name}_audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.m4a"
                    output_path = os.path.join(self.output_dir, output_name)
                    
                    self.root.after(0, lambda: self.progress_var.set(20 + (i * 40 / len(input_files))))
                    
                    success, msg, result_path = process_video(
                        filepath, output_path, 'extract_audio',
                        log_callback=self.log
                    )
                    
                    if success:
                        size = get_file_size_mb(result_path)
                        self.log(f"✅ 音频提取完成: {os.path.basename(result_path)} ({size} MB)")
                    else:
                        if msg == "处理已取消":
                            self.log("⏹ 处理已取消")
                            self.root.after(0, lambda: self.set_status("已取消"))
                            break
                        self.log(f"❌ 音频提取失败: {msg}")
                
                self.root.after(0, lambda: self.progress_var.set(100))
                if not is_stopped():
                    self.root.after(0, lambda: self.set_status("全部处理完成"))
            
            else:
                for i, filepath in enumerate(input_files):
                    if is_stopped():
                        self.log("⏹ 处理已取消")
                        self.root.after(0, lambda: self.set_status("已取消"))
                        break
                    
                    self.log(f"📹 处理 ({i+1}/{len(input_files)}): {os.path.basename(filepath)}")
                    
                    suffix = None
                    if task == 'change_fps':
                        suffix = f"{fps}fps"
                    
                    output_name = generate_output_filename(os.path.basename(filepath), task, suffix)
                    output_path = os.path.join(self.output_dir, output_name)
                    
                    self.root.after(0, lambda: self.progress_var.set(10 + (i * 80 / len(input_files))))
                    
                    success, msg, result_path = process_video(
                        filepath, output_path, task,
                        log_callback=self.log
                    )
                    
                    if success:
                        size = get_file_size_mb(result_path)
                        self.log(f"✅ 处理完成: {os.path.basename(result_path)} ({size} MB)")
                        self.root.after(0, lambda p=result_path: self.show_result(p))
                    else:
                        if msg == "处理已取消":
                            self.log("⏹ 处理已取消")
                            self.root.after(0, lambda: self.set_status("已取消"))
                            break
                        self.log(f"❌ 处理失败: {msg}")
                        if len(input_files) == 1:
                            self.root.after(0, lambda: self.set_status("处理失败", True))
                
                self.root.after(0, lambda: self.progress_var.set(100))
                if not is_stopped():
                    self.root.after(0, lambda: self.set_status("全部处理完成"))
        
        except Exception as e:
            self.log(f"❌ 异常: {str(e)}")
            self.root.after(0, lambda: self.set_status(f"错误: {str(e)}", True))
        
        finally:
            self.root.after(0, lambda: self.reset_ui())
    
    def show_result(self, filepath):
        """显示处理结果并询问是否打开文件夹"""
        result = messagebox.askyesno(
            "处理完成",
            f"✅ 视频处理完成!\n\n文件: {os.path.basename(filepath)}\n大小: {get_file_size_mb(filepath)} MB\n\n是否打开所在文件夹？"
        )
        if result:
            os.startfile(os.path.dirname(filepath))
    
    def reset_ui(self):
        """恢复UI状态"""
        self.is_processing = False
        reset_stop_flag()
        self.process_btn.config(text="🚀 开始处理", bg=self.colors['success'], state=tk.NORMAL)
        self.cancel_btn.config(text="⏹ 取消处理", state=tk.DISABLED)
        self.progress_bar.pack_forget()
        self.progress_var.set(0)
        if not self.status_bar.cget('text').startswith("已取消"):
            self.set_status("就绪")


def main():
    root = tk.Tk()
    try:
        root.iconbitmap(os.path.join(BASE_DIR, 'icon.ico'))
    except:
        pass
    
    app = VideoProcessorGUI(root)
    
    if not os.path.exists(FFMPEG_PATH):
        messagebox.showwarning(
            "FFmpeg 未找到",
            f"未找到 ffmpeg.exe!\n\n请将 ffmpeg.exe 放在以下位置之一:\n"
            f"1. {os.path.join(BASE_DIR, 'ffmpeg.exe')}\n"
            f"2. {os.path.join(BASE_DIR, 'bin', 'ffmpeg.exe')}\n"
            f"3. 系统 PATH 环境变量中"
        )
    
    root.mainloop()


if __name__ == '__main__':
    main()
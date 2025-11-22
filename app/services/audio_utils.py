import subprocess
import json
import tempfile
import os
import logging

logger = logging.getLogger(__name__)


async def get_audio_duration(file_content: bytes, filename: str) -> float:
    """
    获取音频文件时长（秒）
    
    Args:
        file_content: 文件内容
        filename: 文件名（用于确定扩展名）
    
    Returns:
        时长（秒）
    """
    # 创建临时文件
    file_extension = filename.split(".")[-1] if "." in filename else "mp3"
    
    with tempfile.NamedTemporaryFile(suffix=f".{file_extension}", delete=False) as temp_file:
        temp_path = temp_file.name
        temp_file.write(file_content)
    
    try:
        # 使用 ffprobe 获取时长
        cmd = [
            'ffprobe',
            '-v', 'quiet',
            '-print_format', 'json',
            '-show_format',
            temp_path
        ]
        
        logger.info(f"执行 ffprobe 命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.error(f"ffprobe 执行失败: {result.stderr}")
            raise Exception(f"无法获取音频时长: {result.stderr}")
        
        data = json.loads(result.stdout)
        duration = float(data['format']['duration'])
        
        logger.info(f"音频时长: {duration} 秒")
        return duration
        
    except subprocess.TimeoutExpired:
        logger.error("ffprobe 执行超时")
        raise Exception("获取音频时长超时")
    except KeyError:
        logger.error(f"ffprobe 输出格式异常: {result.stdout}")
        raise Exception("无法解析音频信息")
    except Exception as e:
        logger.error(f"获取音频时长失败: {e}")
        raise
    finally:
        # 删除临时文件
        try:
            os.unlink(temp_path)
        except:
            pass

import asyncio
import logging
import torch
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

whisper_model = None

def init_whisper_model():
    """
    初始化 Whisper 模型的同步函数，由主程序的 lifespan 事件统一分配生命周期。
    """
    global whisper_model
    # 单例模式防穿透
    if whisper_model is not None:
        return
        
    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"

    logger.info(f"底层准备拉起 Faster-Whisper: {device.upper()} ({compute_type})")

    try:
        whisper_model = WhisperModel("small", device=device, compute_type=compute_type)
        logger.info("=== Whisper 框架装载圆满成功并注入全局作用域 ===")
    except Exception as e:
        logger.error(f"Whisper 底层内核受损失效: {e}")
        raise

async def transcribe_media(file_path: str) -> str:
    """
    异步非阻塞转录音频媒体文件，对接生产级的 Faster-Whisper 系统。
    它将从物理隔离的源提取特征并识别为连续的中文（或多语种）文本。
    """
    try:
        logger.info(f"唤起语音提取工作流，处理物理文件：{file_path}")

        # 【核心架构防拥塞设计】
        # 由于 model.transcribe 返回的 segments 本质是一个生成器 (Generator)，
        # 其音频解码与推理过程是在 next(segments) 的迭代过程中惰性执行的（CPU/GPU 同步爆表）。
        # 如果我们在主事件循环中去 for 循环它，依旧会阻塞整个 FastAPI 的其他并发请求。
        # 必须将从加载到完整遍历生成器的动作，完完全全打包封锁到一个内部函数中，送进后台异步线程持行。
        def _run_sync_whisper():
            if not whisper_model:
                raise RuntimeError("系统错位：您没有随主程序的 lifespan 正确唤起加载 whisper_model 实例！")
                
            # 开启 C++ 密集运算
            segments, info = whisper_model.transcribe(file_path, beam_size=5)
            
            # 在隔离线程中吞噬吸干全部迭代数据
            full_texts = []
            for segment in segments:
                full_texts.append(segment.text)
            
            # 安全返回纯净字符串
            return " ".join(full_texts).strip()

        # 交给系统级别的异步线程池分发运行这个密集阻塞任务
        transcription_result = await asyncio.to_thread(_run_sync_whisper)

        logger.info(f"转录物理切割完毕。总提琴析出字数：{len(transcription_result)} 字。")
        
        return transcription_result

    except Exception as e:
        logger.error(f"Faster-Whisper 提纯音频链崩溃，无法解析该媒体轨: {e}")
        raise

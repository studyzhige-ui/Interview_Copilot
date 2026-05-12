"""Audio transcription service — WhisperX + Pyannote diarization.

Renamed from ``app.services.transcription_service`` to disambiguate from
``app.services.chat.chat_history_service`` (chat transcripts as text).
"""

import asyncio
import logging

import torch

from app.core.config import settings
from app.core.hf_runtime import prepare_hf_runtime, resolve_local_snapshot

logger = logging.getLogger(__name__)

whisper_model = None
diarize_model = None


def init_whisper_model():
    """
    初始化 WhisperX 与 Pyannote 的同步函数，由主程序的 lifespan 事件统一分配生命周期验证。
    杜绝在业务请求期间发生 OOM 重复映射加载。
    """
    global whisper_model, diarize_model
    if whisper_model is not None and diarize_model is not None:
        return

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"

    logger.info(f"底层准备拉起声纹特征级提取核: {device.upper()} ({compute_type})")

    try:
        hf_cache_dir = prepare_hf_runtime()
        local_whisper_path = resolve_local_snapshot(settings.WHISPER_MODEL_ID)
        diarization_model_path = resolve_local_snapshot(settings.DIARIZATION_MODEL_ID)
        if local_whisper_path is None:
            raise RuntimeError(
                f"Whisper model '{settings.WHISPER_MODEL_ID}' is missing. "
                "Run the model init script before starting the backend."
            )
        if diarization_model_path is None:
            raise RuntimeError(
                f"Diarization model '{settings.DIARIZATION_MODEL_ID}' is missing. "
                "Run the model init script before starting the backend."
            )

        import whisperx
        from whisperx.diarize import DiarizationPipeline
        whisper_model = whisperx.load_model(
            local_whisper_path,
            device,
            compute_type=compute_type,
            download_root=str(hf_cache_dir),
            local_files_only=True,
        )
        diarize_model = DiarizationPipeline(model_name=diarization_model_path, device=device)
        logger.info("=== WhisperX & Diarization 声纹双核框架装载圆满成功 ===")
    except ImportError:
        logger.warning("未捕获原生 WhisperX 声纹剥离库，启动 Mock 声纹测试兜底通道。")
        raise
    except Exception as e:
        logger.error(f"Whisper 底层内核受损失效: {e}")
        raise


async def transcribe_media(file_path: str) -> str:
    """
    异步非阻塞转录音频媒体文件。
    【声纹剥离升级】：将录音精准降维剥离出多持卡人 Speaker 问答对抗，并序列化为 Markdown 流。
    """
    try:
        logger.info(f"唤起语音声纹降维工作流，处理物理文件：{file_path}")

        def _run_sync_whisper():
            if not whisper_model:
                raise RuntimeError("系统错位：您没有随主程序的 lifespan 正确唤起加载声纹实例！")

            if whisper_model == "mock_model":
                return "**[Speaker 1]**: 请问你的项目难点是什么？\n\n**[Speaker 2]**: 难点在于高并发处理下，分布式锁发生脑裂的情况。\n\n**[Speaker 1]**: 你是怎么解决的？\n\n**[Speaker 2]**: 我采用了 Redisson 的看门狗机制。"

            import whisperx

            audio = whisperx.load_audio(file_path)
            result = whisper_model.transcribe(audio, batch_size=16)

            diarize_segments = diarize_model(audio)

            result = whisperx.assign_word_speakers(diarize_segments, result)

            lines = []
            current_speaker = None
            current_sentence = []

            for segment in result.get("segments", []):
                speaker = segment.get("speaker", "UNKNOWN")
                text = segment.get("text", "").strip()

                if speaker != current_speaker:
                    if current_speaker is not None:
                        lines.append(f"**[{current_speaker}]**: {' '.join(current_sentence)}")
                    current_speaker = speaker
                    current_sentence = [text]
                else:
                    current_sentence.append(text)

            if current_speaker is not None:
                lines.append(f"**[{current_speaker}]**: {' '.join(current_sentence)}")

            return "\n\n".join(lines)

        transcription_result = await asyncio.to_thread(_run_sync_whisper)
        logger.info(f"声纹剥离转录完成，已封装为具有层级的 Markdown。字长：{len(transcription_result)}。")

        return transcription_result

    except Exception as e:
        logger.error(f"声纹重构链崩溃，无法解析该媒体轨: {e}")
        raise


__all__ = ["init_whisper_model", "transcribe_media", "whisper_model", "diarize_model"]

"""
Demo Music - ساخت پیش‌نمایش صوتی
Audio demo/preview generation

Features / امکانات:
- Extract time range from audio
  استخراج بازه زمانی از صدا
- Convert to voice format (OGG)
  تبدیل به فرمت صوتی (OGG)
- Send as Telegram voice message
  ارسال به عنوان پیام صوتی تلگرام
"""

import subprocess
import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DemoMusic:
    """Audio demo generation / ساخت پیش‌نمایش صوتی"""

    def __init__(self, temp_dir: str = "/tmp"):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(exist_ok=True)

    def create_demo(
        self,
        input_path: str,
        start: float = 0,
        end: float = 0,
        output_format: str = "ogg",
    ) -> Optional[str]:
        """
        Create demo/preview from audio file
        ساخت پیش‌نمایش از فایل صوتی

        Args:
            input_path: Path to input audio file
            start: Start time in seconds
            end: End time in seconds (0 = end of file)
            output_format: Output format (ogg for voice, mp3 for audio)

        Returns:
            Path to output file or None
        """
        if not os.path.exists(input_path):
            return None

        # Get duration
        duration = self._get_duration(input_path)
        if duration <= 0:
            return None

        # Validate times
        if start < 0:
            start = 0
        if end <= 0 or end > duration:
            end = duration
        if start >= end:
            return None

        # Calculate clip duration
        clip_duration = end - start

        # Build output path
        output_path = str(
            self.temp_dir / f"demo_{Path(input_path).stem}.{output_format}"
        )

        try:
            if output_format == "ogg":
                # OGG Vorbis for Telegram voice
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(start),
                    "-i", input_path,
                    "-t", str(clip_duration),
                    "-c:a", "libvorbis",
                    "-q:a", "6",
                    "-ar", "44100",
                    "-ac", "1",  # Mono for voice
                    output_path,
                ]
            elif output_format == "mp3":
                # MP3 for audio message
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(start),
                    "-i", input_path,
                    "-t", str(clip_duration),
                    "-c:a", "libmp3lame",
                    "-b:a", "192k",
                    output_path,
                ]
            else:
                return None

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=60
            )

            if result.returncode == 0 and os.path.exists(output_path):
                return output_path

        except Exception as e:
            logger.error(f"Demo creation error: {e}")

        return None

    def create_voice_demo(
        self, input_path: str, start: float = 0, end: float = 0
    ) -> Optional[str]:
        """
        Create voice demo (OGG format for Telegram)
        ساخت دموی صوتی (فرمت OGG برای تلگرام)
        """
        return self.create_demo(input_path, start, end, "ogg")

    def create_audio_demo(
        self, input_path: str, start: float = 0, end: float = 0
    ) -> Optional[str]:
        """
        Create audio demo (MP3 format)
        ساخت دموی صوتی (فرمت MP3)
        """
        return self.create_demo(input_path, start, end, "mp3")

    def _get_duration(self, file_path: str) -> float:
        """Get audio duration / دریافت مدت صدا"""
        try:
            cmd = [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                file_path,
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception:
            pass
        return 0.0

    def cleanup(self, *paths):
        """Remove temporary files / حذف فایل‌های موقت"""
        for path in paths:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

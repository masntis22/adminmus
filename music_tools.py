"""
Music Tools - جعبه ابزار کامل ویرایش موزیک
Complete music editing toolbox for Admin Channel Bot

Features / امکانات:
- Metadata editing (title, artist, album, year, genre, track)
  ویرایش متادیتا (عنوان، هنرمند، آلبوم، سال، ژانر، شماره ترک)
- Cover art management (add/change/remove)
  مدیریت کاور آرت (افزودن/تغییر/حذف)
- Audio format conversion (mp3, m4a, flac, wav)
  تبدیل فرمت صوتی
- Volume normalization
  نرمال‌سازی صدا
- Fade in/out effects
  افکت fade in/out
- Trim/cut audio
  برش صدا
- Metadata preview
  پیش‌نمایش متادیتا
- Metadata export as text/JSON
  خروجی متادیتا به متن/JSON
"""

import os
import json
import subprocess
import logging
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC, ID3NoHeaderError
from mutagen import File as MutagenFile

logger = logging.getLogger(__name__)

# Supported formats
SUPPORTED_FORMATS = ["mp3", "m4a", "flac", "wav"]
DEFAULT_FORMAT = "mp3"
DEFAULT_BITRATE = "320"


class MusicTools:
    """Complete music editing toolbox / جعبه ابزار کامل ویرایش موزیک"""

    def __init__(self, temp_dir: str = "/tmp"):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(exist_ok=True)

    # ════════════════════════════════════════════════════════════
    # METADATA - متادیتا
    # ════════════════════════════════════════════════════════════

    def get_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        Get all metadata from audio file
        دریافت تمام متادیتا از فایل صوتی
        """
        result = {
            "title": "",
            "artist": "",
            "album": "",
            "year": "",
            "genre": "",
            "track": "",
            "has_cover": False,
            "cover_size": 0,
            "duration": 0,
            "file_size": 0,
            "format": "",
        }

        if not os.path.exists(file_path):
            return result

        result["file_size"] = os.path.getsize(file_path)
        result["format"] = os.path.splitext(file_path)[1].lower().lstrip(".")

        # Get EasyID3 metadata
        try:
            audio = EasyID3(file_path)
            result["title"] = audio.get("title", [""])[0]
            result["artist"] = audio.get("artist", [""])[0]
            result["album"] = audio.get("album", [""])[0]
            result["year"] = audio.get("date", [""])[0]
            result["genre"] = audio.get("genre", [""])[0]
            result["track"] = audio.get("tracknumber", [""])[0]
        except Exception:
            pass

        # Get cover art info
        try:
            af = ID3(file_path)
            cover_tags = [k for k in af.keys() if k.startswith("APIC")]
            if cover_tags:
                result["has_cover"] = True
                result["cover_size"] = len(af[cover_tags[0]].data)
        except Exception:
            pass

        # Get duration
        try:
            mf = MutagenFile(file_path)
            if mf and mf.info:
                result["duration"] = mf.info.length
        except Exception:
            pass

        return result

    def set_metadata(self, file_path: str, **kwargs) -> bool:
        """
        Set metadata fields on audio file
        تنظیم فیلدهای متادیتا روی فایل صوتی

        Supported fields: title, artist, album, year, genre, track
        فیلدهای پشتیبانی شده: عنوان، هنرمند، آلبوم، سال، ژانر، شماره ترک
        """
        if not os.path.exists(file_path):
            return False

        try:
            audio = EasyID3(file_path)
        except ID3NoHeaderError:
            # Create new ID3 tags
            try:
                af = ID3(file_path)
            except ID3NoHeaderError:
                af = ID3()
            af.save(file_path)
            audio = EasyID3(file_path)
        except Exception:
            return False

        field_map = {
            "title": "title",
            "artist": "artist",
            "album": "album",
            "year": "date",
            "genre": "genre",
            "track": "tracknumber",
        }

        for key, value in kwargs.items():
            if key in field_map and value:
                audio[field_map[key]] = str(value)

        audio.save()
        return True

    def get_metadata_text(self, file_path: str) -> str:
        """
        Get metadata as formatted text
        دریافت متادیتا به صورت متن فرمت شده
        """
        meta = self.get_metadata(file_path)
        duration_str = self._format_duration(meta["duration"])

        lines = [
            "📋 **اطلاعات موزیک:**",
            "",
            f"📌 عنوان: {meta['title'] or '(خالی)'}",
            f"🎤 هنرمند: {meta['artist'] or '(خالی)'}",
            f"💿 آلبوم: {meta['album'] or '(خالی)'}",
            f"📅 سال: {meta['year'] or '(خالی)'}",
            f"🎵 ژانر: {meta['genre'] or '(خالی)'}",
            f"🔢 شماره ترک: {meta['track'] or '(خالی)'}",
            f"🖼️ کاور: {'✅' if meta['has_cover'] else '❌'}",
            f"⏱️ مدت: {duration_str}",
            f"📦 حجم: {meta['file_size'] / 1024:.1f} KB",
            f"📁 فرمت: {meta['format'].upper()}",
        ]
        return "\n".join(lines)

    def get_metadata_json(self, file_path: str) -> str:
        """
        Get metadata as JSON string
        دریافت متادیتا به صورت رشته JSON
        """
        meta = self.get_metadata(file_path)
        meta["duration_str"] = self._format_duration(meta["duration"])
        return json.dumps(meta, ensure_ascii=False, indent=2)

    # ════════════════════════════════════════════════════════════
    # COVER ART - کاور آرت
    # ════════════════════════════════════════════════════════════

    def get_cover(self, file_path: str) -> Optional[bytes]:
        """
        Get cover art data from audio file
        دریافت داده کاور آرت از فایل صوتی
        """
        try:
            af = ID3(file_path)
            cover_tags = [k for k in af.keys() if k.startswith("APIC")]
            if cover_tags:
                return af[cover_tags[0]].data
        except Exception:
            pass
        return None

    def set_cover(self, file_path: str, cover_path: str) -> bool:
        """
        Set cover art on audio file
        تنظیم کاور آرت روی فایل صوتی
        """
        if not os.path.exists(file_path) or not os.path.exists(cover_path):
            return False

        try:
            # Detect mime type
            mime = "image/jpeg"
            if cover_path.lower().endswith(".png"):
                mime = "image/png"

            with open(cover_path, "rb") as f:
                cover_data = f.read()

            af = ID3(file_path)
            af.delall("APIC")
            af.add(APIC(
                encoding=3,
                mime=mime,
                type=3,
                desc="Cover",
                data=cover_data,
            ))
            af.save()
            return True
        except Exception as e:
            logger.error(f"Set cover error: {e}")
            return False

    def remove_cover(self, file_path: str) -> bool:
        """
        Remove cover art from audio file
        حذف کاور آرت از فایل صوتی
        """
        try:
            af = ID3(file_path)
            af.delall("APIC")
            af.save()
            return True
        except Exception:
            return False

    def save_cover_to_file(self, file_path: str, output_path: str) -> bool:
        """
        Extract cover art and save to file
        استخراج کاور آرت و ذخیره در فایل
        """
        cover_data = self.get_cover(file_path)
        if not cover_data:
            return False

        with open(output_path, "wb") as f:
            f.write(cover_data)
        return True

    # ════════════════════════════════════════════════════════════
    # FORMAT CONVERSION - تبدیل فرمت
    # ════════════════════════════════════════════════════════════

    def convert_format(
        self,
        input_path: str,
        output_format: str = "mp3",
        bitrate: str = "320",
    ) -> Optional[str]:
        """
        Convert audio to different format
        تبدیل صدا به فرمت دیگر

        Args:
            input_path: Path to input audio file
            output_format: Target format (mp3, m4a, flac, wav)
            bitrate: Output bitrate for lossy formats (128, 192, 256, 320)
        """
        if output_format not in SUPPORTED_FORMATS:
            return None

        output_path = str(
            self.temp_dir / f"converted_{Path(input_path).stem}.{output_format}"
        )

        try:
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-acodec",
                "libmp3lame" if output_format == "mp3" else
                "aac" if output_format == "m4a" else
                "flac" if output_format == "flac" else
                "pcm_s16le",
            ]

            if output_format in ("mp3", "m4a"):
                cmd.extend(["-b:a", f"{bitrate}k"])

            cmd.append(output_path)

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0 and os.path.exists(output_path):
                return output_path
        except Exception as e:
            logger.error(f"Convert error: {e}")

        return None

    # ════════════════════════════════════════════════════════════
    # VOLUME / NORMALIZATION - صدا / نرمال‌سازی
    # ════════════════════════════════════════════════════════════

    def normalize_volume(
        self, input_path: str, target_level: float = -16.0
    ) -> Optional[str]:
        """
        Normalize audio volume
        نرمال‌سازی حجم صدا

        Args:
            input_path: Path to input audio file
            target_level: Target loudness in LUFS (default -16)
        """
        output_path = str(self.temp_dir / f"normalized_{Path(input_path).name}")

        try:
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-af", f"loudnorm=I={target_level}:TP=-1.5:LRA=11",
                "-ar", "44100",
                output_path,
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0 and os.path.exists(output_path):
                return output_path
        except Exception as e:
            logger.error(f"Normalize error: {e}")

        return None

    def change_volume(
        self, input_path: str, volume_db: float = 0
    ) -> Optional[str]:
        """
        Change audio volume by dB
        تغییر حجم صدا بر حسب دسیبل

        Args:
            volume_db: Volume change in dB (positive = louder, negative = quieter)
        """
        output_path = str(self.temp_dir / f"volume_{Path(input_path).name}")

        try:
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-af", f"volume={volume_db}dB",
                output_path,
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0 and os.path.exists(output_path):
                return output_path
        except Exception as e:
            logger.error(f"Volume change error: {e}")

        return None

    # ════════════════════════════════════════════════════════════
    # FADE EFFECTS - افکت‌های fade
    # ════════════════════════════════════════════════════════════

    def add_fade(
        self,
        input_path: str,
        fade_in: float = 0,
        fade_out: float = 0,
    ) -> Optional[str]:
        """
        Add fade in/out effects
        اضافه کردن افکت fade in/out

        Args:
            fade_in: Fade in duration in seconds
            fade_out: Fade out duration in seconds
        """
        output_path = str(self.temp_dir / f"faded_{Path(input_path).name}")

        # Get duration for fade_out
        meta = self.get_metadata(input_path)
        duration = meta["duration"]

        filters = []
        if fade_in > 0:
            filters.append(f"afade=t=in:d={fade_in}")
        if fade_out > 0 and duration > fade_out:
            start = duration - fade_out
            filters.append(f"afade=t=out:st={start}:d={fade_out}")

        if not filters:
            return None

        try:
            cmd = [
                "ffmpeg", "-y", "-i", input_path,
                "-af", ",".join(filters),
                output_path,
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0 and os.path.exists(output_path):
                return output_path
        except Exception as e:
            logger.error(f"Fade error: {e}")

        return None

    # ════════════════════════════════════════════════════════════
    # TRIM / CUT - برش
    # ════════════════════════════════════════════════════════════

    def trim(
        self, input_path: str, start: float = 0, end: float = 0
    ) -> Optional[str]:
        """
        Trim audio to specific time range
        برش صدا به بازه زمانی مشخص

        Args:
            start: Start time in seconds
            end: End time in seconds (0 = end of file)
        """
        output_path = str(self.temp_dir / f"trimmed_{Path(input_path).name}")

        try:
            cmd = ["ffmpeg", "-y", "-i", input_path, "-ss", str(start)]
            if end > 0:
                cmd.extend(["-to", str(end)])
            cmd.extend(["-c", "copy", output_path])

            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0 and os.path.exists(output_path):
                return output_path
        except Exception as e:
            logger.error(f"Trim error: {e}")

        return None

    # ════════════════════════════════════════════════════════════
    # HELPER FUNCTIONS - توابع کمکی
    # ════════════════════════════════════════════════════════════

    def _format_duration(self, seconds: float) -> str:
        """Format seconds to MM:SS"""
        if seconds <= 0:
            return "0:00"
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}:{secs:02d}"

    def cleanup(self, *paths):
        """Remove temporary files / حذف فایل‌های موقت"""
        for path in paths:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

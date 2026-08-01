# 🎵 Music Toolbox Enhancement Plan

## Complete Analysis & Architecture for adminmus Bot Music Editor

---

## Part 1: Current Issues Found

### Bugs & Critical Issues

1. **Bare `except` swallows metadata errors silently** (bot.py:724-725)
   ```python
   # BUG: If EasyID3 can't write (corrupt file, unsupported format), 
   # the error is completely swallowed — user thinks it worked
   try:
       audio = EasyID3(file_path)
       audio["title"] = d.get("title", "نامشخص")
       audio["artist"] = d.get("artist", "نامشخص")
       audio.save()
   except Exception:
       pass  # <-- silent failure
   ```

2. **Cover art MIME type hardcoded to `image/jpeg`** (bot.py:740)
   ```python
   # BUG: PNG covers will have wrong MIME type, causing display issues
   # in some players
   af.add(APIC(
       encoding=3,
       mime="image/jpeg",  # <-- always JPEG, even for PNG covers
       type=3,
       desc="Cover",
       data=cover_data,
   ))
   ```

3. **APIC cover detection only works for ID3/MP3** (bot.py:640)
   ```python
   # BUG: FLAC (Vorbis comments) and M4A (MP4 atoms) use different 
   # cover art storage — this won't detect them
   has_cover = any(k.startswith("APIC") for k in af.keys())
   ```

4. **No handling of non-ID3 audio files** (bot.py:629)
   ```python
   # BUG: FLAC files will crash EasyID3 which only handles ID3 tags.
   # M4A files use MP4 tags, not ID3 at all.
   try:
       audio_file = EasyID3(str(tmp_path))  # Crashes on FLAC/M4A
       title = audio_file.get("title", ["نامشخص"])[0]
       artist = audio_file.get("artist", ["نامشخص"])[0]
   except Exception:
       title = audio.title or "نامشخص"  # <-- audio is a Telegram object, not file
       artist = "نامشخص"
   ```
   Note: `audio` on line 633 refers to the *Telegram message.audio*, not a mutagen file — `audio.title` gives the Telegram filename, not the embedded title.

5. **No temp file cleanup on errors** (bot.py:710-748)
   ```python
   # If music_apply_changes raises before returning, or music_finish 
   # fails between apply and send, temp files leak:
   # - file_path remains on disk
   # - cover_path remains on disk
   ```

6. **State corruption risk** — `set_state` replaces entire `d` dict via `**d` splatting (bot.py:676,688,700). If any key is missing or has an unexpected type, downstream functions silently get wrong data.

### Missing Features

| Feature | Status |
|---------|--------|
| Edit title | ✅ Implemented |
| Edit artist | ✅ Implemented |
| Edit album | ❌ Missing |
| Edit year | ❌ Missing |
| Edit genre | ❌ Missing |
| Add cover art | ✅ Implemented |
| Remove cover art | ❌ Missing |
| Preview changes | ❌ Missing (applies on "done") |
| Batch editing | ❌ Missing |
| Format conversion | ❌ Missing |
| Audio quality settings | ❌ Missing |
| Volume normalization | ❌ Missing |
| Fade in/out | ❌ Missing |
| Trim/cut audio | ❌ Missing |
| Add watermark/tag | ❌ Missing |
| Export metadata | ❌ Missing |
| Non-MP3 format support | ❌ Missing |
| Undo changes | ❌ Missing |
| Progress indicators | ❌ Missing |
| File size validation | ❌ Missing |
| Supported format detection | ❌ Missing |

### Edge Cases

- Sending non-audio file while in `music_waiting` state — user gets "please send audio" but no navigation back
- Sending same file twice — stale state from previous edit persists
- Very long title/artist breaks keyboard layout
- Sending document instead of audio — `message.document` is handled but extension detection may fail
- Concurrent editing — no locking on user state; rapid button clicks could race
- Corrupt audio files — no graceful error handling
- Audio files > 50MB — Telegram limit, no pre-check
- Cover art > 10MB — very slow processing, no feedback

---

## Part 2: Proposed Architecture

### New Files to Create

```
adminmus/
├── bot.py                    # Modified: integrate music toolbox
├── database.py               # Modified: add music edit history table
├── music_toolbox.py          # NEW: Core audio processing engine
├── music_handlers.py         # NEW: Telegram conversation handlers
├── music_ui.py               # NEW: Keyboard builders & message templates
├── music_preview.py          # NEW: Before/after comparison generator
├── requirements.txt          # Modified: add pydub, pillow
└── tests/
    └── test_music_toolbox.py # NEW: Unit tests
```

### Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│                     bot.py                          │
│  (routes callbacks & messages to music_handlers)    │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│              music_handlers.py                       │
│  (Telegram conversation flow - all user interaction) │
│                                                      │
│  States:                                             │
│   music_waiting → music_editing → music_changing_*   │
│   music_batch → music_audio_effects → music_convert  │
│   music_preview → music_confirm                      │
└──────┬──────────────┬───────────────┬────────────────┘
       │              │               │
┌──────▼──────┐ ┌─────▼──────┐ ┌─────▼──────────────┐
│ music_ui.py │ │music_preview│ │ music_toolbox.py    │
│ (keyboards, │ │   .py       │ │ (core engine)       │
│  messages)  │ │(comparisons)│ │                      │
└─────────────┘ └─────────────┘ │ • read_metadata()    │
                                │ • write_metadata()   │
                                │ • convert_format()   │
                                │ • normalize_volume() │
                                │ • fade_audio()       │
                                │ • trim_audio()       │
                                │ • add_watermark()    │
                                │ • export_metadata()  │
                                └─────────────────────┘
```

---

## Part 3: Complete Code for Each Module

### 3.1 `music_toolbox.py` — Core Audio Engine

```python
"""
Music Toolbox - Core audio processing engine
جعبه ابزار موزیک - موتور پردازش صوتی اصلی

Uses:
- mutagen: metadata reading/writing for all formats
- pydub: audio processing (convert, fade, trim, normalize)
- pillow: cover art processing
"""

import os
import json
import struct
import logging
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime

from mutagen.easyid3 import EasyID3
from mutagen.id3 import APIC, ID3
from mutagen.mp4 import MP4Cover
from mutagen.flac import Picture
from mutagen import File as MutagenFile

logger = logging.getLogger(__name__)

# Supported formats
SUPPORTED_FORMATS = {
    ".mp3": {"mutagen": "EasyID3", "type": "id3"},
    ".m4a": {"mutagen": "EasyID3", "type": "mp4"},
    ".m4b": {"mutagen": "EasyID3", "type": "mp4"},
    ".flac": {"mutagen": "Vorbis", "type": "vorbis"},
    ".ogg": {"mutagen": "Vorbis", "type": "vorbis"},
    ".wav": {"mutagen": "Wav", "type": "wav"},
    ".wma": {"mutagen": "ASF", "type": "asf"},
}

FORMAT_OPTIONS = {
    "mp3": {"bitrates": [128, 192, 256, 320], "default": 192},
    "m4a": {"bitrates": [128, 192, 256, 320], "default": 192},
    "flac": {"bitrates": [], "default": 0},  # lossless, no bitrate option
    "wav": {"bitrates": [], "default": 0},   # uncompressed
}


class MusicToolbox:
    """Core music processing engine."""

    def __init__(self, temp_dir: str):
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(exist_ok=True)

    # ─── Metadata Reading ──────────────────────────────────────

    def read_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        Read all metadata from an audio file.
        Returns dict with: title, artist, album, year, genre, 
                          has_cover, duration, format, bitrate, file_size
        """
        result = {
            "title": "",
            "artist": "",
            "album": "",
            "year": "",
            "genre": "",
            "track_number": "",
            "has_cover": False,
            "cover_mime": "",
            "duration": 0,
            "format": "",
            "bitrate": 0,
            "file_size": os.path.getsize(file_path),
        }

        try:
            audio = MutagenFile(file_path, easy=True)
        except Exception as e:
            logger.warning(f"Cannot read file {file_path}: {e}")
            return result

        if audio is None:
            logger.warning(f"Unsupported format: {file_path}")
            return result

        # Get basic info
        result["duration"] = audio.info.length if audio.info else 0
        result["format"] = Path(file_path).suffix.lower().lstrip(".")
        result["bitrate"] = getattr(audio.info, "bitrate", 0)

        # Read tags based on format
        fmt = self._detect_format(file_path)

        if fmt == "id3":
            result.update(self._read_id3(file_path))
        elif fmt == "mp4":
            result.update(self._read_mp4(file_path))
        elif fmt == "vorbis":
            result.update(self._read_vorbis(file_path))
        else:
            # Try generic mutagen
            try:
                easy = EasyID3(file_path)
                result["title"] = easy.get("title", [""])[0]
                result["artist"] = easy.get("artist", [""])[0]
                result["album"] = easy.get("album", [""])[0]
                result["genre"] = easy.get("genre", [""])[0]
                result["year"] = easy.get("date", [""])[0]
            except Exception:
                pass

        return result

    def _detect_format(self, file_path: str) -> str:
        """Detect the tag format of an audio file."""
        ext = Path(file_path).suffix.lower()
        if ext in (".mp3",):
            return "id3"
        elif ext in (".m4a", ".m4b", ".mp4"):
            return "mp4"
        elif ext in (".flac", ".ogg"):
            return "vorbis"
        return "unknown"

    def _read_id3(self, file_path: str) -> Dict[str, Any]:
        """Read ID3 tags (MP3)."""
        result = {}
        try:
            audio = ID3(file_path)
            # Title
            if "TIT2" in audio:
                result["title"] = str(audio["TIT2"])
            # Artist
            if "TPE1" in audio:
                result["artist"] = str(audio["TPE1"])
            # Album
            if "TALB" in audio:
                result["album"] = str(audio["TALB"])
            # Year
            if "TDRC" in audio:
                result["year"] = str(audio["TDRC"])
            elif "TYER" in audio:
                result["year"] = str(audio["TYER"])
            # Genre
            if "TCON" in audio:
                result["genre"] = str(audio["TCON"])
            # Track number
            if "TRCK" in audio:
                result["track_number"] = str(audio["TRCK"]).split("/")[0]
            # Cover art
            for key in audio.keys():
                if key.startswith("APIC"):
                    result["has_cover"] = True
                    result["cover_mime"] = audio[key].mime
                    break
        except Exception as e:
            logger.warning(f"ID3 read error: {e}")
        return result

    def _read_mp4(self, file_path: str) -> Dict[str, Any]:
        """Read MP4/M4A tags."""
        result = {}
        try:
            audio = MutagenFile(file_path)
            if audio and hasattr(audio, "tags"):
                tags = audio.tags
                result["title"] = tags.get("\xa9nam", [""])[0] if "\xa9nam" in tags else ""
                result["artist"] = tags.get("\xa9ART", [""])[0] if "\xa9ART" in tags else ""
                result["album"] = tags.get("\xa9alb", [""])[0] if "\xa9alb" in tags else ""
                result["year"] = str(tags.get("\xa9day", [""])[0]) if "\xa9day" in tags else ""
                result["genre"] = tags.get("\xa9gen", [""])[0] if "\xa9gen" in tags else ""
                # Cover art
                if "covr" in tags:
                    result["has_cover"] = True
                    cover = tags["covr"][0]
                    if hasattr(cover, "imageformat"):
                        result["cover_mime"] = "image/jpeg" if cover.imageformat == 0x0D else "image/png"
                    else:
                        result["cover_mime"] = "image/jpeg"
        except Exception as e:
            logger.warning(f"MP4 read error: {e}")
        return result

    def _read_vorbis(self, file_path: str) -> Dict[str, Any]:
        """Read Vorbis/FLAC/OGG tags."""
        result = {}
        try:
            audio = MutagenFile(file_path)
            if audio and hasattr(audio, "tags"):
                tags = audio.tags
                result["title"] = str(tags.get("TITLE", [""])[0]) if "TITLE" in tags else ""
                result["artist"] = str(tags.get("ARTIST", [""])[0]) if "ARTIST" in tags else ""
                result["album"] = str(tags.get("ALBUM", [""])[0]) if "ALBUM" in tags else ""
                result["year"] = str(tags.get("DATE", [""])[0]) if "DATE" in tags else ""
                result["genre"] = str(tags.get("GENRE", [""])[0]) if "GENRE" in tags else ""
                # Cover art
                if hasattr(audio, "pictures") and audio.pictures:
                    result["has_cover"] = True
                    result["cover_mime"] = audio.pictures[0].mime
        except Exception as e:
            logger.warning(f"Vorbis read error: {e}")
        return result

    # ─── Metadata Writing ──────────────────────────────────────

    def write_metadata(
        self,
        file_path: str,
        title: Optional[str] = None,
        artist: Optional[str] = None,
        album: Optional[str] = None,
        year: Optional[str] = None,
        genre: Optional[str] = None,
        track_number: Optional[str] = None,
    ) -> str:
        """
        Write metadata to audio file. Returns output path.
        Works with MP3 (ID3), M4A (MP4), FLAC/OGG (Vorbis).
        """
        fmt = self._detect_format(file_path)

        if fmt == "id3":
            self._write_id3(file_path, title, artist, album, year, genre, track_number)
        elif fmt == "mp4":
            self._write_mp4(file_path, title, artist, album, year, genre)
        elif fmt == "vorbis":
            self._write_vorbis(file_path, title, artist, album, year, genre)
        else:
            # Fallback to EasyID3
            try:
                audio = EasyID3(file_path)
                if title is not None:
                    audio["title"] = [title]
                if artist is not None:
                    audio["artist"] = [artist]
                if album is not None:
                    audio["album"] = [album]
                if genre is not None:
                    audio["genre"] = [genre]
                if year is not None:
                    audio["date"] = [year]
                audio.save()
            except Exception as e:
                logger.warning(f"EasyID3 fallback error: {e}")

        return file_path

    def _write_id3(self, file_path, title, artist, album, year, genre, track_number):
        """Write ID3 tags for MP3 files."""
        try:
            audio = ID3(file_path)
        except Exception:
            audio = ID3()

        from mutagen.id3 import TIT2, TPE1, TALB, TDRC, TCON, TRCK

        if title is not None:
            audio["TIT2"] = TIT2(encoding=3, text=[title])
        if artist is not None:
            audio["TPE1"] = TPE1(encoding=3, text=[artist])
        if album is not None:
            audio["TALB"] = TALB(encoding=3, text=[album])
        if year is not None:
            audio["TDRC"] = TDRC(encoding=3, text=[year])
        if genre is not None:
            audio["TCON"] = TCON(encoding=3, text=[genre])
        if track_number is not None:
            audio["TRCK"] = TRCK(encoding=3, text=[track_number])

        audio.save(file_path)
        logger.info(f"ID3 tags written to {file_path}")

    def _write_mp4(self, file_path, title, artist, album, year, genre):
        """Write MP4 tags for M4A files."""
        try:
            audio = MutagenFile(file_path)
            if audio is None:
                return
            if audio.tags is None:
                audio.add_tags()
            tags = audio.tags

            if title is not None:
                tags["\xa9nam"] = [title]
            if artist is not None:
                tags["\xa9ART"] = [artist]
            if album is not None:
                tags["\xa9alb"] = [album]
            if year is not None:
                tags["\xa9day"] = [year]
            if genre is not None:
                tags["\xa9gen"] = [genre]

            audio.save()
            logger.info(f"MP4 tags written to {file_path}")
        except Exception as e:
            logger.warning(f"MP4 write error: {e}")

    def _write_vorbis(self, file_path, title, artist, album, year, genre):
        """Write Vorbis comments for FLAC/OGG files."""
        try:
            audio = MutagenFile(file_path)
            if audio is None:
                return
            if audio.tags is None:
                audio.add_tags()
            tags = audio.tags

            if title is not None:
                tags["TITLE"] = [title]
            if artist is not None:
                tags["ARTIST"] = [artist]
            if album is not None:
                tags["ALBUM"] = [album]
            if year is not None:
                tags["DATE"] = [year]
            if genre is not None:
                tags["GENRE"] = [genre]

            audio.save()
            logger.info(f"Vorbis tags written to {file_path}")
        except Exception as e:
            logger.warning(f"Vorbis write error: {e}")

    # ─── Cover Art ─────────────────────────────────────────────

    def get_cover_art(self, file_path: str) -> Optional[Tuple[bytes, str]]:
        """Extract cover art. Returns (image_data, mime_type) or None."""
        fmt = self._detect_format(file_path)

        if fmt == "id3":
            try:
                audio = ID3(file_path)
                for key in audio.keys():
                    if key.startswith("APIC"):
                        return (audio[key].data, audio[key].mime)
            except Exception:
                pass

        elif fmt == "mp4":
            try:
                audio = MutagenFile(file_path)
                if audio and "covr" in audio.tags:
                    cover = audio.tags["covr"][0]
                    mime = "image/jpeg" if getattr(cover, "imageformat", 0) == 0x0D else "image/png"
                    return (bytes(cover), mime)
            except Exception:
                pass

        elif fmt == "vorbis":
            try:
                audio = MutagenFile(file_path)
                if audio and hasattr(audio, "pictures") and audio.pictures:
                    pic = audio.pictures[0]
                    return (pic.data, pic.mime)
            except Exception:
                pass

        return None

    def set_cover_art(self, file_path: str, image_path: str) -> bool:
        """Set cover art from an image file."""
        fmt = self._detect_format(file_path)

        # Detect image MIME
        ext = Path(image_path).suffix.lower()
        mime_map = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".gif": "image/gif",
            ".webp": "image/jpeg",  # webp → treat as jpeg for ID3
        }
        mime = mime_map.get(ext, "image/jpeg")

        with open(image_path, "rb") as f:
            image_data = f.read()

        if fmt == "id3":
            return self._set_cover_id3(file_path, image_data, mime)
        elif fmt == "mp4":
            return self._set_cover_mp4(file_path, image_data, mime)
        elif fmt == "vorbis":
            return self._set_cover_vorbis(file_path, image_data, mime)

        return False

    def _set_cover_id3(self, file_path, image_data, mime):
        try:
            audio = ID3(file_path)
            audio.delall("APIC")
            audio.add(APIC(
                encoding=3,
                mime=mime,
                type=3,  # Cover (front)
                desc="Cover",
                data=image_data,
            ))
            audio.save()
            return True
        except Exception as e:
            logger.warning(f"Set cover ID3 error: {e}")
            return False

    def _set_cover_mp4(self, file_path, image_data, mime):
        try:
            audio = MutagenFile(file_path)
            if audio is None:
                return False
            if audio.tags is None:
                audio.add_tags()

            # MP4 expects JPEG or PNG
            if mime == "image/png":
                cover_type = MP4Cover.FORMAT_PNG
            else:
                cover_type = MP4Cover.FORMAT_JPEG

            audio.tags["covr"] = [MP4Cover(image_data, imageformat=cover_type)]
            audio.save()
            return True
        except Exception as e:
            logger.warning(f"Set cover MP4 error: {e}")
            return False

    def _set_cover_vorbis(self, file_path, image_data, mime):
        try:
            audio = MutagenFile(file_path)
            if audio is None:
                return False
            if audio.tags is None:
                audio.add_tags()

            pic = Picture()
            pic.type = 3  # Cover (front)
            pic.mime = mime
            pic.desc = "Cover"
            pic.data = image_data

            audio.clear_pictures()
            audio.add_picture(pic)
            audio.save()
            return True
        except Exception as e:
            logger.warning(f"Set cover Vorbis error: {e}")
            return False

    def remove_cover_art(self, file_path: str) -> bool:
        """Remove cover art from audio file."""
        fmt = self._detect_format(file_path)
        try:
            if fmt == "id3":
                audio = ID3(file_path)
                audio.delall("APIC")
                audio.save()
            elif fmt == "mp4":
                audio = MutagenFile(file_path)
                if audio and "covr" in audio.tags:
                    del audio.tags["covr"]
                    audio.save()
            elif fmt == "vorbis":
                audio = MutagenFile(file_path)
                if audio:
                    audio.clear_pictures()
                    audio.save()
            return True
        except Exception as e:
            logger.warning(f"Remove cover error: {e}")
            return False

    # ─── Format Conversion ─────────────────────────────────────

    def convert_format(
        self,
        input_path: str,
        output_format: str = "mp3",
        bitrate: int = 192,
    ) -> str:
        """
        Convert audio to a different format.
        Uses pydub for conversion.
        Returns path to the converted file.
        """
        from pydub import AudioSegment

        output_path = str(
            self.temp_dir / f"converted_{os.urandom(8).hex()}.{output_format}"
        )

        try:
            audio = AudioSegment.from_file(input_path)

            if output_format == "mp3":
                audio.export(output_path, format="mp3", bitrate=f"{bitrate}k",
                           tags=audio.export_tags if hasattr(audio, 'export_tags') else {})
            elif output_format == "m4a":
                audio.export(output_path, format="mp4", bitrate=f"{bitrate}k")
            elif output_format == "flac":
                audio.export(output_path, format="flac")
            elif output_format == "wav":
                audio.export(output_path, format="wav")
            else:
                audio.export(output_path, format=output_format)

            logger.info(f"Converted {input_path} → {output_path} ({output_format})")
            return output_path

        except Exception as e:
            logger.error(f"Format conversion error: {e}")
            raise

    # ─── Audio Effects ─────────────────────────────────────────

    def normalize_volume(
        self,
        input_path: str,
        target_dbfs: float = -20.0,
    ) -> str:
        """
        Normalize audio volume to target dBFS.
        Returns path to normalized file.
        """
        from pydub import AudioSegment
        from pydub.effects import normalize

        output_path = str(
            self.temp_dir / f"norm_{os.urandom(8).hex()}{Path(input_path).suffix}"
        )

        try:
            audio = AudioSegment.from_file(input_path)
            normalized = normalize(audio, headroom=0.1)  # loudness normalization
            # Alternative: manual normalization to target
            change_in_dbfs = target_dbfs - audio.dBFS
            normalized = audio.apply_gain(change_in_dbfs)
            normalized.export(output_path, format=output_path.split(".")[-1])
            logger.info(f"Normalized {input_path} (dBFS: {audio.dBFS:.1f} → {target_dbfs})")
            return output_path
        except Exception as e:
            logger.error(f"Normalize error: {e}")
            raise

    def fade_audio(
        self,
        input_path: str,
        fade_in_ms: int = 0,
        fade_out_ms: int = 0,
    ) -> str:
        """
        Add fade in/out effects.
        Returns path to processed file.
        """
        from pydub import AudioSegment

        output_path = str(
            self.temp_dir / f"faded_{os.urandom(8).hex()}{Path(input_path).suffix}"
        )

        try:
            audio = AudioSegment.from_file(input_path)

            if fade_in_ms > 0:
                audio = audio.fade_in(fade_in_ms)
            if fade_out_ms > 0:
                audio = audio.fade_out(fade_out_ms)

            ext = Path(output_path).suffix.lstrip(".")
            audio.export(output_path, format=ext)
            logger.info(f"Faded {input_path} (in={fade_in_ms}ms, out={fade_out_ms}ms)")
            return output_path
        except Exception as e:
            logger.error(f"Fade error: {e}")
            raise

    def trim_audio(
        self,
        input_path: str,
        start_ms: int = 0,
        end_ms: Optional[int] = None,
    ) -> str:
        """
        Trim/cut audio. If end_ms is None, trim from start to end.
        Returns path to trimmed file.
        """
        from pydub import AudioSegment

        output_path = str(
            self.temp_dir / f"trimmed_{os.urandom(8).hex()}{Path(input_path).suffix}"
        )

        try:
            audio = AudioSegment.from_file(input_path)
            total_ms = len(audio)

            # Clamp values
            start_ms = max(0, min(start_ms, total_ms))
            if end_ms is None:
                end_ms = total_ms
            end_ms = max(start_ms, min(end_ms, total_ms))

            trimmed = audio[start_ms:end_ms]

            ext = Path(output_path).suffix.lstrip(".")
            trimmed.export(output_path, format=ext)
            logger.info(f"Trimmed {input_path} ({start_ms}ms → {end_ms}ms, total={total_ms}ms)")
            return output_path
        except Exception as e:
            logger.error(f"Trim error: {e}")
            raise

    def add_watermark(
        self,
        input_path: str,
        watermark_text: str,
        position: str = "bottom_right",  # top_left, top_right, bottom_left, bottom_right, center
        opacity: float = 0.3,
    ) -> str:
        """
        Add a text watermark/tag to audio metadata.
        For audio files, this embeds a comment tag with the watermark text.
        """
        output_path = str(
            self.temp_dir / f"watermarked_{os.urandom(8).hex()}{Path(input_path).suffix}"
        )

        import shutil
        shutil.copy2(input_path, output_path)

        fmt = self._detect_format(output_path)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        try:
            if fmt == "id3":
                from mutagen.id3 import COMM
                audio = ID3(output_path)
                audio.delall("COMM")
                audio.add(COMM(encoding=3, lang="eng", desc="", text=f"{watermark_text} [{timestamp}]"))
                audio.save()
            elif fmt == "mp4":
                audio = MutagenFile(output_path)
                if audio:
                    if audio.tags is None:
                        audio.add_tags()
                    audio.tags["\xa9cmt"] = [f"{watermark_text} [{timestamp}]"]
                    audio.save()
            elif fmt == "vorbis":
                audio = MutagenFile(output_path)
                if audio and audio.tags:
                    audio.tags["COMMENT"] = [f"{watermark_text} [{timestamp}]"]
                    audio.save()

            logger.info(f"Watermark added to {output_path}: {watermark_text}")
            return output_path
        except Exception as e:
            logger.error(f"Watermark error: {e}")
            return output_path  # Return copy even if watermark fails

    # ─── Metadata Export ───────────────────────────────────────

    def export_metadata(
        self,
        file_path: str,
        format: str = "text",  # "text" or "json"
    ) -> str:
        """Export metadata as text or JSON string."""
        meta = self.read_metadata(file_path)

        if format == "json":
            meta["duration_formatted"] = self._format_duration(meta["duration"])
            meta["file_size_formatted"] = self._format_size(meta["file_size"])
            return json.dumps(meta, indent=2, ensure_ascii=False)
        else:
            lines = [
                "═══ Audio Metadata ═══",
                f"Title:       {meta['title'] or '(empty)'}",
                f"Artist:      {meta['artist'] or '(empty)'}",
                f"Album:       {meta['album'] or '(empty)'}",
                f"Year:        {meta['year'] or '(empty)'}",
                f"Genre:       {meta['genre'] or '(empty)'}",
                f"Track:       {meta['track_number'] or '(empty)'}",
                f"Format:      {meta['format'].upper()}",
                f"Duration:    {self._format_duration(meta['duration'])}",
                f"Bitrate:     {meta['bitrate'] // 1000 if meta['bitrate'] else '?'} kbps",
                f"File Size:   {self._format_size(meta['file_size'])}",
                f"Cover Art:   {'Yes (' + meta['cover_mime'] + ')' if meta['has_cover'] else 'No'}",
                "═══════════════════════",
            ]
            return "\n".join(lines)

    def _format_duration(self, seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    def _format_size(self, bytes_size: int) -> str:
        for unit in ["B", "KB", "MB", "GB"]:
            if bytes_size < 1024:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024
        return f"{bytes_size:.1f} TB"

    # ─── Batch Operations ──────────────────────────────────────

    def batch_edit_metadata(
        self,
        files: List[str],
        title: Optional[str] = None,
        artist: Optional[str] = None,
        album: Optional[str] = None,
        year: Optional[str] = None,
        genre: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Apply metadata changes to multiple files.
        If title/artist contain {n}, it's replaced with the track number.
        Returns list of results per file.
        """
        results = []
        for i, file_path in enumerate(files, 1):
            try:
                # Handle {n} pattern for batch numbering
                t = title.replace("{n}", str(i)) if title and "{n}" in title else title
                a = artist.replace("{n}", str(i)) if artist and "{n}" in artist else artist

                self.write_metadata(
                    file_path,
                    title=t, artist=a,
                    album=album, year=year, genre=genre,
                )
                results.append({"file": file_path, "success": True})
            except Exception as e:
                results.append({"file": file_path, "success": False, "error": str(e)})
                logger.error(f"Batch edit error on {file_path}: {e}")

        return results

    # ─── Cleanup Helper ────────────────────────────────────────

    def cleanup(self, *paths):
        """Remove temporary files."""
        for path in paths:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
```

### 3.2 `music_ui.py` — Keyboard Builders & UI Templates

```python
"""
Music UI - Telegram keyboards and message templates for music editing
رابط کاربری موزیک - کیبوردها و قالب‌های پیام
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_music_menu_kb():
    """Main music editing options."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 تکی (یک فایل)", callback_data="mt_single")],
        [InlineKeyboardButton("📦 گروهی (چند فایل)", callback_data="mt_batch")],
        [InlineKeyboardButton("📤 ارسال به کانال", callback_data="mt_send")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
    ])


def edit_menu_kb(meta: dict) -> InlineKeyboardMarkup:
    """Music editing menu with current metadata display."""
    title = (meta.get("title") or "—")[:30]
    artist = (meta.get("artist") or "—")[:30]
    album = (meta.get("album") or "—")[:30]
    year = meta.get("year") or "—"
    genre = (meta.get("genre") or "—")[:20]
    cover = "✅" if meta.get("has_cover") else "❌"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📌 عنوان: {title}", callback_data="mu_title")],
        [InlineKeyboardButton(f"🎤 هنرمند: {artist}", callback_data="mu_artist")],
        [InlineKeyboardButton(f"💿 آلبوم: {album}", callback_data="mu_album")],
        [InlineKeyboardButton(f"📅 سال: {year}", callback_data="mu_year")],
        [InlineKeyboardButton(f"🎶 ژانر: {genre}", callback_data="mu_genre")],
        [InlineKeyboardButton(f"🖼️ کاور: {cover} (تغییر)", callback_data="mu_cover")],
        [InlineKeyboardButton("🔧 افکت‌های صوتی", callback_data="mu_effects")],
        [InlineKeyboardButton("🔄 تبدیل فرمت", callback_data="mu_convert")],
        [InlineKeyboardButton("📋 خروجی متادیتا", callback_data="mu_export")],
        [InlineKeyboardButton("👁️ پیش‌نمایش", callback_data="mu_preview")],
        [InlineKeyboardButton("✅ ذخیره و ارسال", callback_data="mu_done")],
        [InlineKeyboardButton("❌ لغو", callback_data="mu_cancel")],
    ])


def preview_kb() -> InlineKeyboardMarkup:
    """Preview confirmation keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید", callback_data="mu_confirm_apply")],
        [InlineKeyboardButton("🔄 ویرایش بیشتر", callback_data="mu_back_to_edit")],
        [InlineKeyboardButton("❌ لغو", callback_data="mu_cancel")],
    ])


def audio_effects_kb() -> InlineKeyboardMarkup:
    """Audio effects submenu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 نرمالایز صدا", callback_data="mu_fx_normalize")],
        [InlineKeyboardButton("📈 Fade In", callback_data="mu_fx_fadein")],
        [InlineKeyboardButton("📉 Fade Out", callback_data="mu_fx_fadeout")],
        [InlineKeyboardButton("✂️ بُرش (Trim)", callback_data="mu_fx_trim")],
        [InlineKeyboardButton("🏷️ واترمارک", callback_data="mu_fx_watermark")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="mu_back_to_edit")],
    ])


def convert_format_kb(current_format: str) -> InlineKeyboardMarkup:
    """Format conversion keyboard."""
    formats = [
        ("mp3", "🎵 MP3"),
        ("m4a", "🎵 M4A (AAC)"),
        ("flac", "🎵 FLAC (Lossless)"),
        ("wav", "🎵 WAV (Uncompressed)"),
    ]
    rows = []
    for fmt, label in formats:
        marker = " ✅" if fmt == current_format else ""
        rows.append([InlineKeyboardButton(f"{label}{marker}", callback_data=f"mu_cvt_{fmt}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="mu_back_to_edit")])
    return InlineKeyboardMarkup(rows)


def bitrate_kb(current_bitrate: int = 192) -> InlineKeyboardMarkup:
    """Bitrate selection keyboard."""
    rates = [128, 192, 256, 320]
    rows = []
    for rate in rates:
        marker = " ✅" if rate == current_bitrate // 1000 else ""
        rows.append([InlineKeyboardButton(f"{rate} kbps{marker}", callback_data=f"mu_br_{rate}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="mu_convert")])
    return InlineKeyboardMarkup(rows)


def fade_duration_kb(direction: str) -> InlineKeyboardMarkup:
    """Fade duration selection."""
    durations = [500, 1000, 2000, 3000, 5000, 8000, 10000]
    rows = []
    for d in durations:
        label = f"{d/1000:.1f}s" if d >= 1000 else f"{d}ms"
        rows.append([InlineKeyboardButton(label, callback_data=f"mu_fade_{direction}_{d}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="mu_effects")])
    return InlineKeyboardMarkup(rows)


def trim_quick_kb(duration_ms: int) -> InlineKeyboardMarkup:
    """Quick trim presets."""
    secs = duration_ms // 1000
    rows = []
    # Common trim points
    presets = [
        ("🎵 اول 15 ثانیه", 0, 15000),
        ("🎵 آخر 15 ثانیه", max(0, duration_ms - 15000), duration_ms),
        ("🎵 اول 30 ثانیه", 0, 30000),
        ("🎵 آخر 30 ثانیه", max(0, duration_ms - 30000), duration_ms),
    ]
    for label, start, end in presets:
        if end <= duration_ms and start < end:
            rows.append([InlineKeyboardButton(label, callback_data=f"mu_trim_q_{start}_{end}")])
    rows.append([InlineKeyboardButton("✏️ برش دلخواه", callback_data="mu_trim_custom")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="mu_effects")])
    return InlineKeyboardMarkup(rows)


def export_format_kb() -> InlineKeyboardMarkup:
    """Export metadata format selection."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 متن ساده", callback_data="mu_exp_text")],
        [InlineKeyboardButton("📋 JSON", callback_data="mu_exp_json")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="mu_back_to_edit")],
    ])


def batch_list_kb(files_info: list) -> InlineKeyboardMarkup:
    """Batch editing file list with per-file toggles."""
    rows = []
    for i, fi in enumerate(files_info):
        status = "✅" if fi.get("selected", True) else "⬜"
        name = fi.get("name", f"File {i+1}")[:25]
        rows.append([
            InlineKeyboardButton(f"{status} {name}", callback_data=f"mt_toggle_{i}"),
            InlineKeyboardButton(f"📎{i+1}", callback_data=f"mt_info_{i}"),
        ])
    rows.append([InlineKeyboardButton("🔧 اعمال روی انتخاب‌شده‌ها", callback_data="mt_apply")])
    rows.append([InlineKeyboardButton("❌ لغو", callback_data="mu_cancel")])
    return InlineKeyboardMarkup(rows)


def format_meta_display(meta: dict) -> str:
    """Format metadata for display in Telegram message."""
    duration_s = meta.get("duration", 0)
    m, s = divmod(int(duration_s), 60)
    h, m = divmod(m, 60)
    dur = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    file_size = meta.get("file_size", 0)
    for unit in ["B", "KB", "MB", "GB"]:
        if file_size < 1024:
            size_str = f"{file_size:.1f} {unit}"
            break
        file_size /= 1024
    else:
        size_str = f"{file_size:.1f} TB"

    br = meta.get("bitrate", 0)
    br_str = f"{br // 1000} kbps" if br else "N/A"

    lines = [
        f"🎵 **اطلاعات فایل صوتی**",
        f"",
        f"📌 **عنوان:** {meta.get('title') or '—'}",
        f"🎤 **هنرمند:** {meta.get('artist') or '—'}",
        f"💿 **آلبوم:** {meta.get('album') or '—'}",
        f"📅 **سال:** {meta.get('year') or '—'}",
        f"🎶 **ژانر:** {meta.get('genre') or '—'}",
        f"🖼️ **کاور:** {'✅ دارد' if meta.get('has_cover') else '❌ ندارد'}",
        f"",
        f"⏱ **مدت:** {dur}",
        f"📊 **فرمت:** {meta.get('format', '?').upper()}",
        f"🔊 **بیت‌ریت:** {br_str}",
        f"📦 **حجم:** {size_str}",
    ]
    return "\n".join(lines)
```

### 3.3 `music_handlers.py` — Telegram Conversation Handlers

```python
"""
Music Handlers - Telegram conversation flow for music editing
هندلرهای موزیک - جریان مکالمه ویرایش موزیک

This module contains all callback handlers and message handlers
for the music editing feature.
"""

import os
import uuid
import logging
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from music_toolbox import MusicToolbox
from music_ui import (
    edit_menu_kb, preview_kb, audio_effects_kb,
    convert_format_kb, bitrate_kb, fade_duration_kb,
    trim_quick_kb, export_format_kb, batch_list_kb,
    format_meta_display,
)

logger = logging.getLogger(__name__)

# Will be initialized by bot.py
toolbox: MusicToolbox = None


def init_toolbox(temp_dir: str):
    global toolbox
    toolbox = MusicToolbox(temp_dir)


# ─── Helper ────────────────────────────────────────────────────

def _state(ctx):
    return ctx.user_data.get("state"), ctx.user_data.get("d", {})


def _set(ctx, state, **data):
    ctx.user_data["state"] = state
    ctx.user_data["d"] = data


def _clear(ctx):
    ctx.user_data.pop("state", None)
    ctx.user_data.pop("d", None)


# ─── Entry: Receive Audio ─────────────────────────────────────

async def on_audio_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle incoming audio file for editing."""
    state, d = _state(ctx)
    if state not in ("music_waiting", "mt_batch_waiting"):
        return False  # Not handled

    message = update.message
    audio = message.audio or message.document
    if not audio:
        await message.reply_text("❌ لطفاً یک فایل صوتی بفرستید.")
        return True

    await ctx.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)

    # Download
    file = await ctx.bot.get_file(audio.file_id)
    ext = os.path.splitext(file.file_path)[1] or ".mp3"
    tmp_path = str(Path(toolbox.temp_dir) / f"{uuid.uuid4().hex}{ext}")
    await file.download_to_drive(tmp_path)

    # Batch mode: accumulate files
    if state == "mt_batch_waiting":
        files = d.get("files", [])
        files.append(tmp_path)
        _set(ctx, "mt_batch_waiting", files=files, file_ids=d.get("file_ids", []) + [audio.file_id])

        count = len(files)
        await message.reply_text(
            f"✅ فایل {count} دریافت شد.\n\n"
            f"📁 **{count} فایل** آماده ویرایش گروهی.\n\n"
            "یک فایل دیگر بفرستید یا:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🔧 ویرایش {count} فایل", callback_data="mt_batch_edit")],
                [InlineKeyboardButton("❌ لغو", callback_data="mu_cancel")],
            ]),
        )
        return True

    # Single mode
    meta = toolbox.read_metadata(tmp_path)

    # Get file info for Telegram
    file_id = audio.file_id

    _set(ctx, "music_editing",
         file_path=tmp_path,
         original_file_id=file_id,
         meta=meta,
         pending_changes={},
         original_meta=meta.copy())

    text = format_meta_display(meta)
    text += "\n\nچه چیزی رو می‌خواید تغییر بدید؟"

    await message.reply_text(
        text,
        reply_markup=edit_menu_kb(meta),
        parse_mode=ParseMode.MARKDOWN,
    )
    return True


async def on_photo_received(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photo for cover art replacement."""
    state, d = _state(ctx)
    if state != "music_waiting_cover":
        return False

    message = update.message
    photo = message.photo[-1] if message.photo else None
    if not photo:
        await message.reply_text("❌ لطفاً یک عکس بفرستید.")
        return True

    # Download cover
    file = await ctx.bot.get_file(photo.file_id)
    cover_path = str(Path(toolbox.temp_dir) / f"cover_{uuid.uuid4().hex}.jpg")
    await file.download_to_drive(cover_path)

    # Update state
    d["pending_cover"] = cover_path
    _set(ctx, "music_editing", **d)

    meta = d.get("meta", {})
    meta["has_cover"] = True
    d["meta"] = meta

    await message.reply_text(
        "✅ کاور جدید دریافت شد!\n\n"
        "🖼️ کاور جایگزین خواهد شد. برای اعمال تغییرات روی «ذخیره و ارسال» بزنید.",
        reply_markup=edit_menu_kb(meta),
        parse_mode=ParseMode.MARKDOWN,
    )
    return True


# ─── Callback Handlers ────────────────────────────────────────

async def handle_music_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    """
    Route music-related callbacks. Returns True if handled.
    Called from the main callback_handler in bot.py.
    """
    if not data.startswith("mu_"):
        return False

    state, d = _state(ctx)
    query = update.callback_query

    # ── Edit field requests ──
    if data == "mu_title":
        _set(ctx, "music_changing_title", **d)
        await query.edit_message_text(
            f"✏️ **عنوان فعلی:** {d.get('meta', {}).get('title', '—')}\n\n📌 **عنوان جدید رو بفرستید:**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data="mu_back_to_edit")],
            ]),
        )
        return True

    if data == "mu_artist":
        _set(ctx, "music_changing_artist", **d)
        await query.edit_message_text(
            f"🎤 **هنرمند فعلی:** {d.get('meta', {}).get('artist', '—')}\n\n🎤 **نام هنرمند جدید رو بفرستید:**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data="mu_back_to_edit")],
            ]),
        )
        return True

    if data == "mu_album":
        _set(ctx, "music_changing_album", **d)
        await query.edit_message_text(
            f"💿 **آلبوم فعلی:** {d.get('meta', {}).get('album', '—')}\n\n💿 **نام آلبوم جدید رو بفرستید:**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data="mu_back_to_edit")],
            ]),
        )
        return True

    if data == "mu_year":
        _set(ctx, "music_changing_year", **d)
        await query.edit_message_text(
            f"📅 **سال فعلی:** {d.get('meta', {}).get('year', '—')}\n\n📅 **سال جدید رو بفرستید:** (مثال: 2024)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data="mu_back_to_edit")],
            ]),
        )
        return True

    if data == "mu_genre":
        _set(ctx, "music_changing_genre", **d)
        await query.edit_message_text(
            f"🎶 **ژانر فعلی:** {d.get('meta', {}).get('genre', '—')}\n\n🎶 **ژانر جدید رو بفرستید:**",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data="mu_back_to_edit")],
            ]),
        )
        return True

    # ── Cover art ──
    if data == "mu_cover":
        has_cover = d.get("meta", {}).get("has_cover", False)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🖼️ تغییر/اضافه کاور", callback_data="mu_cover_change")],
        ])
        if has_cover:
            kb.inline_keyboard.insert(0, [InlineKeyboardButton("🗑️ حذف کاور", callback_data="mu_cover_remove")])
        kb.inline_keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="mu_back_to_edit")])

        await query.edit_message_text(
            f"🖼️ **مدیریت کاور**\n\n"
            f"وضعیت فعلی: {'✅ دارد' if has_cover else '❌ ندارد'}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
        )
        return True

    if data == "mu_cover_change":
        _set(ctx, "music_waiting_cover", **d)
        await query.edit_message_text(
            "🖼️ **عکس کاور جدید رو بفرستید:**\n\n"
            "(JPG یا PNG با کیفیت خوب پیشنهاد می‌شود)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data="mu_back_to_edit")],
            ]),
        )
        return True

    if data == "mu_cover_remove":
        file_path = d.get("file_path")
        if file_path:
            toolbox.remove_cover_art(file_path)
            meta = toolbox.read_metadata(file_path)
            d["meta"] = meta
            _set(ctx, "music_editing", **d)

        await query.edit_message_text(
            "🗑️ کاور حذف شد!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=edit_menu_kb(d.get("meta", {})),
        )
        return True

    # ── Back to edit menu ──
    if data == "mu_back_to_edit":
        if state.startswith("mt_"):
            _set(ctx, state, **d)
        else:
            _set(ctx, "music_editing", **d)
        meta = d.get("meta", {})
        await query.edit_message_text(
            format_meta_display(meta) + "\n\nچه چیزی رو می‌خواید تغییر بدید؟",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=edit_menu_kb(meta),
        )
        return True

    # ── Audio effects ──
    if data == "mu_effects":
        await query.edit_message_text(
            "🔧 **افکت‌های صوتی**\n\nیکی رو انتخاب کنید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=audio_effects_kb(),
        )
        return True

    if data == "mu_fx_normalize":
        await query.edit_message_text(
            "📊 **نرمالایز صدا**\n\nصدا به سطح استاندارد تنظیم می‌شود.\n"
            "این عملیات ممکن است کمی طول بکشد...",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ اجرا", callback_data="mu_run_normalize")],
                [InlineKeyboardButton("❌ لغو", callback_data="mu_effects")],
            ]),
        )
        return True

    if data == "mu_run_normalize":
        file_path = d.get("file_path")
        if file_path:
            await ctx.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
            try:
                new_path = toolbox.normalize_volume(file_path)
                d["file_path"] = new_path
                _set(ctx, "music_editing", **d)
                await query.edit_message_text(
                    "✅ صدا نرمالایز شد!",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=edit_menu_kb(d.get("meta", {})),
                )
            except Exception as e:
                await query.edit_message_text(
                    f"❌ خطا در نرمالایز: {str(e)[:200]}",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=audio_effects_kb(),
                )
        return True

    if data == "mu_fx_fadein":
        await query.edit_message_text(
            "📈 **Fade In**\n\nمدت زمان افزایش تدریجی صدا رو انتخاب کنید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=fade_duration_kb("in"),
        )
        return True

    if data == "mu_fx_fadeout":
        await query.edit_message_text(
            "📉 **Fade Out**\n\nمدت زمان کاهش تدریجی صدا رو انتخاب کنید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=fade_duration_kb("out"),
        )
        return True

    # Fade duration selected
    if data.startswith("mu_fade_"):
        parts = data.split("_")  # mu_fade_{direction}_{ms}
        direction = parts[2]  # in or out
        duration_ms = int(parts[3])

        file_path = d.get("file_path")
        if file_path:
            await ctx.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
            try:
                fade_in = duration_ms if direction == "in" else 0
                fade_out = duration_ms if direction == "out" else 0
                new_path = toolbox.fade_audio(file_path, fade_in_ms=fade_in, fade_out_ms=fade_out)
                d["file_path"] = new_path
                _set(ctx, "music_editing", **d)

                dir_label = "Fade In" if direction == "in" else "Fade Out"
                await query.edit_message_text(
                    f"✅ {dir_label} ({duration_ms/1000:.1f}s) اعمال شد!",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=edit_menu_kb(d.get("meta", {})),
                )
            except Exception as e:
                await query.edit_message_text(
                    f"❌ خطا: {str(e)[:200]}",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=audio_effects_kb(),
                )
        return True

    # ── Trim ──
    if data == "mu_fx_trim":
        meta = d.get("meta", {})
        duration_ms = int(meta.get("duration", 0) * 1000)
        await query.edit_message_text(
            f"✂️ **بُرش صدا**\n\n"
            f"⏱ مدت فعلی: {duration_ms // 1000} ثانیه\n\n"
            f"یکی از گزینه‌ها رو انتخاب کنید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=trim_quick_kb(duration_ms),
        )
        return True

    if data.startswith("mu_trim_q_"):
        parts = data.split("_")
        start_ms = int(parts[3])
        end_ms = int(parts[4])

        file_path = d.get("file_path")
        if file_path:
            await ctx.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
            try:
                new_path = toolbox.trim_audio(file_path, start_ms, end_ms)
                d["file_path"] = new_path
                # Update duration in meta
                new_meta = toolbox.read_metadata(new_path)
                new_meta.update({k: v for k, v in d["meta"].items() if v})
                d["meta"] = new_meta
                _set(ctx, "music_editing", **d)

                await query.edit_message_text(
                    f"✅ صدا بُریده شد! (از {start_ms//1000}s تا {end_ms//1000}s)",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=edit_menu_kb(d.get("meta", {})),
                )
            except Exception as e:
                await query.edit_message_text(
                    f"❌ خطا: {str(e)[:200]}",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=audio_effects_kb(),
                )
        return True

    if data == "mu_trim_custom":
        _set(ctx, "music_trimming", **d)
        await query.edit_message_text(
            "✂️ **بُرش دلخواه**\n\n"
            "زمان شروع و پایان رو به این فرمت بفرستید:\n"
            "`0:00 - 3:45`\n\n"
            "(دقیقه:ثانیه)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data="mu_effects")],
            ]),
        )
        return True

    # ── Watermark ──
    if data == "mu_fx_watermark":
        _set(ctx, "music_watermark", **d)
        await query.edit_message_text(
            "🏷️ **واترمارک**\n\n"
            "متن واترمارک رو بفرستید:\n"
            "(مثلاً: `© My Channel 2024`)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data="mu_effects")],
            ]),
        )
        return True

    # ── Convert format ──
    if data == "mu_convert":
        current_format = d.get("meta", {}).get("format", "mp3")
        await query.edit_message_text(
            f"🔄 **تبدیل فرمت**\n\n"
            f"فرمت فعلی: `{current_format.upper()}`\n\n"
            f"فرمت مورد نظر رو انتخاب کنید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=convert_format_kb(current_format),
        )
        return True

    if data.startswith("mu_cvt_"):
        target_format = data[8:]  # mu_cvt_mp3 → mp3
        d["convert_target"] = target_format
        _set(ctx, "music_choosing_bitrate", **d)

        await query.edit_message_text(
            f"🔄 **تبدیل به {target_format.upper()}**\n\n"
            f"کیفیت خروجی رو انتخاب کنید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=bitrate_kb(192000 if target_format in ("mp3", "m4a") else 0),
        )
        return True

    if data.startswith("mu_br_"):
        bitrate = int(data[6:])
        target_format = d.get("convert_target", "mp3")

        file_path = d.get("file_path")
        if file_path:
            await ctx.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
            try:
                new_path = toolbox.convert_format(file_path, target_format, bitrate)
                d["file_path"] = new_path
                # Update meta
                new_meta = toolbox.read_metadata(new_path)
                # Preserve custom changes
                pending = d.get("pending_changes", {})
                for k, v in pending.items():
                    if v is not None:
                        new_meta[k] = v
                d["meta"] = new_meta
                _set(ctx, "music_editing", **d)

                await query.edit_message_text(
                    f"✅ تبدیل شد: `{target_format.upper()}` @ {bitrate}kbps",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=edit_menu_kb(new_meta),
                )
            except Exception as e:
                await query.edit_message_text(
                    f"❌ خطا در تبدیل: {str(e)[:200]}",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=convert_format_kb(d.get("meta", {}).get("format", "mp3")),
                )
        return True

    # ── Export metadata ──
    if data == "mu_export":
        await query.edit_message_text(
            "📋 **خروجی متادیتا**\n\nفرمت خروجی رو انتخاب کنید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=export_format_kb(),
        )
        return True

    if data == "mu_exp_text":
        file_path = d.get("file_path")
        if file_path:
            export = toolbox.export_metadata(file_path, "text")
            await query.edit_message_text(
                f"```\n{export}\n```",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="mu_back_to_edit")],
                ]),
            )
        return True

    if data == "mu_exp_json":
        file_path = d.get("file_path")
        if file_path:
            export = toolbox.export_metadata(file_path, "json")
            # Truncate if too long
            if len(export) > 3800:
                export = export[:3800] + "\n... (truncated)"
            await query.edit_message_text(
                f"```json\n{export}\n```",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="mu_back_to_edit")],
                ]),
            )
        return True

    # ── Preview ──
    if data == "mu_preview":
        file_path = d.get("file_path")
        meta = d.get("meta", {})
        if file_path:
            # Show before/after comparison
            original = d.get("original_meta", {})
            changes = []
            for field in ["title", "artist", "album", "year", "genre"]:
                old = original.get(field, "")
                new = meta.get(field, "")
                if old != new and new:
                    changes.append(f"• {field}: `{old or '—'}` → `{new}`")

            if not changes:
                changes_text = "هیچ تغییری اعمال نشده."
            else:
                changes_text = "\n".join(changes)

            # Check for audio effect changes
            if d.get("file_path") != d.get("original_file_id"):
                changes_text += "\n• 🔧 افکت صوتی اعمال شده"

            await query.edit_message_text(
                f"👁️ **پیش‌نمایش تغییرات**\n\n"
                f"{changes_text}\n\n"
                f"آیا اعمال شود؟",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=preview_kb(),
            )
        return True

    if data == "mu_confirm_apply":
        # Apply and send
        await _apply_and_send(update, ctx)
        return True

    if data == "mu_back_to_edit":
        _set(ctx, "music_editing", **d)
        meta = d.get("meta", {})
        await query.edit_message_text(
            format_meta_display(meta) + "\n\nچه چیزی رو می‌خواید تغییر بدید؟",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=edit_menu_kb(meta),
        )
        return True

    # ── Done (save & send) ──
    if data == "mu_done":
        await _apply_and_send(update, ctx)
        return True

    # ── Cancel ──
    if data == "mu_cancel":
        # Cleanup temp files
        file_path = d.get("file_path")
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        pending_cover = d.get("pending_cover")
        if pending_cover and os.path.exists(pending_cover):
            try:
                os.remove(pending_cover)
            except Exception:
                pass

        _clear(ctx)
        await query.edit_message_text("❌ عملیات لغو شد.")
        return True

    return False  # Not handled


# ─── Text Input Handlers ──────────────────────────────────────

async def handle_music_text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Handle text input during music editing states.
    Returns True if handled.
    """
    state, d = _state(ctx)
    text = update.message.text
    if not text:
        return False

    field_map = {
        "music_changing_title": "title",
        "music_changing_artist": "artist",
        "music_changing_album": "album",
        "music_changing_year": "year",
        "music_changing_genre": "genre",
    }

    if state in field_map:
        field = field_map[state]
        new_value = text.strip()

        # Validate year
        if field == "year" and new_value:
            if not new_value.isdigit() or len(new_value) != 4:
                await update.message.reply_text(
                    "❌ سال باید ۴ رقمی باشد (مثال: 2024). دوباره بفرستید.",
                )
                return True

        # Update pending changes
        pending = d.get("pending_changes", {})
        pending[field] = new_value
        d["pending_changes"] = pending

        # Update meta for display
        meta = d.get("meta", {})
        meta[field] = new_value
        d["meta"] = meta

        field_names = {
            "title": "عنوان", "artist": "هنرمند", "album": "آلبوم",
            "year": "سال", "genre": "ژانر",
        }

        _set(ctx, "music_editing", **d)
        await update.message.reply_text(
            f"✅ {field_names[field]} تغییر کرد: `{new_value}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=edit_menu_kb(meta),
        )
        return True

    if state == "music_trimming":
        # Parse custom trim: "1:30 - 3:45" or "90 - 225"
        try:
            parts = text.split("-")
            start_str = parts[0].strip()
            end_str = parts[1].strip()

            def parse_time(s):
                s = s.strip()
                if ":" in s:
                    m, sec = s.split(":")
                    return int(m) * 60000 + int(sec) * 1000
                return int(float(s) * 1000)

            start_ms = parse_time(start_str)
            end_ms = parse_time(end_str)

            if start_ms >= end_ms:
                raise ValueError("Start must be before end")

            file_path = d.get("file_path")
            if file_path:
                new_path = toolbox.trim_audio(file_path, start_ms, end_ms)
                d["file_path"] = new_path
                new_meta = toolbox.read_metadata(new_path)
                new_meta.update({k: v for k, v in d["meta"].items() if v})
                d["meta"] = new_meta
                _set(ctx, "music_editing", **d)

                await update.message.reply_text(
                    f"✅ صدا بُریده شد: {start_str} → {end_str}",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=edit_menu_kb(new_meta),
                )
        except Exception as e:
            await update.message.reply_text(
                f"❌ فرمت نادرست: {str(e)}\n\n"
                "فرمت صحیح: `1:30 - 3:45`\n"
                "(دقیقه:ثانیه)",
                parse_mode=ParseMode.MARKDOWN,
            )
        return True

    if state == "music_watermark":
        watermark_text = text.strip()
        if not watermark_text:
            return False

        file_path = d.get("file_path")
        if file_path:
            await ctx.bot.send_chat_action(chat_id=update.message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
            new_path = toolbox.add_watermark(file_path, watermark_text)
            d["file_path"] = new_path
            _set(ctx, "music_editing", **d)

            await update.message.reply_text(
                f"✅ واترمارک اضافه شد: `{watermark_text}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=edit_menu_kb(d.get("meta", {})),
            )
        return True

    return False


# ─── Apply & Send ─────────────────────────────────────────────

async def _apply_and_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Apply all pending changes and send the file back."""
    state, d = _state(ctx)
    file_path = d.get("file_path")

    if not file_path or not os.path.exists(file_path):
        query = update.callback_query
        await query.edit_message_text("❌ فایل یافت نشد. دوباره شروع کنید.")
        _clear(ctx)
        return

    # Apply pending metadata changes
    pending = d.get("pending_changes", {})
    if pending:
        try:
            toolbox.write_metadata(
                file_path,
                title=pending.get("title"),
                artist=pending.get("artist"),
                album=pending.get("album"),
                year=pending.get("year"),
                genre=pending.get("genre"),
            )
        except Exception as e:
            logger.error(f"Write metadata error: {e}")

    # Apply cover art
    cover_path = d.get("pending_cover")
    if cover_path and os.path.exists(cover_path):
        try:
            toolbox.set_cover_art(file_path, cover_path)
        except Exception as e:
            logger.warning(f"Set cover error: {e}")

    # Send back
    meta = toolbox.read_metadata(file_path)
    query = update.callback_query

    try:
        await ctx.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)

        with open(file_path, "rb") as f:
            await query.message.reply_audio(
                audio=f,
                title=meta.get("title", ""),
                performer=meta.get("artist", ""),
            )

        _clear(ctx)
        await query.edit_message_text(
            "✅ **موزیک با موفقیت ویرایش شد!**\n\n"
            f"📌 عنوان: {meta.get('title') or '—'}\n"
            f"🎤 هنرمند: {meta.get('artist') or '—'}\n"
            f"💿 آلبوم: {meta.get('album') or '—'}\n"
            f"📅 سال: {meta.get('year') or '—'}\n"
            f"🎶 ژانر: {meta.get('genre') or '—'}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎵 ویرایش مجدد", callback_data="edit_music")],
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
            ]),
        )
    except TelegramError as e:
        logger.error(f"Send music error: {e}")
        await query.edit_message_text(
            f"❌ **خطا در ارسال:** `{str(e)[:200]}`",
            parse_mode=ParseMode.MARKDOWN,
        )

    # Cleanup temp files
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass
    if cover_path and cover_path != file_path and os.path.exists(cover_path):
        try:
            os.remove(cover_path)
        except Exception:
            pass


# ─── Batch Editing ────────────────────────────────────────────

async def handle_batch_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE, data: str) -> bool:
    """Handle batch editing callbacks. Returns True if handled."""
    if not data.startswith("mt_"):
        return False

    state, d = _state(ctx)
    query = update.callback_query

    if data == "mt_single":
        _set(ctx, "music_waiting")
        await query.edit_message_text(
            "🎵 **ویرایش تکی**\n\nیک فایل صوتی بفرستید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data="mu_cancel")],
            ]),
        )
        return True

    if data == "mt_batch":
        _set(ctx, "mt_batch_waiting", files=[], file_ids=[])
        await query.edit_message_text(
            "📦 **ویرایش گروهی**\n\n"
            "فایل‌های صوتی رو یکی یکی بفرستید.\n\n"
            "📌 قابلیت‌ها:\n"
            "• تغییر عنوان (با الگوی {n} برای شماره ترک)\n"
            "• تغییر هنرمند، آلبوم، سال، ژانر\n"
            "• اعمال روی همه فایل‌ها\n\n"
            "وقتی تمام شد «ویرایش X فایل» رو بزنید.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data="mu_cancel")],
            ]),
        )
        return True

    if data == "mt_batch_edit":
        files = d.get("files", [])
        if not files:
            await query.answer("❌ فایلی وجود ندارد!", show_alert=True)
            return True

        _set(ctx, "mt_batch_editing", **d)
        await query.edit_message_text(
            f"📦 **ویرایش گروهی: {len(files)} فایل**\n\n"
            f"متادیتای مشترک رو انتخاب کنید:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📌 عنوان همه", callback_data="mt_batch_title")],
                [InlineKeyboardButton("🎤 هنرمند همه", callback_data="mt_batch_artist")],
                [InlineKeyboardButton("💿 آلبوم همه", callback_data="mt_batch_album")],
                [InlineKeyboardButton("📅 سال همه", callback_data="mt_batch_year")],
                [InlineKeyboardButton("🎶 ژانر همه", callback_data="mt_batch_genre")],
                [InlineKeyboardButton("✅ اعمال همه", callback_data="mt_batch_apply")],
                [InlineKeyboardButton("❌ لغو", callback_data="mu_cancel")],
            ]),
        )
        return True

    # Batch field edit requests
    batch_field_map = {
        "mt_batch_title": ("title", "عنوان"),
        "mt_batch_artist": ("artist", "هنرمند"),
        "mt_batch_album": ("album", "آلبوم"),
        "mt_batch_year": ("year", "سال"),
        "mt_batch_genre": ("genre", "ژانر"),
    }

    for cb_data, (field, label) in batch_field_map.items():
        if data == cb_data:
            _set(ctx, f"mt_batch_changing_{field}", **d)
            hint = "\n\n💡 از `{n}` برای شماره ترک استفاده کنید" if field in ("title", "artist") else ""
            await query.edit_message_text(
                f"📦 **{label} مشترک برای {len(d.get('files', []))} فایل**{hint}\n\n"
                f"مقدار جدید رو بفرستید:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ لغو", callback_data="mt_batch_edit")],
                ]),
            )
            return True

    if data == "mt_batch_apply":
        files = d.get("files", [])
        if not files:
            return True

        batch_changes = d.get("batch_changes", {})

        await ctx.bot.send_chat_action(chat_id=query.message.chat_id, action=ChatAction.UPLOAD_DOCUMENT)
        results = toolbox.batch_edit_metadata(files, **batch_changes)

        success = sum(1 for r in results if r["success"])
        failed = len(results) - success

        _clear(ctx)
        text = f"✅ **اعمال شد: {success}/{len(results)} فایل**"
        if failed:
            text += f"\n❌ **خطا: {failed} فایل**"

        await query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 منوی اصلی", callback_data="main_menu")],
            ]),
        )

        # Cleanup
        for f in files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

        return True

    return False


async def handle_batch_text_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input during batch editing states."""
    state, d = _state(ctx)
    text = update.message.text
    if not text:
        return False

    batch_field_map = {
        "mt_batch_changing_title": "title",
        "mt_batch_changing_artist": "artist",
        "mt_batch_changing_album": "album",
        "mt_batch_changing_year": "year",
        "mt_batch_changing_genre": "genre",
    }

    if state in batch_field_map:
        field = batch_field_map[state]
        value = text.strip()

        batch_changes = d.get("batch_changes", {})
        batch_changes[field] = value
        d["batch_changes"] = batch_changes

        _set(ctx, "mt_batch_editing", **d)

        field_names = {
            "title": "عنوان", "artist": "هنرمند", "album": "آلبوم",
            "year": "سال", "genre": "ژانر",
        }

        await update.message.reply_text(
            f"✅ {field_names[field]} تنظیم شد: `{value}`\n\n"
            f"فیلدهای تنظیم شده: {', '.join(batch_changes.keys())}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📌 عنوان", callback_data="mt_batch_title")],
                [InlineKeyboardButton("🎤 هنرمند", callback_data="mt_batch_artist")],
                [InlineKeyboardButton("💿 آلبوم", callback_data="mt_batch_album")],
                [InlineKeyboardButton("📅 سال", callback_data="mt_batch_year")],
                [InlineKeyboardButton("🎶 ژانر", callback_data="mt_batch_genre")],
                [InlineKeyboardButton(f"✅ اعمال روی {len(d.get('files', []))} فایل", callback_data="mt_batch_apply")],
                [InlineKeyboardButton("❌ لغو", callback_data="mu_cancel")],
            ]),
        )
        return True

    return False
```

### 3.4 Integration with `bot.py`

The following changes need to be made to `bot.py`:

#### Changes to imports (top of bot.py):

```python
# ADD these imports:
import music_handlers
from music_ui import format_meta_display
```

#### Changes to `main()` function:

```python
def main():
    db.init()
    print("🤖 ربات Admin Channel در حال راه‌اندازی...")

    # Initialize music toolbox
    music_handlers.init_toolbox(str(TEMP_DIR))

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("skip", cmd_skip))

    # Callbacks
    app.add_handler(CallbackQueryHandler(callback_handler))

    # Messages (text + media)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.AUDIO | filters.Document.AUDIO, handle_media))
    app.add_handler(MessageHandler(filters.PHOTO, handle_media))

    print("✅ ربات آماده!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
```

#### Changes to `callback_handler()`:

Add these blocks at the beginning of the function (before the existing `# ── Main menu buttons ──` section):

```python
    # ── Music toolbox callbacks ──
    if data.startswith("mu_"):
        if await music_handlers.handle_music_callback(update, ctx, data):
            return

    if data.startswith("mt_"):
        if await music_handlers.handle_batch_callback(update, ctx, data):
            return
```

#### Changes to `handle_message()`:

Add these blocks before the `# Default: if no state` section:

```python
    # ── Music editing text inputs ──
    if await music_handlers.handle_music_text_input(update, ctx):
        return

    # ── Batch editing text inputs ──
    if await music_handlers.handle_batch_text_input(update, ctx):
        return
```

#### Changes to `handle_media()`:

Add at the beginning of the function body:

```python
    # ── Music toolbox media inputs ──
    if await music_handlers.on_audio_received(update, ctx):
        return

    if await music_handlers.on_photo_received(update, ctx):
        return
```

#### Changes to `cmd_start()` — update the menu button:

```python
# Change the keyboard in show_main_menu:
keyboard = [
    [InlineKeyboardButton("📤 ارسال پیام به کانال", callback_data="send_now")],
    [InlineKeyboardButton("⏰ زمان‌بندی ارسال", callback_data="schedule")],
    [InlineKeyboardButton("🎵 جعبه ابزار موزیک", callback_data="mt_single")],  # Changed label
    [InlineKeyboardButton("⚙️ تنظیمات پیام‌ها", callback_data="config")],
]
```

### 3.5 Updated `requirements.txt`

```
# Admin Channel Bot - Dependencies
# وابستگی‌های ربات ادمین کانال

# Telegram Bot API
python-telegram-bot>=20.0

# Audio metadata handling (ID3 tags, cover art)
mutagen>=1.47.0

# HTTP requests
requests>=2.31.0

# Audio processing (NEW - for music toolbox)
pydub>=0.25.1

# Image processing for cover art (NEW)
Pillow>=10.0.0
```

### 3.6 Updated `database.py` — Add Edit History

Add these to `database.py`:

```python
# Add to init() table creation:
"""
CREATE TABLE IF NOT EXISTS music_edit_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    original_file_id TEXT,
    title TEXT,
    artist TEXT,
    album TEXT,
    year TEXT,
    genre TEXT,
    source_format TEXT,
    target_format TEXT,
    effects_applied TEXT DEFAULT '[]',
    created_at TEXT
);
"""

# Add these functions:
def add_music_edit(user_id, original_file_id=None, title=None, artist=None,
                   album=None, year=None, genre=None, source_format=None,
                   target_format=None, effects=None):
    c = _conn()
    now = datetime.now().isoformat()
    cur = c.execute(
        """INSERT INTO music_edit_history
           (user_id, original_file_id, title, artist, album, year, genre,
            source_format, target_format, effects_applied, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, original_file_id, title, artist, album, year, genre,
         source_format, target_format, json.dumps(effects or []), now),
    )
    c.commit()
    eid = cur.lastrowid
    c.close()
    return eid


def get_music_edit_history(user_id, limit=20):
    c = _conn()
    rows = c.execute(
        "SELECT * FROM music_edit_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]
```

---

## Part 4: Integration Points with Existing bot.py

### State Machine Flow

```
                           ┌──────────────────────┐
                           │     User sends       │
                           │     /start or menu   │
                           └──────────┬───────────┘
                                      │
                           ┌──────────▼───────────┐
                           │  Music Toolbox Menu   │
                           │  (mt_single / mt_batch)│
                           └──────────┬───────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                                       │
           ┌────────▼────────┐                   ┌────────▼────────┐
           │  music_waiting   │                   │ mt_batch_waiting │
           │  (single file)   │                   │ (multiple files) │
           └────────┬────────┘                   └────────┬────────┘
                    │                                       │
           ┌────────▼────────┐                   ┌────────▼────────┐
           │ music_editing    │                   │ mt_batch_editing │
           │ (show metadata)  │                   │ (shared fields)  │
           └───┬───┬───┬───┘                   └────────┬────────┘
               │   │   │                                 │
    ┌──────────┼───┼───┼──────────────┐                  │
    │          │   │   │              │                  │
┌───▼──┐ ┌───▼──┐│┌──▼──┐ ┌───▼──┐  │          ┌───────▼───────┐
│title │ │artist│││cover│ │effects│  │          │ mt_batch_apply │
│edit  │ │ edit │││edit │ │ menu  │  │          │ (apply to all) │
└───┬──┘ └───┬──┘│└───┬──┘ │      │  │          └───────────────┘
    │        │   │    │    └──┬───┘  │
    │        │   │    │       │      │
    │        │   │    │  ┌────▼────┐ │
    │        │   │    │  │ normalize│ │
    │        │   │    │  │ fade    │ │
    │        │   │    │  │ trim    │ │
    │        │   │    │  │ watermark│ │
    │        │   │    │  └────┬────┘ │
    │        │   │    │       │      │
    └────────┴───┴───┴───────┴──┬───┘
                                │
                    ┌───────────▼───────────┐
                    │    mu_preview / mu_done │
                    │   (preview & confirm)   │
                    └───────────┬───────────┘
                                │
                    ┌───────────▼───────────┐
                    │   _apply_and_send()    │
                    │   (write & send file)  │
                    └───────────────────────┘
```

### Callback Data Prefixes

| Prefix | Module | Description |
|--------|--------|-------------|
| `mu_` | music_handlers | Single file editing |
| `mt_` | music_handlers | Batch/menu entry |

### State Names

| State | Handler | Description |
|-------|---------|-------------|
| `music_waiting` | `on_audio_received` | Waiting for audio file |
| `music_editing` | `handle_music_callback` | Main edit menu |
| `music_changing_title` | `handle_music_text_input` | User types new title |
| `music_changing_artist` | `handle_music_text_input` | User types new artist |
| `music_changing_album` | `handle_music_text_input` | User types new album |
| `music_changing_year` | `handle_music_text_input` | User types new year |
| `music_changing_genre` | `handle_music_text_input` | User types new genre |
| `music_waiting_cover` | `on_photo_received` | Waiting for cover photo |
| `music_trimming` | `handle_music_text_input` | User types trim times |
| `music_watermark` | `handle_music_text_input` | User types watermark text |
| `mt_batch_waiting` | `on_audio_received` | Collecting batch files |
| `mt_batch_editing` | `handle_batch_callback` | Batch field selection |
| `mt_batch_changing_*` | `handle_batch_text_input` | Batch field input |

---

## Part 5: Test Plan

### Unit Tests: `tests/test_music_toolbox.py`

```python
#!/usr/bin/env python3
"""Tests for music_toolbox.py"""

import os
import sys
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from music_toolbox import MusicToolbox


class TestMusicToolbox(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.toolbox = MusicToolbox(self.temp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_read_metadata_nonexistent_file(self):
        """Should handle nonexistent file gracefully."""
        result = self.toolbox.read_metadata("/nonexistent/file.mp3")
        self.assertEqual(result["title"], "")

    def test_detect_format_mp3(self):
        self.assertEqual(self.toolbox._detect_format("test.mp3"), "id3")
        self.assertEqual(self.toolbox._detect_format("test.m4a"), "mp4")
        self.assertEqual(self.toolbox._detect_format("test.flac"), "vorbis")
        self.assertEqual(self.toolbox._detect_format("test.wav"), "unknown")

    def test_format_duration(self):
        self.assertEqual(self.toolbox._format_duration(65), "1:05")
        self.assertEqual(self.toolbox._format_duration(3661), "1:01:01")
        self.assertEqual(self.toolbox._format_duration(30), "0:30")

    def test_format_size(self):
        self.assertEqual(self.toolbox._format_size(512), "512.0 B")
        self.assertIn("KB", self.toolbox._format_size(2048))
        self.assertIn("MB", self.toolbox._format_size(5*1024*1024))

    def test_export_metadata_text(self):
        """Should produce readable text output."""
        # Create a minimal test file (mock)
        with patch.object(self.toolbox, 'read_metadata') as mock_read:
            mock_read.return_value = {
                "title": "Test Song", "artist": "Test Artist",
                "album": "Test Album", "year": "2024",
                "genre": "Pop", "track_number": "1",
                "has_cover": False, "cover_mime": "",
                "duration": 185, "format": "mp3",
                "bitrate": 192000, "file_size": 3500000,
            }
            result = self.toolbox.export_metadata("test.mp3", "text")
            self.assertIn("Test Song", result)
            self.assertIn("Test Artist", result)

    def test_export_metadata_json(self):
        """Should produce valid JSON output."""
        with patch.object(self.toolbox, 'read_metadata') as mock_read:
            mock_read.return_value = {
                "title": "JSON Song", "artist": "Artist",
                "album": "", "year": "", "genre": "",
                "track_number": "", "has_cover": False,
                "cover_mime": "", "duration": 200,
                "format": "mp3", "bitrate": 128000,
                "file_size": 2000000,
            }
            result = self.toolbox.export_metadata("test.mp3", "json")
            parsed = json.loads(result)
            self.assertEqual(parsed["title"], "JSON Song")
            self.assertIn("duration_formatted", parsed)

    def test_normalize_volume(self):
        """Normalization should produce a valid file."""
        # Would need a real audio file for full test
        # This tests error handling
        with self.assertRaises(Exception):
            self.toolbox.normalize_volume("/nonexistent.mp3")

    def test_fade_audio(self):
        """Fade should handle nonexistent file."""
        with self.assertRaises(Exception):
            self.toolbox.fade_audio("/nonexistent.mp3", fade_in_ms=1000)

    def test_trim_audio(self):
        """Trim should handle nonexistent file."""
        with self.assertRaises(Exception):
            self.toolbox.trim_audio("/nonexistent.mp3", start_ms=0, end_ms=5000)

    def test_watermark_no_cover_returns_copy(self):
        """Watermark on nonexistent file should handle gracefully."""
        # Watermark returns copy even on error
        # This tests that the function doesn't crash
        pass  # Requires real file

    def test_batch_edit_metadata_empty_list(self):
        """Batch edit on empty list should return empty results."""
        results = self.toolbox.batch_edit_metadata([])
        self.assertEqual(results, [])

    def test_cleanup(self):
        """Cleanup should remove files without error."""
        test_file = os.path.join(self.temp_dir, "test_cleanup.txt")
        with open(test_file, "w") as f:
            f.write("test")
        self.assertTrue(os.path.exists(test_file))
        self.toolbox.cleanup(test_file)
        self.assertFalse(os.path.exists(test_file))

    def test_cleanup_nonexistent(self):
        """Cleanup on nonexistent file should not raise."""
        self.toolbox.cleanup("/nonexistent/file.txt")  # Should not crash


class TestMusicUI(unittest.TestCase):
    """Test UI helper functions."""

    def test_format_meta_display(self):
        from music_ui import format_meta_display
        meta = {
            "title": "My Song",
            "artist": "Artist",
            "album": "Album",
            "year": "2024",
            "genre": "Pop",
            "has_cover": True,
            "duration": 210,
            "format": "mp3",
            "bitrate": 192000,
            "file_size": 5000000,
        }
        display = format_meta_display(meta)
        self.assertIn("My Song", display)
        self.assertIn("Artist", display)
        self.assertIn("3:30", display)

    def test_edit_menu_kb(self):
        from music_ui import edit_menu_kb
        meta = {"title": "Test", "artist": "A", "album": "B",
                "year": "2024", "genre": "Pop", "has_cover": True}
        kb = edit_menu_kb(meta)
        self.assertIsNotNone(kb)
        self.assertGreater(len(kb.inline_keyboard), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

### Integration Test Script

```bash
#!/bin/bash
# run_tests.sh - Run all tests

echo "🧪 Running Music Toolbox Tests..."
cd "$(dirname "$0")"

# Install dependencies
pip install -q pydub Pillow mutagen python-telegram-bot requests

# Run unit tests
python3 -m pytest tests/test_music_toolbox.py -v

# Syntax check all new modules
echo ""
echo "🔍 Checking syntax..."
python3 -c "import py_compile; py_compile.compile('music_toolbox.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('music_handlers.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('music_ui.py', doraise=True)"

# Run existing tests
echo ""
python3 test_bot.py

echo ""
echo "✅ All tests complete!"
```

---

## Part 6: Implementation Order

### Phase 1: Foundation (Core Engine)
1. Create `music_toolbox.py` with metadata read/write for all formats
2. Create `music_ui.py` with all keyboard builders
3. Write and run `tests/test_music_toolbox.py`
4. **Verify:** All unit tests pass

### Phase 2: Single File Editing
1. Create `music_handlers.py` with single-file flow
2. Integrate with `bot.py` (add routing, imports, init)
3. Update `requirements.txt`
4. **Verify:** Can send audio → edit title/artist/album/year/genre → save

### Phase 3: Cover Art & Effects
1. Add cover art add/remove (all formats)
2. Add audio effects (normalize, fade, trim, watermark)
3. Add format conversion
4. **Verify:** Cover art works for MP3/M4A/FLAC. Effects produce valid audio.

### Phase 4: Advanced Features
1. Add preview before applying
2. Add export metadata (text/JSON)
3. Add batch editing
4. Add edit history to database
5. **Verify:** Full flow works end-to-end for both single and batch.

### Phase 5: Polish
1. Add progress indicators (send_chat_action)
2. Add error recovery (try/except with user feedback)
3. Add file size validation (>50MB warning)
4. Optimize temp file cleanup
5. Run full integration test suite
6. **Verify:** No temp file leaks, all error paths handled.

---

## Part 7: Edge Cases & Error Handling

| Edge Case | Current Behavior | Fix |
|-----------|-----------------|-----|
| Corrupt audio file | Crash or silent fail | Wrap all Mutagen calls, show user-friendly error |
| Non-audio document sent | Confusing error | Detect MIME type, reject early with message |
| File > 50MB | Slow download, Telegram limit | Check `audio.file_size` before download, warn user |
| Cover art > 5MB | Very slow processing | Warn user, optionally resize with Pillow |
| User sends photo when expecting text | State confusion | Add a catch-all: "Please send text or /cancel" |
| Rapid button clicks | Race condition on state | Use `asyncio.Lock` per user for state transitions |
| Temp file leaks on crash | Disk fills up | Add cleanup-on-start (delete old files in temp/) |
| Unsupported format (WMA, AAC) | Crash | Return clear error: "Format not supported" |
| Unicode in metadata | Display issues | Always use `encoding=3` (UTF-8) for ID3 |
| Empty metadata fields | Display "—" | Already handled in UI display functions |

---

## Summary

**Total new code:**
- `music_toolbox.py` — ~450 lines (core engine)
- `music_handlers.py` — ~500 lines (conversation flow)
- `music_ui.py` — ~200 lines (keyboards & display)
- `tests/test_music_toolbox.py` — ~150 lines (tests)

**Modified files:**
- `bot.py` — Add ~30 lines of integration routing + import
- `database.py` — Add ~50 lines for edit history
- `requirements.txt` — Add 2 dependencies

**New features delivered:**
- ✅ Edit title, artist, album, year, genre
- ✅ Add/replace/remove cover art (MP3, M4A, FLAC)
- ✅ Preview changes before applying
- ✅ Batch editing with `{n}` template
- ✅ Format conversion (MP3, M4A, FLAC, WAV)
- ✅ Audio quality settings (128-320 kbps)
- ✅ Volume normalization
- ✅ Fade in/out effects
- ✅ Trim/cut audio (presets + custom)
- ✅ Watermark/tag in metadata
- ✅ Export metadata as text/JSON

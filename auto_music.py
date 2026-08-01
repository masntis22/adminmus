"""
Auto Music - تشخیص خودکار مود و هشتگ‌ها
Automatic mood detection and hashtag generation for music

Features / امکانات:
- Analyze audio features (tempo, energy, loudness)
  تحلیل ویژگی‌های صوتی (تمپو، انرژی، بلندی)
- Detect mood (happy, sad, energetic, calm, romantic, etc.)
  تشخیص مود (شاد، غمگین، پرانرژی، آرام، عاشقانه و...)
- Generate hashtags in English and Persian
  تولید هشتگ به انگلیسی و فارسی
"""

import subprocess
import json
import re
import logging
from typing import Dict, List, Tuple, Optional

logger = logging.getLogger(__name__)

# Mood definitions with keywords
MOODS = {
    "happy": {
        "en": "happy",
        "fa": "شاد",
        "hashtags_en": ["#happy", "#joy", "#upbeat", "#feelgood", "#positive"],
        "hashtags_fa": ["#شاد", "#شادی", "#انرژی_مثبت", "#حس_خوب"],
        "tempo_range": (100, 160),
        "energy_range": (0.5, 1.0),
    },
    "sad": {
        "en": "sad",
        "fa": "غمگین",
        "hashtags_en": ["#sad", "#melancholy", "#emotional", "#heartbreak", "#sorrow"],
        "hashtags_fa": ["#غمگین", "#احساسی", "#دلتنگی", "#غم"],
        "tempo_range": (60, 100),
        "energy_range": (0.0, 0.4),
    },
    "energetic": {
        "en": "energetic",
        "fa": "پرانرژی",
        "hashtags_en": ["#energetic", "#powerful", "#workout", "#dance", "#pump"],
        "hashtags_fa": ["#پرانرژی", "#رقص", "#ورزش", "#انرژی"],
        "tempo_range": (120, 200),
        "energy_range": (0.7, 1.0),
    },
    "calm": {
        "en": "calm",
        "fa": "آرام",
        "hashtags_en": ["#calm", "#relax", "#peaceful", "#chill", "#soothing"],
        "hashtags_fa": ["#آرام", "#آرامش", "#relaxing", "#مدیتیشن"],
        "tempo_range": (60, 100),
        "energy_range": (0.0, 0.3),
    },
    "romantic": {
        "en": "romantic",
        "fa": "عاشقانه",
        "hashtags_en": ["#romantic", "#love", "#romance", "#lovesong", "#sweet"],
        "hashtags_fa": ["#عاشقانه", "#عشق", "#love", "#احساسی"],
        "tempo_range": (70, 120),
        "energy_range": (0.2, 0.6),
    },
    "aggressive": {
        "en": "aggressive",
        "fa": "خشن",
        "hashtags_en": ["#aggressive", "#hard", "#intense", "#metal", "#rock"],
        "hashtags_fa": ["#خشن", "#هارد", "#متال", "#راک"],
        "tempo_range": (100, 180),
        "energy_range": (0.8, 1.0),
    },
    "chill": {
        "en": "chill",
        "fa": "چیل",
        "hashtags_en": ["#chill", "#lofi", "#mellow", "#easygoing", "#smooth"],
        "hashtags_fa": ["#چیل", "#لوفای", "#آرام", "#نرم"],
        "tempo_range": (80, 120),
        "energy_range": (0.2, 0.5),
    },
}

# Genre detection patterns
GENRE_PATTERNS = {
    "pop": {"en": "pop", "fa": "پاپ", "hashtags": ["#pop", "#پاپ", "#popmusic"]},
    "rock": {"en": "rock", "fa": "راک", "hashtags": ["#rock", "#راک", "#rockmusic"]},
    "hiphop": {"en": "hip-hop", "fa": "هیپ‌هاپ", "hashtags": ["#hiphop", "#هیپهاپ", "#rap", "#رپ"]},
    "electronic": {"en": "electronic", "fa": "الکترونیک", "hashtags": ["#electronic", "#الکترونیک", "#edm", "#edm"]},
    "jazz": {"en": "jazz", "fa": "جاز", "hashtags": ["#jazz", "#جاز", "#jazzmusic"]},
    "classical": {"en": "classical", "fa": "کلاسیک", "hashtags": ["#classical", "#کلاسیک"]},
    "folk": {"en": "folk", "fa": "فولکلور", "hashtags": ["#folk", "#فولکلور", "#local"]},
    "rnb": {"en": "R&B", "fa": "آر اند بی", "hashtags": ["#rnb", "#r&b", "#آراندبی"]},
    "reggae": {"en": "reggae", "fa": "رگی", "hashtags": ["#reggae", "#رگی"]},
    "indie": {"en": "indie", "fa": "ایندی", "hashtags": ["#indie", "#ایندی"]},
}


class AutoMusic:
    """Auto music analysis and hashtag generation
    تحلیل خودکار موزیک و تولید هشتگ"""

    def __init__(self):
        pass

    def analyze_audio(self, file_path: str) -> Dict:
        """
        Analyze audio file and extract features
        تحلیل فایل صوتی و استخراج ویژگی‌ها

        Returns:
            Dict with tempo, energy, loudness, duration
        """
        result = {
            "tempo": 120,
            "energy": 0.5,
            "loudness": -14.0,
            "duration": 0,
            "format": "",
        }

        try:
            # Use ffmpeg to analyze audio
            cmd = [
                "ffmpeg", "-i", file_path,
                "-af", "ebur128=peak=true",
                "-f", "null", "-"
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            stderr = proc.stderr

            # Parse loudness from stderr
            lufs_match = re.search(r"I:\s*([-\d.]+)\s*LUFS", stderr)
            if lufs_match:
                result["loudness"] = float(lufs_match.group(1))

            # Get duration
            dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", stderr)
            if dur_match:
                h, m, s = int(dur_match.group(1)), int(dur_match.group(2)), int(dur_match.group(3))
                result["duration"] = h * 3600 + m * 60 + s

            # Estimate energy from loudness
            # Normalize loudness to 0-1 range (typical: -30 to 0 LUFS)
            result["energy"] = max(0, min(1, (result["loudness"] + 30) / 30))

            # Estimate tempo from spectral analysis
            result["tempo"] = self._estimate_tempo(file_path)

        except Exception as e:
            logger.warning(f"Audio analysis error: {e}")

        return result

    def _estimate_tempo(self, file_path: str) -> float:
        """Estimate tempo from audio / تخمین تمپو از صدا"""
        try:
            # Use ffmpeg to detect tempo
            cmd = [
                "ffmpeg", "-i", file_path,
                "-af", "tempendo=win_size=512:start_bpm=60:end_bpm=200:measure=none",
                "-f", "null", "-"
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            # Parse tempo from output
            tempo_match = re.search(r"tempo:\s*([\d.]+)", proc.stderr)
            if tempo_match:
                return float(tempo_match.group(1))
        except Exception:
            pass

        return 120.0  # Default tempo

    def detect_mood(self, file_path: str) -> Dict:
        """
        Detect mood of audio file
        تشخیص مود فایل صوتی

        Returns:
            Dict with mood info and hashtags
        """
        features = self.analyze_audio(file_path)
        tempo = features["tempo"]
        energy = features["energy"]

        # Score each mood
        scores = {}
        for mood_name, mood_data in MOODS.items():
            tempo_min, tempo_max = mood_data["tempo_range"]
            energy_min, energy_max = mood_data["energy_range"]

            # Calculate tempo score
            if tempo_min <= tempo <= tempo_max:
                tempo_score = 1.0
            else:
                dist = min(abs(tempo - tempo_min), abs(tempo - tempo_max))
                tempo_score = max(0, 1 - dist / 50)

            # Calculate energy score
            if energy_min <= energy <= energy_max:
                energy_score = 1.0
            else:
                dist = min(abs(energy - energy_min), abs(energy - energy_max))
                energy_score = max(0, 1 - dist / 0.3)

            scores[mood_name] = (tempo_score + energy_score) / 2

        # Get top mood
        best_mood = max(scores, key=scores.get)
        confidence = scores[best_mood]

        # If confidence is low, return "unknown"
        if confidence < 0.3:
            best_mood = "chill"  # Default to chill

        mood_data = MOODS[best_mood]

        return {
            "mood_en": mood_data["en"],
            "mood_fa": mood_data["fa"],
            "confidence": round(confidence, 2),
            "tempo": round(tempo, 1),
            "energy": round(energy, 2),
            "loudness": round(features["loudness"], 1),
            "hashtags_en": mood_data["hashtags_en"],
            "hashtags_fa": mood_data["hashtags_fa"],
        }

    def detect_genre_from_metadata(self, file_path: str) -> Optional[Dict]:
        """
        Try to detect genre from metadata
        تلاش برای تشخیص ژانر از متادیتا
        """
        try:
            from mutagen.easyid3 import EasyID3
            audio = EasyID3(file_path)
            genre = audio.get("genre", [""])[0].lower()

            for genre_key, genre_data in GENRE_PATTERNS.items():
                if genre_key in genre or genre_data["en"].lower() in genre:
                    return genre_data

        except Exception:
            pass

        return None

    def generate_hashtags(self, file_path: str) -> Dict:
        """
        Generate complete hashtag set for music
        تولید مجموعه کامل هشتگ برای موزیک

        Returns:
            Dict with mood, genre, and combined hashtags
        """
        mood = self.detect_mood(file_path)
        genre = self.detect_genre_from_metadata(file_path)

        # Combine hashtags
        all_hashtags_en = list(mood["hashtags_en"])
        all_hashtags_fa = list(mood["hashtags_fa"])

        if genre:
            all_hashtags_en.extend(genre["hashtags"])
            all_hashtags_fa.extend(genre["hashtags"])

        # Remove duplicates while preserving order
        seen_en = set()
        seen_fa = set()
        unique_en = []
        unique_fa = []

        for h in all_hashtags_en:
            h_lower = h.lower()
            if h_lower not in seen_en:
                seen_en.add(h_lower)
                unique_en.append(h)

        for h in all_hashtags_fa:
            if h not in seen_fa:
                seen_fa.add(h)
                unique_fa.append(h)

        return {
            "mood": mood,
            "genre": genre,
            "hashtags_en": unique_en[:8],  # Max 8 English hashtags
            "hashtags_fa": unique_fa[:8],  # Max 8 Persian hashtags
            "all_hashtags": unique_en[:8] + unique_fa[:8],
            "features": {
                "tempo": mood["tempo"],
                "energy": mood["energy"],
                "loudness": mood["loudness"],
            },
        }

    def format_hashtags_text(self, file_path: str) -> str:
        """
        Format hashtags as readable text
        فرمت‌بندی هشتگ‌ها به صورت متن خوانا
        """
        result = self.generate_hashtags(file_path)
        mood = result["mood"]
        genre = result["genre"]

        lines = [
            "🎵 **تحلیل خودکار موزیک**",
            "",
            f"🎭 **مود:** {mood['mood_en']} / {mood['mood_fa']}",
            f"📊 **اطمینان:** {mood['confidence'] * 100:.0f}%",
            f"🎶 **تمپو:** {mood['tempo']} BPM",
            f"⚡ **انرژی:** {mood['energy'] * 100:.0f}%",
            f"🔊 **بلندی:** {mood['loudness']} LUFS",
        ]

        if genre:
            lines.append(f"🎸 **ژانر:** {genre['en']} / {genre['fa']}")

        lines.extend([
            "",
            "🏷️ **هشتگ‌های انگلیسی:**",
            " ".join(result["hashtags_en"]),
            "",
            "🏷️ **هشتگ‌های فارسی:**",
            " ".join(result["hashtags_fa"]),
            "",
            "📋 **کپی کنید:**",
            " ".join(result["all_hashtags"]),
        ])

        return "\n".join(lines)

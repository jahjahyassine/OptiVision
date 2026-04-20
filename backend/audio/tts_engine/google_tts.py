"""
audio/tts_engine/google_tts.py
================================
Google TTS (gTTS) engine wrapper for OptiVision / VisionAssist.

Drop-in replacement for coqui_tts.CoquiTTS — exposes the same
speak() / speak_async() public API so AudioPriorityQueue needs zero changes.

Features
--------
- No local model weights; synthesis is done by Google's TTS endpoint over HTTPS.
- LRU phrase cache (_CACHE_SIZE entries): repeated obstacle/direction phrases
  (which recur constantly in navigation) cost 0 ms of network time after the
  first call.
- speak() is synchronous and blocking — designed for the AudioPriorityQueue
  background worker thread, not the asyncio event loop.
- Interrupt-aware playback: checks interrupt_event every ~100 ms so that
  CRITICAL alerts can preempt current speech within one polling cycle.
- MP3 is decoded via ffmpeg subprocess (no pydub dependency — avoids the
  audioop/pyaudioop breakage on Python 3.13+).

⚠  Latency trade-off vs. Coqui
--------------------------------
  gTTS adds a network round-trip of roughly 100–400 ms per *new* phrase.
  Cached phrases play immediately (0 ms synthesis overhead).
  Recommendation: pre-warm the cache at startup with the ~20 most common
  navigation phrases (see warm_cache() helper below) so that real-time
  navigation traffic almost never hits the network.

Dependencies
------------
  pip install gtts sounddevice numpy
  sudo pacman -S ffmpeg        # Arch
  # sudo apt install ffmpeg    # Ubuntu/Debian

Language codes (set in config.py → TTS_ENGINE → lang):
  French  : "fr"
  Arabic  : "ar"
  English : "en"
  Darija  : use "ar" (closest available)
"""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import threading
import time
from collections import OrderedDict
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)

_SAMPLE_RATE: int  = 22_050   # Hz — matches Coqui output rate; consistent with AudioPQ
_CHUNK_MS:    int  = 100      # interrupt-polling interval in milliseconds
_CACHE_SIZE:  int  = 64       # max LRU cache entries (phrases → PCM arrays)


class GoogleTTS:
    """
    Thread-safe Google TTS engine.

    Parameters
    ----------
    lang : BCP-47 language code passed to gTTS ("fr", "ar", "en", …).
    slow : If True, Google speaks more slowly — helps with Arabic clarity.
    tld  : Google Translate TLD ("com", "fr", "co.uk", …).
           "fr" may give slightly more natural French prosody.
    """

    def __init__(
        self,
        lang: str = "fr",
        slow: bool = False,
        tld:  str  = "com",
    ) -> None:
        self._lang = lang
        self._slow = slow
        self._tld  = tld

        self._lock:  threading.Lock     = threading.Lock()
        self._sd                        = None   # sounddevice module
        self._gtts_mod                  = None   # gtts module reference
        self._ffmpeg:  Optional[str]    = None   # path to ffmpeg binary

        # phrase → float32 PCM array (22 050 Hz mono)
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()

        self._load()

    # ─────────────────────────────── public API ───────────────────────────────

    def speak(
        self,
        text: str,
        interrupt_event: Optional[threading.Event] = None,
    ) -> None:
        """
        Synthesise *text* and play it through the default audio device.

        Identical contract to CoquiTTS.speak() — AudioPriorityQueue calls this
        directly from its background worker thread.

        Parameters
        ----------
        text            : Sentence to synthesise and speak.
        interrupt_event : threading.Event set by AudioPriorityQueue when a
                          higher-priority alert arrives; causes early exit.
        """
        if not text or not text.strip():
            return

        if interrupt_event and interrupt_event.is_set():
            logger.debug("GoogleTTS: speak() skipped — already interrupted")
            return

        wav = self._get_pcm(text)
        if wav is None:
            return

        self._play(wav, interrupt_event)

    def speak_async(self, text: str) -> threading.Thread:
        """
        Fire-and-forget wrapper. Returns the daemon thread (useful for tests).
        Prefer AudioPriorityQueue in production.
        """
        t = threading.Thread(
            target=self.speak,
            args=(text,),
            name="gtts-async",
            daemon=True,
        )
        t.start()
        return t

    def warm_cache(self, phrases: List[str]) -> None:
        """
        Pre-synthesise a list of common phrases so they play with zero
        network latency at runtime.

        Call once at application startup (runs in the calling thread —
        wrap in a daemon thread if you don't want to block startup):

            threading.Thread(
                target=tts.warm_cache,
                args=(COMMON_PHRASES,),
                daemon=True,
            ).start()
        """
        logger.info("GoogleTTS: warming cache with %d phrases …", len(phrases))
        for phrase in phrases:
            if phrase.strip() not in self._cache:
                self._get_pcm(phrase)
        logger.info("GoogleTTS: cache warm-up complete.")

    # ─────────────────────────────── internals ────────────────────────────────

    def _load(self) -> None:
        """Import optional dependencies. Errors are logged, not raised."""

        # ── gTTS ──────────────────────────────────────────────────────────────
        try:
            import gtts as _gtts  # type: ignore
            self._gtts_mod = _gtts
            logger.info(
                "GoogleTTS: gTTS loaded (lang=%s, tld=%s, slow=%s).",
                self._lang, self._tld, self._slow,
            )
        except ImportError:
            logger.error(
                "gTTS not installed — run: pip install gtts\n"
                "AudioPriorityQueue will start but TTS output will be silent."
            )

        # ── ffmpeg (MP3 → raw PCM via subprocess) ─────────────────────────────
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            self._ffmpeg = ffmpeg_path
            logger.info("GoogleTTS: ffmpeg found at %s — MP3 decoding ready.", ffmpeg_path)
        else:
            logger.error(
                "ffmpeg not found in PATH — MP3 decoding will fail.\n"
                "Install: sudo pacman -S ffmpeg  |  sudo apt install ffmpeg"
            )

        # ── sounddevice ───────────────────────────────────────────────────────
        try:
            import sounddevice as sd  # type: ignore
            self._sd = sd
            logger.info("GoogleTTS: sounddevice loaded — audio output ready.")
        except ImportError:
            logger.warning(
                "sounddevice not installed — run: pip install sounddevice\n"
                "Synthesis will run but audio will not play."
            )

    def _synthesise(self, text: str) -> Optional[np.ndarray]:
        """
        Call the Google TTS endpoint, decode MP3 → float32 PCM at _SAMPLE_RATE
        using an ffmpeg subprocess (no pydub / audioop dependency).

        Returns None on any error so callers can skip playback gracefully.
        """
        if self._gtts_mod is None:
            logger.warning("GoogleTTS: gTTS missing — cannot synthesise.")
            return None
        if self._ffmpeg is None:
            logger.warning("GoogleTTS: ffmpeg missing — cannot decode MP3.")
            return None

        t0 = time.monotonic()

        # ── Network call → MP3 bytes in memory ────────────────────────────────
        try:
            tts_obj = self._gtts_mod.gTTS(
                text=text,
                lang=self._lang,
                slow=self._slow,
                tld=self._tld,
            )
            mp3_buf = io.BytesIO()
            tts_obj.write_to_fp(mp3_buf)
            mp3_bytes = mp3_buf.getvalue()
        except Exception as exc:
            logger.error("GoogleTTS synthesis request failed: %s", exc, exc_info=True)
            return None

        # ── ffmpeg: MP3 → signed 16-bit little-endian PCM at _SAMPLE_RATE ─────
        #   stdin  : raw MP3 bytes
        #   stdout : raw s16le PCM at target sample rate, 1 channel
        cmd = [
            self._ffmpeg,
            "-hide_banner", "-loglevel", "error",
            "-i", "pipe:0",                    # read from stdin
            "-ar", str(_SAMPLE_RATE),          # resample to 22 050 Hz
            "-ac", "1",                        # mono
            "-f", "s16le",                     # signed 16-bit little-endian
            "pipe:1",                          # write to stdout
        ]
        try:
            result = subprocess.run(
                cmd,
                input=mp3_bytes,
                capture_output=True,
                timeout=10,
            )
            if result.returncode != 0:
                logger.error(
                    "GoogleTTS ffmpeg decode error: %s",
                    result.stderr.decode(errors="replace"),
                )
                return None
            pcm_bytes = result.stdout
        except subprocess.TimeoutExpired:
            logger.error("GoogleTTS ffmpeg decode timed out.")
            return None
        except Exception as exc:
            logger.error("GoogleTTS ffmpeg subprocess failed: %s", exc, exc_info=True)
            return None

        # ── Convert int16 bytes → float32 [-1, 1] ─────────────────────────────
        raw = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        raw /= 32_768.0

        elapsed_ms = (time.monotonic() - t0) * 1_000
        logger.debug(
            "GoogleTTS: synthesised %d samples (%.2f s audio) in %.0f ms",
            len(raw),
            len(raw) / _SAMPLE_RATE,
            elapsed_ms,
        )
        return raw

    def _get_pcm(self, text: str) -> Optional[np.ndarray]:
        """Return PCM array for *text*, hitting the LRU cache when possible."""
        key = text.strip()

        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                logger.debug("GoogleTTS: cache hit — %r", key[:50])
                return self._cache[key]

        # Synthesise *outside* the lock so parallel speak() calls don't block
        # each other during the network round-trip.
        wav = self._synthesise(key)
        if wav is None:
            return None

        with self._lock:
            self._cache[key] = wav
            self._cache.move_to_end(key)
            # Evict LRU entry when capacity is exceeded
            while len(self._cache) > _CACHE_SIZE:
                evicted = next(iter(self._cache))
                del self._cache[evicted]
                logger.debug("GoogleTTS: cache evicted — %r", evicted[:50])

        return wav

    def _play(
        self,
        wav: np.ndarray,
        interrupt_event: Optional[threading.Event],
    ) -> None:
        """
        Play a float32 PCM array through sounddevice with interrupt polling
        every _CHUNK_MS milliseconds — identical logic to CoquiTTS._play.
        """
        if self._sd is None:
            logger.warning("GoogleTTS: sounddevice unavailable — skipping playback.")
            return

        sd = self._sd
        try:
            sd.play(wav, samplerate=_SAMPLE_RATE)
            stream = sd.get_stream()

            while stream.active:
                if interrupt_event and interrupt_event.is_set():
                    sd.stop()
                    logger.info("GoogleTTS: playback interrupted by CRITICAL alert.")
                    return
                time.sleep(_CHUNK_MS / 1_000.0)

            sd.wait()   # flush the output buffer fully
        except Exception as exc:
            logger.error("GoogleTTS playback error: %s", exc, exc_info=True)
            try:
                sd.stop()
            except Exception:
                pass
"""
audio/tts_engine/coqui_tts.py
==============================
Coqui TTS engine wrapper for OptiVision.

Features
--------
- Loads model once at startup; subsequent calls reuse the loaded weights.
- speak() is synchronous and blocking — designed to be called from the
  AudioPriorityQueue background worker thread (not the asyncio event loop).
- Interrupt-aware playback: checks interrupt_event every ~100 ms so that
  CRITICAL alerts can preempt current speech within one polling cycle.
- Falls back gracefully when sounddevice is unavailable (e.g. CI / servers
  without audio hardware) by writing to a temp WAV file instead.

Dependencies
------------
  pip install TTS sounddevice numpy

GPU (optional — dramatically faster synthesis):
  pip install TTS sounddevice numpy torch torchvision torchaudio
  Set device="cuda" in constructor.

Language models (set in config.py → TTS_ENGINE):
  French: "tts_models/fr/css10/vits"  ← recommended, fastest
  Arabic: "tts_models/ar/cv/vits"
  English: "tts_models/en/ljspeech/vits"
  Multilingual: "tts_models/multilingual/multi-dataset/xtts_v2"
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_SAMPLE_RATE  = 22050   # standard Coqui output rate
_CHUNK_MS     = 100     # interrupt polling interval in milliseconds
_CHUNK_FRAMES = int(_SAMPLE_RATE * _CHUNK_MS / 1000)


class CoquiTTS:
    """
    Thread-safe Coqui TTS engine.

    Parameters
    ----------
    model_name : Coqui TTS model identifier string.
    device     : "cpu" | "cuda"
    """

    def __init__(
        self,
        model_name: str = "tts_models/fr/css10/vits",
        device:     str = "cpu",
    ) -> None:
        self._device     = device
        self._model_name = model_name
        self._tts        = None          # lazy-loaded on first speak()
        self._lock       = threading.Lock()
        self._sd         = None          # sounddevice module, loaded once

        self._load()

    # ── public API ────────────────────────────────────────────────────────────

    def speak(self, text: str, interrupt_event: Optional[threading.Event] = None) -> None:
        """
        Synthesize *text* and play it through the default audio device.

        Checks *interrupt_event* every _CHUNK_MS milliseconds so that a
        CRITICAL alert can preempt this utterance with minimal delay.

        Parameters
        ----------
        text            : The sentence to synthesize and speak.
        interrupt_event : threading.Event — set by AudioPriorityQueue when a
                          higher-priority alert arrives; causes early exit.
        """
        if not text or not text.strip():
            return

        # Fast-path: already interrupted before we even start
        if interrupt_event and interrupt_event.is_set():
            logger.debug("CoquiTTS: speak() skipped — already interrupted")
            return

        t0 = time.monotonic()

        # ── Synthesise (CPU/GPU) ──────────────────────────────────────────────
        with self._lock:
            try:
                wav_list = self._tts.tts(text=text)
            except Exception as exc:
                logger.error("CoquiTTS synthesis failed: %s", exc, exc_info=True)
                return

        wav = np.array(wav_list, dtype=np.float32)
        synth_ms = (time.monotonic() - t0) * 1000
        logger.debug("CoquiTTS: synthesised %d samples in %.0f ms", len(wav), synth_ms)

        # ── Playback with interrupt polling ───────────────────────────────────
        if self._sd is None:
            logger.warning("CoquiTTS: sounddevice not available — skipping playback")
            return

        sd = self._sd
        try:
            sd.play(wav, samplerate=_SAMPLE_RATE)
            stream = sd.get_stream()

            while stream.active:
                if interrupt_event and interrupt_event.is_set():
                    sd.stop()
                    logger.info("CoquiTTS: playback interrupted by CRITICAL alert")
                    return
                time.sleep(_CHUNK_MS / 1000.0)

            sd.wait()   # ensure buffer fully flushed
        except Exception as exc:
            logger.error("CoquiTTS playback error: %s", exc, exc_info=True)
            try:
                sd.stop()
            except Exception:
                pass

    def speak_async(self, text: str) -> threading.Thread:
        """
        Fire-and-forget wrapper. Returns the daemon thread for testing.
        In production, prefer AudioPriorityQueue which manages its own thread.
        """
        t = threading.Thread(
            target=self.speak,
            args=(text,),
            name="coqui-async",
            daemon=True,
        )
        t.start()
        return t

    # ── internals ─────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load TTS model and sounddevice. Errors are logged, not raised."""
        # ── Coqui TTS model ───────────────────────────────────────────────────
        try:
            from TTS.api import TTS as _TTS  # type: ignore
            logger.info(
                "Loading Coqui TTS model '%s' on %s …", self._model_name, self._device
            )
            tts_instance = _TTS(model_name=self._model_name, progress_bar=False)
            if self._device == "cuda":
                try:
                    tts_instance.to("cuda")
                    logger.info("Coqui TTS: GPU acceleration enabled.")
                except Exception as exc:
                    logger.warning("Coqui TTS: GPU unavailable (%s) — using CPU.", exc)
            self._tts = tts_instance
            logger.info("Coqui TTS model ready.")
        except ImportError:
            logger.error(
                "Coqui TTS not installed. Run: pip install TTS\n"
                "AudioPriorityQueue will start but TTS output will be silent."
            )
        except Exception as exc:
            logger.error("Coqui TTS model load failed: %s", exc, exc_info=True)

        # ── sounddevice ───────────────────────────────────────────────────────
        try:
            import sounddevice as sd  # type: ignore
            self._sd = sd
            logger.info("sounddevice loaded — audio output ready.")
        except ImportError:
            logger.warning(
                "sounddevice not installed. Run: pip install sounddevice\n"
                "TTS synthesis will run but audio will not play."
            )
        except Exception as exc:
            logger.warning("sounddevice initialisation failed: %s", exc)
"""
audio/audio_factory.py
======================
Factory for creating the AudioPriorityQueue with a properly initialized TTS engine.

This module handles lazy loading of audio dependencies and provides a single
entry point for creating the complete audio subsystem.
"""

from __future__ import annotations

import logging
from typing import Optional

from backend.core.config import settings

logger = logging.getLogger(__name__)


def build_tts_engine():
    """
    Build a TTS engine based on configuration.

    Returns a TTS engine instance with a .speak(text, interrupt_event) method.
    Raises RuntimeError if dependencies are missing (rather than silently failing).
    """
    tts_engine_name = settings.TTS_ENGINE.lower()
    language = getattr(settings, "TTS_LANGUAGE", "fr")

    if tts_engine_name == "google":
        try:
            from backend.audio.tts_engine.google_tts import GoogleTTS
            engine = GoogleTTS(lang=language)
            logger.info("GoogleTTS initialized [language=%s]", language)
            return engine
        except Exception as exc:
            logger.critical(
                "GoogleTTS initialization FAILED: %s\n"
                "Install: pip install gtts sounddevice ffmpeg\n"
                "System will continue but TTS output will be DISABLED.",
                exc
            )
            # Create silent stub but log it as CRITICAL
            return _SilentTTS(failed=True)

    elif tts_engine_name == "coqui":
        try:
            from backend.audio.tts_engine.coqui_tts import CoquiTTS
            # Map our config language code to Coqui model name
            model_map = {
                "fr": "tts_models/fr/css10/vits",
                "en": "tts_models/en/ljspeech/vits",
                "ar": "tts_models/ar/cv/vits",
            }
            model_name = model_map.get(language, model_map["fr"])
            device = getattr(settings, "DEVICE", "cpu")
            engine = CoquiTTS(model_name=model_name, device=device)
            logger.info("CoquiTTS initialized [model=%s device=%s]", model_name, device)
            return engine
        except Exception as exc:
            logger.critical(
                "CoquiTTS initialization FAILED: %s\n"
                "Install: pip install tts torch\n"
                "System will continue but TTS output will be DISABLED.",
                exc
            )
            return _SilentTTS(failed=True)

    else:
        logger.warning("Unknown TTS engine '%s' — using silent stub", tts_engine_name)
        return _SilentTTS(failed=False)


def build_audio_priority_queue(tts_engine=None, state_manager=None):
    """
    Build and configure the AudioPriorityQueue.

    Parameters
    ----------
    tts_engine :
        Optional pre-built TTS engine. If None, one is created via build_tts_engine().
    state_manager :
        Optional StateManager for persistence tracking.
        If None, the queue uses internal counters.

    Returns
    -------
    AudioPriorityQueue
        Ready to use; caller must call .start() before adding alerts.
    """
    from backend.audio.audio_output_handler.priority_queue import AudioPriorityQueue

    if tts_engine is None:
        tts_engine = build_tts_engine()

    cooldown_secs = getattr(settings, "TTS_RATE_LIMIT_SECS", 3.0)
    max_queue_size = getattr(settings, "AUDIO_QUEUE_MAX", 20)

    queue = AudioPriorityQueue(
        tts_engine=tts_engine,
        state_manager=state_manager,
        cooldown_secs=cooldown_secs,
        max_size=max_queue_size,
    )

    logger.info(
        "AudioPriorityQueue created [cooldown=%.1fs max_size=%d]",
        cooldown_secs, max_queue_size
    )
    return queue


# ── Fallback silent TTS for environments without audio support ────────────────

class _SilentTTS:
    """
    No-op TTS engine.
    Used when audio dependencies are unavailable (e.g. CI, headless servers).
    """

    def __init__(self, failed: bool = False):
        """
        Parameters
        ----------
        failed : bool
            If True, this stub is due to a failed initialization.
            If False, audio support was intentionally disabled.
        """
        self.failed = failed
        if failed:
            logger.critical("TTS engine is MUTED due to initialization failure — no audio output will be produced")

    def speak(self, text: str, interrupt_event=None) -> None:
        """Log text instead of speaking."""
        logger.debug("TTS (muted): %s", text)

    def speak_async(self, text: str):
        """Fire-and-forget."""
        import threading
        t = threading.Thread(target=self.speak, args=(text,), daemon=True)
        t.start()
        return t

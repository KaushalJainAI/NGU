"""Client for the self-hosted whisper.cpp transcription server.

One of two STT backends (see `stt.py` for the dispatcher and the shared domain
prompt / language mapping). This one keeps audio entirely on our own
infrastructure, but on the 2 vCPU deploy box it runs ~20s per second of audio,
so it now serves as the FALLBACK behind Voxtral rather than the default.

Kept intentionally thin and dependency-light: the HTTP details (endpoint shape,
timeout) all live here so the view stays simple.
"""

import logging

import requests
from django.conf import settings

from .stt import DOMAIN_PROMPT, TranscriptionUnavailable, resolve_language

logger = logging.getLogger(__name__)


class WhisperUnavailable(TranscriptionUnavailable):
    """The whisper server was unreachable or returned an error."""


def transcribe(audio_bytes: bytes, filename: str, content_type: str, language: str = '') -> dict:
    """Send audio to the whisper.cpp server and return {'transcript', 'language'}.

    The client sends 16 kHz mono WAV (the frontend converts before upload), which
    whisper.cpp decodes natively without needing an ffmpeg build.
    """
    # Forcing the language beats autodetect on a small model; 'auto' triggers
    # detection (omitting the field would force English on this server).
    lang = resolve_language(language)
    data = {
        'temperature': '0.0',
        'response_format': 'json',
        'prompt': DOMAIN_PROMPT,
        'language': lang,
    }

    try:
        resp = requests.post(
            settings.WHISPER_URL,
            files={'file': (
                filename or 'audio.wav',
                audio_bytes,
                content_type or 'application/octet-stream',
            )},
            data=data,
            timeout=settings.WHISPER_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning('whisper transcription failed: %s', exc)
        raise WhisperUnavailable(str(exc)) from exc

    try:
        text = (resp.json().get('text') or '').strip()
    except ValueError:
        text = (resp.text or '').strip()
    return {'transcript': text, 'language': lang}

"""Client for the self-hosted whisper.cpp transcription server.

Voice input is transcribed on our own infrastructure (a small whisper.cpp
container, `small-q5` model) rather than the browser's Web Speech API — the
latter is browser-dependent and weak on Hindi/Hinglish. See docs/ASSISTANT.md.

Kept intentionally thin and dependency-light: the HTTP details (endpoint shape,
timeout, domain prompt, language mapping) all live here so the view stays simple.
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Prime the decoder with our catalogue vocabulary. A small model transcribes
# in-domain spice terms far more reliably when biased toward the words customers
# actually say — this punches above the model size for our use case.
DOMAIN_PROMPT = (
    "Nidhi Masala spices. haldi turmeric, mirch chilli, dhaniya coriander, "
    "jeera cumin, garam masala, kasuri methi, chaat masala, sabji masala, "
    "hing asafoetida, elaichi cardamom, laung clove, kali mirch black pepper. "
    "Add to cart, checkout, my orders, track order."
)

# Our UI language codes -> whisper language codes. Anything not listed
# (including 'auto'/'') maps to 'auto' so the server autodetects — NOTE the
# whisper server defaults to English when language is omitted, so we must send
# 'auto' explicitly rather than leaving it unset.
_LANG_MAP = {
    'en': 'en', 'hi': 'hi', 'hinglish': 'hi',
    'gu': 'gu', 'mr': 'mr', 'pa': 'pa',
}


class WhisperUnavailable(Exception):
    """The whisper server was unreachable or returned an error."""


def transcribe(audio_bytes: bytes, filename: str, content_type: str, language: str = '') -> dict:
    """Send audio to the whisper.cpp server and return {'transcript', 'language'}.

    The client sends 16 kHz mono WAV (the frontend converts before upload), which
    whisper.cpp decodes natively without needing an ffmpeg build.
    """
    # Forcing the language beats autodetect on a small model; 'auto' triggers
    # detection (omitting the field would force English on this server).
    lang = _LANG_MAP.get((language or '').lower(), 'auto')
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

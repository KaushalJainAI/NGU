"""Client for Mistral Voxtral Mini Transcribe, served over OpenRouter.

OpenRouter exposes an OpenAI-compatible POST /api/v1/audio/transcriptions that
takes a multipart upload and returns ``{"text": ..., "usage": {...}}``. That is
the same shape our frontend already produces (16 kHz mono WAV), so nothing about
the upload path changes when switching to this backend.

Billing is per minute of audio, prorated to the second — a 5-second utterance
costs about $0.00025. The reported per-request cost is logged at DEBUG and is
deliberately NOT returned to the caller: it is our billing data, not the
customer's, and this endpoint's response is sent straight to the browser.

Kept intentionally thin and dependency-light, mirroring whisper_client — the
HTTP details all live here so the view stays simple.
"""

import logging

import requests
from django.conf import settings

from .stt import DOMAIN_PROMPT, TranscriptionUnavailable, resolve_language

logger = logging.getLogger(__name__)


def transcribe(audio_bytes: bytes, filename: str, content_type: str, language: str = '') -> dict:
    """Send audio to OpenRouter for transcription. Returns {'transcript', 'language'}."""
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        # Treated as unavailable rather than a hard error so the dispatcher can
        # fall back to the local whisper container on a key-less environment.
        raise TranscriptionUnavailable('OPENROUTER/LLM API key is not configured')

    lang = resolve_language(language)
    data = {
        'model': settings.VOXTRAL_MODEL,
        'temperature': '0.0',
        'response_format': 'json',
        'prompt': DOMAIN_PROMPT,
    }
    # Unlike whisper.cpp, OpenRouter autodetects when `language` is OMITTED and
    # rejects the literal string 'auto' as an ISO-639-1 code — so drop the field
    # instead of sending 'auto'.
    if lang != 'auto':
        data['language'] = lang

    try:
        resp = requests.post(
            settings.OPENROUTER_TRANSCRIBE_URL,
            headers={'Authorization': f'Bearer {api_key}'},
            files={'file': (
                filename or 'audio.wav',
                audio_bytes,
                content_type or 'application/octet-stream',
            )},
            data=data,
            timeout=settings.VOXTRAL_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning('voxtral transcription failed: %s', exc)
        raise TranscriptionUnavailable(str(exc)) from exc

    try:
        payload = resp.json()
    except ValueError as exc:
        raise TranscriptionUnavailable('voxtral returned a non-JSON response') from exc

    usage = payload.get('usage') or {}
    logger.debug(
        'voxtral transcribed %ss for $%s', usage.get('seconds'), usage.get('cost'),
    )
    return {'transcript': (payload.get('text') or '').strip(), 'language': lang}

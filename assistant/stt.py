"""Speech-to-text dispatch for the assistant's voice input.

Owns the pieces that are true of transcription regardless of who performs it —
the exception type, the UI-language mapping, and the catalogue domain prompt —
plus a dispatcher that picks a backend at call time.

Two backends exist:

``voxtral``   Mistral Voxtral Mini Transcribe via OpenRouter (default). Hosted,
              ~1s for a short utterance, $0.003/minute of audio, and much
              stronger on Hindi/Hinglish than a quantized `small` model.
``whisper``   The self-hosted whisper.cpp container. Free and keeps audio on our
              own infrastructure, but on the 2 vCPU deploy box it runs roughly
              20s per second of audio, which is too slow to actually use.

``STT_PROVIDER`` selects the primary. When it is ``voxtral`` and
``STT_FALLBACK_TO_WHISPER`` is on, an unavailable Voxtral falls back to the
local container rather than failing the request — so an OpenRouter outage or an
exhausted credit limit degrades to slow-but-working instead of no voice at all.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class TranscriptionUnavailable(Exception):
    """No transcription backend could service the request."""


# Prime the decoder with our catalogue vocabulary. A small model transcribes
# in-domain spice terms far more reliably when biased toward the words customers
# actually say — this punches above the model size for our use case.
#
# NOTE: this genuinely biases whisper.cpp. OpenRouter documents `prompt` as
# "accepted but ignored on most providers", and a side-by-side probe against
# Voxtral confirmed byte-identical output with and without it. We still send it
# (it is free and harmless, and may start being honoured), but do NOT count on
# it for Voxtral accuracy — see docs/ASSISTANT.md.
DOMAIN_PROMPT = (
    "Nidhi Masala spices. haldi turmeric, mirch chilli, dhaniya coriander, "
    "jeera cumin, garam masala, kasuri methi, chaat masala, sabji masala, "
    "hing asafoetida, elaichi cardamom, laung clove, kali mirch black pepper. "
    "Add to cart, checkout, my orders, track order."
)

# Our UI language codes -> ISO-639-1 codes (what both backends expect).
# Anything not listed (including 'auto'/'') maps to 'auto' so the backend
# autodetects — NOTE the whisper server defaults to English when language is
# omitted, so we must send 'auto' explicitly rather than leaving it unset.
LANG_MAP = {
    'en': 'en', 'hi': 'hi', 'hinglish': 'hi',
    'gu': 'gu', 'mr': 'mr', 'pa': 'pa',
}


def resolve_language(language: str) -> str:
    """Map a UI language code to ISO-639-1, or 'auto' to let the model detect."""
    return LANG_MAP.get((language or '').lower(), 'auto')


def transcribe(audio_bytes: bytes, filename: str, content_type: str, language: str = '') -> dict:
    """Transcribe audio with the configured backend. Returns {'transcript', 'language'}.

    ``language`` in the result is the language we *asked* for ('auto' when we let
    the model detect), not a detection result — neither backend reports one in
    the plain-json response format.
    """
    from . import voxtral_client, whisper_client  # local: avoids an import cycle

    provider = (settings.STT_PROVIDER or 'voxtral').strip().lower()

    if provider == 'whisper':
        return whisper_client.transcribe(audio_bytes, filename, content_type, language)

    try:
        return voxtral_client.transcribe(audio_bytes, filename, content_type, language)
    except TranscriptionUnavailable:
        if not settings.STT_FALLBACK_TO_WHISPER:
            raise
        logger.warning('voxtral unavailable, falling back to self-hosted whisper')
        return whisper_client.transcribe(audio_bytes, filename, content_type, language)

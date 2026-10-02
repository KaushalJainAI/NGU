"""Voice transcription: endpoint gating and STT backend dispatch.

Network is always mocked — these must never hit OpenRouter (it is metered) or
the whisper container (it may not be running).
"""

from unittest.mock import patch

import pytest
import requests
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from assistant import stt, voxtral_client, whisper_client

URL = '/api/assistant/transcribe/'
WAV = b'RIFF$\x00\x00\x00WAVEfmt '  # contents are irrelevant; the backend is mocked


def make_audio(data=WAV):
    return SimpleUploadedFile('voice.wav', data, content_type='audio/wav')


class _Resp:
    """Minimal stand-in for a requests.Response."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


# ---------------------------------------------------------------------------
# Endpoint gating
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_transcribe_requires_login(settings):
    settings.USE_SELF_HOSTED_STT = True
    resp = APIClient().post(URL, {'audio': make_audio()}, format='multipart')
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_transcribe_disabled_returns_503(authenticated_client, settings):
    settings.USE_SELF_HOSTED_STT = False
    resp = authenticated_client.post(URL, {'audio': make_audio()}, format='multipart')
    assert resp.status_code == 503


@pytest.mark.django_db
def test_transcribe_without_audio_returns_400(authenticated_client, settings):
    settings.USE_SELF_HOSTED_STT = True
    resp = authenticated_client.post(URL, {}, format='multipart')
    assert resp.status_code == 400


@pytest.mark.django_db
def test_oversized_audio_returns_413(authenticated_client, settings):
    settings.USE_SELF_HOSTED_STT = True
    from assistant.views import AssistantTranscribeView
    oversized = make_audio(b'x' * (AssistantTranscribeView.MAX_AUDIO_BYTES + 1))
    resp = authenticated_client.post(URL, {'audio': oversized}, format='multipart')
    assert resp.status_code == 413


@pytest.mark.django_db
def test_backend_unavailable_returns_503(authenticated_client, settings):
    settings.USE_SELF_HOSTED_STT = True
    with patch.object(stt, 'transcribe', side_effect=stt.TranscriptionUnavailable('down')):
        resp = authenticated_client.post(URL, {'audio': make_audio()}, format='multipart')
    assert resp.status_code == 503


@pytest.mark.django_db
def test_successful_transcription_returns_text(authenticated_client, settings):
    settings.USE_SELF_HOSTED_STT = True
    result = {'transcript': 'add garam masala', 'language': 'hi'}
    with patch.object(stt, 'transcribe', return_value=result) as mock:
        resp = authenticated_client.post(
            URL, {'audio': make_audio(), 'language': 'hinglish'}, format='multipart',
        )
    assert resp.status_code == 200
    assert resp.json()['transcript'] == 'add garam masala'
    # The UI language must reach the backend — forcing it beats autodetect.
    assert mock.call_args[0][3] == 'hinglish'


@pytest.mark.django_db
def test_response_never_leaks_billing_data(authenticated_client, settings):
    """usage/cost is our billing data — it must not reach the browser."""
    settings.USE_SELF_HOSTED_STT = True
    settings.OPENROUTER_API_KEY = 'sk-or-test'
    settings.STT_PROVIDER = 'voxtral'
    payload = {'text': 'hi', 'usage': {'seconds': 4, 'cost': 0.0002}}
    with patch.object(voxtral_client.requests, 'post', return_value=_Resp(payload)):
        body = authenticated_client.post(
            URL, {'audio': make_audio()}, format='multipart',
        ).json()
    assert set(body) == {'transcript', 'language'}


# ---------------------------------------------------------------------------
# Voxtral client
# ---------------------------------------------------------------------------

def test_voxtral_sends_model_and_language(settings):
    settings.OPENROUTER_API_KEY = 'sk-or-test'
    settings.VOXTRAL_MODEL = 'mistralai/voxtral-mini-transcribe'
    payload = {'text': ' add jeera ', 'usage': {'seconds': 4, 'cost': 0.0002}}
    with patch.object(voxtral_client.requests, 'post', return_value=_Resp(payload)) as post:
        out = voxtral_client.transcribe(WAV, 'voice.wav', 'audio/wav', 'hinglish')

    assert out == {'transcript': 'add jeera', 'language': 'hi'}
    data = post.call_args.kwargs['data']
    assert data['model'] == 'mistralai/voxtral-mini-transcribe'
    assert data['language'] == 'hi'
    assert post.call_args.kwargs['headers']['Authorization'] == 'Bearer sk-or-test'


def test_voxtral_omits_language_when_unknown(settings):
    """OpenRouter 422s on the literal 'auto' — the field must be dropped instead."""
    settings.OPENROUTER_API_KEY = 'sk-or-test'
    with patch.object(voxtral_client.requests, 'post', return_value=_Resp({'text': 'hello'})) as post:
        out = voxtral_client.transcribe(WAV, 'voice.wav', 'audio/wav', 'klingon')

    assert 'language' not in post.call_args.kwargs['data']
    assert out['language'] == 'auto'


def test_voxtral_without_api_key_is_unavailable(settings):
    settings.OPENROUTER_API_KEY = ''
    with pytest.raises(stt.TranscriptionUnavailable):
        voxtral_client.transcribe(WAV, 'voice.wav', 'audio/wav', 'en')


def test_voxtral_http_error_raises_unavailable(settings):
    settings.OPENROUTER_API_KEY = 'sk-or-test'
    with patch.object(voxtral_client.requests, 'post', side_effect=requests.ConnectionError('boom')):
        with pytest.raises(stt.TranscriptionUnavailable):
            voxtral_client.transcribe(WAV, 'voice.wav', 'audio/wav', 'en')


def test_voxtral_upstream_error_raises_unavailable(settings):
    settings.OPENROUTER_API_KEY = 'sk-or-test'
    with patch.object(voxtral_client.requests, 'post', return_value=_Resp({'error': {}}, 402)):
        with pytest.raises(stt.TranscriptionUnavailable):
            voxtral_client.transcribe(WAV, 'voice.wav', 'audio/wav', 'en')


# ---------------------------------------------------------------------------
# Dispatch + fallback
# ---------------------------------------------------------------------------

def test_dispatch_uses_whisper_when_selected(settings):
    settings.STT_PROVIDER = 'whisper'
    result = {'transcript': 'w', 'language': 'en'}
    with patch.object(whisper_client, 'transcribe', return_value=result) as w, \
            patch.object(voxtral_client, 'transcribe') as v:
        assert stt.transcribe(WAV, 'a.wav', 'audio/wav', 'en')['transcript'] == 'w'
    v.assert_not_called()
    w.assert_called_once()


def test_dispatch_falls_back_to_whisper(settings):
    settings.STT_PROVIDER = 'voxtral'
    settings.STT_FALLBACK_TO_WHISPER = True
    result = {'transcript': 'w', 'language': 'en'}
    with patch.object(voxtral_client, 'transcribe', side_effect=stt.TranscriptionUnavailable('402')), \
            patch.object(whisper_client, 'transcribe', return_value=result) as w:
        assert stt.transcribe(WAV, 'a.wav', 'audio/wav', 'en')['transcript'] == 'w'
    w.assert_called_once()


def test_dispatch_propagates_when_fallback_disabled(settings):
    settings.STT_PROVIDER = 'voxtral'
    settings.STT_FALLBACK_TO_WHISPER = False
    with patch.object(voxtral_client, 'transcribe', side_effect=stt.TranscriptionUnavailable('402')), \
            patch.object(whisper_client, 'transcribe') as w:
        with pytest.raises(stt.TranscriptionUnavailable):
            stt.transcribe(WAV, 'a.wav', 'audio/wav', 'en')
    w.assert_not_called()


def test_whisper_failure_is_a_transcription_failure(settings):
    """WhisperUnavailable must stay catchable as the shared type — the view only
    catches TranscriptionUnavailable, so a narrower class would 500."""
    assert issubclass(whisper_client.WhisperUnavailable, stt.TranscriptionUnavailable)


@pytest.mark.parametrize('ui, expected', [
    ('en', 'en'), ('hi', 'hi'), ('hinglish', 'hi'), ('HI', 'hi'),
    ('gu', 'gu'), ('', 'auto'), ('auto', 'auto'), ('xx', 'auto'),
])
def test_resolve_language(ui, expected):
    assert stt.resolve_language(ui) == expected

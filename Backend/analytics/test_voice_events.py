"""AP11: voice-ordering funnel events ingest cleanly (choices-level only)."""
import pytest

from analytics.models import UserEvent


@pytest.mark.django_db
class TestVoiceEvents:
    def test_voice_events_recorded(self, authenticated_client, test_user):
        r = authenticated_client.post('/api/events/', [
            {'event_type': 'voice_used'},
            {'event_type': 'voice_confirmed'},
        ], format='json')
        assert r.status_code == 201
        assert r.data == {'recorded': 2, 'skipped': 0}
        assert UserEvent.objects.filter(
            user=test_user, event_type='voice_used').exists()
        assert UserEvent.objects.filter(
            user=test_user, event_type='voice_confirmed').exists()

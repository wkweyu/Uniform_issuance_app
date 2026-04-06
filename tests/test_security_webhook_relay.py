import time

import pytest

from platform_bp.services.notifications import build_webhook_signature
from scripts.security_webhook_relay import build_sentinel_event, build_splunk_event, create_app


@pytest.fixture()
def relay_client(monkeypatch):
    for key in [
        'PLATFORM_SECURITY_SHARED_SECRET',
        'SECURITY_RELAY_ALLOW_TOKEN_ONLY',
        'PLATFORM_SECURITY_TOKEN_ONLY_SECRET',
        'SPLUNK_HEC_URL',
        'SPLUNK_HEC_TOKEN',
        'SPLUNK_HEC_SOURCE',
        'SPLUNK_HEC_SOURCETYPE',
        'SENTINEL_LOGIC_APP_URL',
        'SENTINEL_BEARER_TOKEN',
        'SECURITY_RELAY_FORWARD_TIMEOUT_SECONDS',
        'SECURITY_RELAY_SIGNATURE_TOLERANCE_SECONDS',
    ]:
        monkeypatch.delenv(key, raising=False)
    app = create_app({'TESTING': True})
    return app.test_client()


def test_relay_health_exposes_destination_status(relay_client, monkeypatch):
    monkeypatch.setenv('PLATFORM_SECURITY_SHARED_SECRET', 'shared-secret')
    monkeypatch.setenv('SPLUNK_HEC_URL', 'https://splunk.example.test/hec')
    monkeypatch.setenv('SPLUNK_HEC_TOKEN', 'splunk-token')
    monkeypatch.setenv('SECURITY_RELAY_ENABLE_FORWARDING', '1')

    response = relay_client.get('/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['ok'] is True
    assert payload['destinations']['splunk'] is True
    assert payload['destinations']['sentinel'] is False
    assert payload['hmac_required'] is True
    assert payload['forwarding_enabled'] is True
    assert payload['warning'] is None


def test_relay_health_warns_when_forwarding_disabled(relay_client, monkeypatch):
    monkeypatch.setenv('PLATFORM_SECURITY_SHARED_SECRET', 'shared-secret')

    response = relay_client.get('/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['forwarding_enabled'] is False
    assert payload['warning'] == 'running but downstream SIEM forwarding is disabled'


def test_relay_rejects_invalid_signature(relay_client, monkeypatch):
    monkeypatch.setenv('PLATFORM_SECURITY_SHARED_SECRET', 'shared-secret')
    response = relay_client.post(
        '/webhooks/platform/security',
        json={'event': {'id': 1, 'event_type': 'repeated_failed_platform_login'}},
        headers={
            'X-Security-Webhook-Timestamp': '1700000000',
            'X-Security-Webhook-Signature': 'sha256=invalid',
        },
    )

    assert response.status_code == 401
    assert response.get_json()['error'] == 'Invalid signature'


def test_relay_forwards_to_splunk_and_sentinel(relay_client, monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, status_code=202, text='accepted'):
            self.status_code = status_code
            self.text = text
            self.reason = 'Accepted'

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({'url': url, 'json': json, 'headers': headers, 'timeout': timeout})
        return FakeResponse()

    monkeypatch.setenv('PLATFORM_SECURITY_SHARED_SECRET', 'shared-secret')
    monkeypatch.setenv('SECURITY_RELAY_ENABLE_FORWARDING', '1')
    monkeypatch.setenv('SPLUNK_HEC_URL', 'https://splunk.example.test/hec')
    monkeypatch.setenv('SPLUNK_HEC_TOKEN', 'splunk-token')
    monkeypatch.setenv('SENTINEL_LOGIC_APP_URL', 'https://logic.example.test/workflows/security')
    monkeypatch.setenv('SENTINEL_BEARER_TOKEN', 'sentinel-token')
    monkeypatch.setattr('scripts.security_webhook_relay.requests.post', fake_post)

    payload = {
        'event': {
            'id': 9,
            'event_type': 'platform_impersonation_burst',
            'severity': 'high',
            'status': 'open',
            'title': 'Repeated impersonation activity detected',
            'description': 'Burst detected',
            'school_id': 12,
            'signal_key': 'platform-user:4:school:12',
            'threshold_value': 3,
            'observed_value': 4,
            'occurrence_count': 1,
            'support_ticket_id': 3,
            'first_seen_at': '2026-04-04T11:30:00',
            'last_seen_at': '2026-04-04T11:34:00',
            'details': {'actor_user_id': 4, 'target_user_id': 818},
        }
    }
    signed = build_webhook_signature(payload, 'shared-secret', timestamp=str(int(time.time())))
    response = relay_client.post(
        '/webhooks/platform/security',
        data=signed['body'],
        headers={
            'Content-Type': 'application/json',
            'X-Security-Webhook-Timestamp': signed['timestamp'],
            'X-Security-Webhook-Signature': signed['signature'],
            'X-Security-Webhook-Token': 'shared-secret',
        },
    )

    assert response.status_code == 202
    payload = response.get_json()
    assert payload['ok'] is True
    assert payload['forwarded'] is True
    assert len(calls) == 2
    assert calls[0]['headers']['Authorization'] == 'Splunk splunk-token'
    assert calls[1]['headers']['Authorization'] == 'Bearer sentinel-token'
    assert calls[0]['json']['event']['event_type'] == 'platform_impersonation_burst'
    assert calls[1]['json']['product'] == 'platform-control-plane'


def test_relay_accepts_signed_events_when_forwarding_disabled(relay_client, monkeypatch):
    monkeypatch.setenv('PLATFORM_SECURITY_SHARED_SECRET', 'shared-secret')

    payload = {
        'event': {
            'id': 10,
            'event_type': 'platform_impersonation_burst',
        }
    }
    signed = build_webhook_signature(payload, 'shared-secret', timestamp=str(int(time.time())))
    response = relay_client.post(
        '/webhooks/platform/security',
        data=signed['body'],
        headers={
            'Content-Type': 'application/json',
            'X-Security-Webhook-Timestamp': signed['timestamp'],
            'X-Security-Webhook-Signature': signed['signature'],
        },
    )

    assert response.status_code == 202
    body = response.get_json()
    assert body['ok'] is True
    assert body['forwarded'] is False
    assert body['warning'] == 'running but downstream SIEM forwarding is disabled'


def test_relay_accepts_signed_events_when_no_downstream_siem_configured(relay_client, monkeypatch):
    monkeypatch.setenv('PLATFORM_SECURITY_SHARED_SECRET', 'shared-secret')
    monkeypatch.setenv('SECURITY_RELAY_ENABLE_FORWARDING', '1')

    payload = {
        'event': {
            'id': 11,
            'event_type': 'repeated_failed_platform_login',
        }
    }
    signed = build_webhook_signature(payload, 'shared-secret', timestamp=str(int(time.time())))
    response = relay_client.post(
        '/webhooks/platform/security',
        data=signed['body'],
        headers={
            'Content-Type': 'application/json',
            'X-Security-Webhook-Timestamp': signed['timestamp'],
            'X-Security-Webhook-Signature': signed['signature'],
        },
    )

    assert response.status_code == 202
    body = response.get_json()
    assert body['ok'] is True
    assert body['forwarded'] is False
    assert body['warning'] == 'running but no downstream SIEM configured'


def test_event_transforms_match_documented_shapes():
    payload = {
        'event': {
            'id': 42,
            'event_type': 'repeated_failed_platform_login',
            'severity': 'high',
            'status': 'open',
            'title': 'Repeated failed platform login attempts',
            'description': 'Observed 5 failures',
            'school_id': 12,
            'signal_key': 'platform-user:44',
            'threshold_value': 3,
            'observed_value': 5,
            'occurrence_count': 2,
            'support_ticket_id': 18,
            'first_seen_at': '2026-04-04T11:30:00',
            'last_seen_at': '2026-04-04T11:34:00',
            'details': {'email': 'admin@example.com'},
        }
    }

    splunk_event = build_splunk_event(payload)
    sentinel_event = build_sentinel_event(payload)

    assert splunk_event['event']['event_type'] == 'repeated_failed_platform_login'
    assert splunk_event['event']['support_ticket_id'] == 18
    assert sentinel_event['vendor'] == 'uniform-issuance-app'
    assert sentinel_event['signal_key'] == 'platform-user:44'
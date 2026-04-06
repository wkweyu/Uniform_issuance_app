import os
import sys

import requests
from flask import Flask, jsonify, request

from platform_bp.services.notifications import verify_webhook_signature


def _env_flag(name, default=False):
    value = (os.environ.get(name) or '').strip().lower()
    if not value:
        return default
    return value in {'1', 'true', 'yes', 'on'}


def build_splunk_event(payload):
    event = payload['event']
    return {
        'sourcetype': os.environ.get('SPLUNK_HEC_SOURCETYPE', 'platform:security:event'),
        'source': os.environ.get('SPLUNK_HEC_SOURCE', 'uniform-issuance-app'),
        'event': {
            'event_id': event.get('id'),
            'event_type': event.get('event_type'),
            'severity': event.get('severity'),
            'status': event.get('status'),
            'title': event.get('title'),
            'description': event.get('description'),
            'school_id': event.get('school_id'),
            'signal_key': event.get('signal_key'),
            'threshold_value': event.get('threshold_value'),
            'observed_value': event.get('observed_value'),
            'occurrence_count': event.get('occurrence_count'),
            'support_ticket_id': event.get('support_ticket_id'),
            'first_seen_at': event.get('first_seen_at'),
            'last_seen_at': event.get('last_seen_at'),
            'details': event.get('details') or {},
        },
    }


def build_sentinel_event(payload):
    event = payload['event']
    return {
        'vendor': 'uniform-issuance-app',
        'product': 'platform-control-plane',
        'category': 'security_event',
        'event_id': event.get('id'),
        'event_type': event.get('event_type'),
        'severity': event.get('severity'),
        'status': event.get('status'),
        'title': event.get('title'),
        'description': event.get('description'),
        'school_id': event.get('school_id'),
        'signal_key': event.get('signal_key'),
        'threshold_value': event.get('threshold_value'),
        'observed_value': event.get('observed_value'),
        'occurrence_count': event.get('occurrence_count'),
        'support_ticket_id': event.get('support_ticket_id'),
        'first_seen_at': event.get('first_seen_at'),
        'last_seen_at': event.get('last_seen_at'),
        'details': event.get('details') or {},
    }


def _post_json(url, payload, headers=None, timeout=10):
    response = requests.post(url, json=payload, headers=headers or {}, timeout=timeout)
    ok = 200 <= response.status_code < 300
    return {
        'ok': ok,
        'status_code': response.status_code,
        'reason': response.text[:1000] if response.text else response.reason,
    }


def forward_to_splunk(payload):
    url = os.environ.get('SPLUNK_HEC_URL')
    token = os.environ.get('SPLUNK_HEC_TOKEN')
    if not url or not token:
        return {'configured': False, 'destination': 'splunk'}

    return {
        'configured': True,
        'destination': 'splunk',
        **_post_json(
            url,
            build_splunk_event(payload),
            headers={'Authorization': f'Splunk {token}'},
            timeout=int(os.environ.get('SECURITY_RELAY_FORWARD_TIMEOUT_SECONDS', '10')),
        ),
    }


def forward_to_sentinel(payload):
    url = os.environ.get('SENTINEL_LOGIC_APP_URL')
    if not url:
        return {'configured': False, 'destination': 'sentinel'}

    headers = {}
    auth_token = os.environ.get('SENTINEL_BEARER_TOKEN')
    if auth_token:
        headers['Authorization'] = f'Bearer {auth_token}'

    return {
        'configured': True,
        'destination': 'sentinel',
        **_post_json(
            url,
            build_sentinel_event(payload),
            headers=headers,
            timeout=int(os.environ.get('SECURITY_RELAY_FORWARD_TIMEOUT_SECONDS', '10')),
        ),
    }


def _configured_destinations():
    return {
        'splunk': bool(os.environ.get('SPLUNK_HEC_URL') and os.environ.get('SPLUNK_HEC_TOKEN')),
        'sentinel': bool(os.environ.get('SENTINEL_LOGIC_APP_URL')),
    }


def _relay_warning_message():
    forwarding_enabled = _env_flag('SECURITY_RELAY_ENABLE_FORWARDING', default=False)
    destinations = _configured_destinations()
    if not forwarding_enabled:
        return 'running but downstream SIEM forwarding is disabled'
    if not any(destinations.values()):
        return 'running but no downstream SIEM configured'
    return None


def _emit_startup_warning():
    warning = _relay_warning_message()
    if warning:
        print(f'WARNING: security webhook relay is {warning}', file=sys.stderr)


def create_app(test_config=None):
    app = Flask(__name__)
    if test_config:
        app.config.update(test_config)

    _emit_startup_warning()

    @app.get('/health')
    def health_check():
        warning = _relay_warning_message()
        return jsonify(
            {
                'ok': True,
                'destinations': _configured_destinations(),
                'hmac_required': bool(os.environ.get('PLATFORM_SECURITY_SHARED_SECRET')),
                'forwarding_enabled': _env_flag('SECURITY_RELAY_ENABLE_FORWARDING', default=False),
                'warning': warning,
            }
        )

    @app.post('/webhooks/platform/security')
    def receive_platform_security_webhook():
        raw_body = request.get_data(as_text=True)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get('event'), dict):
            return jsonify({'ok': False, 'error': 'Invalid payload'}), 400

        shared_secret = os.environ.get('PLATFORM_SECURITY_SHARED_SECRET')
        signature = request.headers.get('X-Security-Webhook-Signature')
        timestamp = request.headers.get('X-Security-Webhook-Timestamp')
        compatibility_token = request.headers.get('X-Security-Webhook-Token')

        if shared_secret:
            if not verify_webhook_signature(
                raw_body,
                shared_secret,
                signature,
                timestamp,
                tolerance_seconds=int(os.environ.get('SECURITY_RELAY_SIGNATURE_TOLERANCE_SECONDS', '300')),
            ):
                return jsonify({'ok': False, 'error': 'Invalid signature'}), 401
        elif _env_flag('SECURITY_RELAY_ALLOW_TOKEN_ONLY', default=False):
            fallback_token = os.environ.get('PLATFORM_SECURITY_TOKEN_ONLY_SECRET')
            if not fallback_token or compatibility_token != fallback_token:
                return jsonify({'ok': False, 'error': 'Invalid token'}), 401
        else:
            return jsonify({'ok': False, 'error': 'Shared secret is not configured'}), 503

        forwarding_enabled = _env_flag('SECURITY_RELAY_ENABLE_FORWARDING', default=False)
        if not forwarding_enabled:
            return (
                jsonify(
                    {
                        'ok': True,
                        'event_type': payload['event'].get('event_type'),
                        'forwarded': False,
                        'warning': 'running but downstream SIEM forwarding is disabled',
                        'destinations': [
                            {'configured': False, 'destination': 'splunk'},
                            {'configured': False, 'destination': 'sentinel'},
                        ],
                    }
                ),
                202,
            )

        destinations = [forward_to_splunk(payload), forward_to_sentinel(payload)]
        configured = [item for item in destinations if item['configured']]
        if not configured:
            return (
                jsonify(
                    {
                        'ok': True,
                        'event_type': payload['event'].get('event_type'),
                        'forwarded': False,
                        'warning': 'running but no downstream SIEM configured',
                        'destinations': destinations,
                    }
                ),
                202,
            )

        successful = [item for item in configured if item.get('ok')]
        status_code = 202 if successful else 502
        return (
            jsonify(
                {
                    'ok': bool(successful),
                    'event_type': payload['event'].get('event_type'),
                    'forwarded': bool(successful),
                    'destinations': destinations,
                }
            ),
            status_code,
        )

    return app


app = create_app()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('SECURITY_RELAY_PORT', '8080')))
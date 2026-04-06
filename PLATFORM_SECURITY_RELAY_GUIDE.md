# Platform Security Relay Guide

This guide defines a relay endpoint shape for receiving signed platform security webhooks and forwarding them into Splunk or Microsoft Sentinel.

## Recommended Topology

Use this path instead of sending directly to vendor-specific collectors:

1. Platform sends a signed webhook to your internal relay.
2. Relay verifies the HMAC signature and timestamp.
3. Relay normalizes or enriches the event.
4. Relay forwards to Splunk HEC, Sentinel Logic App, or both.

Recommended endpoint:

```text
POST /webhooks/platform/security
```

Reference implementation in this repo:

```text
scripts/security_webhook_relay.py
```

Example public URL:

```text
https://alerts.example.com/webhooks/platform/security
```

## Headers Sent By The Platform

When a shared secret is configured in the notification preference, the platform sends:

```text
Content-Type: application/json
X-Security-Webhook-Token: <shared-secret>
X-Security-Webhook-Timestamp: <unix-seconds>
X-Security-Webhook-Signature: sha256=<hex-digest>
X-Security-Webhook-Signature-Version: v1
```

The token header is kept for backward compatibility. The relay should verify the HMAC signature and not rely only on the token header.

## Signature Algorithm

The platform signs this exact string:

```text
<timestamp>.<canonical-json-body>
```

Rules:

1. JSON is serialized with sorted keys.
2. Separators are compact: `,` and `:`.
3. HMAC algorithm is SHA-256.
4. Header format is `sha256=<hex-digest>`.

## Payload Shape

Current payload structure:

```json
{
  "event": {
    "id": 42,
    "event_type": "repeated_failed_platform_login",
    "severity": "high",
    "status": "open",
    "title": "Repeated failed platform login attempts",
    "description": "Observed 5 failures in the last 15 minutes.",
    "school_id": 12,
    "signal_key": "platform-user:44",
    "threshold_value": 3,
    "observed_value": 5,
    "occurrence_count": 2,
    "support_ticket_id": 18,
    "first_seen_at": "2026-04-04T11:30:00",
    "last_seen_at": "2026-04-04T11:34:00",
    "details": {
      "email": "admin@example.com",
      "ip_address": "203.0.113.10"
    }
  }
}
```

## Relay Verification Example

Example Flask receiver:

```python
import os

from flask import Flask, abort, request

from platform_bp.services.notifications import verify_webhook_signature

app = Flask(__name__)


@app.post('/webhooks/platform/security')
def receive_platform_security_webhook():
    shared_secret = os.environ['PLATFORM_SECURITY_SHARED_SECRET']
    raw_body = request.get_data(as_text=True)
    signature = request.headers.get('X-Security-Webhook-Signature')
    timestamp = request.headers.get('X-Security-Webhook-Timestamp')

    if not verify_webhook_signature(raw_body, shared_secret, signature, timestamp):
        abort(401)

    payload = request.get_json()
    event = payload['event']
    # transform and forward here
    return {'ok': True}, 202
```

## Splunk Relay Shape

Recommended relay behavior:

1. Verify HMAC.
2. Transform to Splunk HEC format.
3. Send with `Authorization: Splunk <token>`.

Example outbound body to Splunk HEC:

```json
{
  "sourcetype": "platform:security:event",
  "source": "uniform-issuance-app",
  "event": {
    "event_type": "repeated_failed_platform_login",
    "severity": "high",
    "school_id": 12,
    "signal_key": "platform-user:44",
    "observed_value": 5,
    "threshold_value": 3,
    "support_ticket_id": 18,
    "details": {
      "email": "admin@example.com",
      "ip_address": "203.0.113.10"
    }
  }
}
```

Recommended relay endpoint label in the platform UI:

```text
Splunk Security Relay
```

Recommended throttle:

```text
5
```

## Microsoft Sentinel Relay Shape

Recommended Sentinel path:

1. Platform sends to your relay or directly to a Logic App HTTP trigger.
2. Logic App validates the signature or trusts the already-validated relay.
3. Logic App maps fields into a custom log or incident automation flow.

Recommended normalized event shape for the relay-to-Logic-App hop:

```json
{
  "vendor": "uniform-issuance-app",
  "product": "platform-control-plane",
  "category": "security_event",
  "event_type": "platform_impersonation_burst",
  "severity": "high",
  "school_id": 12,
  "signal_key": "platform-user:4:school:12",
  "first_seen_at": "2026-04-04T11:30:00",
  "last_seen_at": "2026-04-04T11:34:00",
  "details": {
    "actor_user_id": 4,
    "target_user_id": 818,
    "window_minutes": 60
  }
}
```

Recommended relay endpoint label in the platform UI:

```text
Sentinel Logic App
```

Recommended throttle:

```text
5
```

## Operational Recommendations

1. Reject timestamps older than 5 minutes.
2. Store and monitor failed signature attempts.
3. Log the event id and signal key for dedupe.
4. Forward enriched school metadata if the relay can look it up safely.
5. Keep vendor-specific auth tokens only in the relay, not in the platform UI.

## Deployment

Example local run:

```bash
cd /home/frappe-user/uniform\ issuance\ app
source venv/bin/activate
gunicorn -w 2 -b 0.0.0.0:8080 scripts.security_webhook_relay:app
```

Required env vars for signed incoming requests:

```text
PLATFORM_SECURITY_SHARED_SECRET
```

Recommended staging default before Splunk or Sentinel values exist:

```text
SECURITY_RELAY_ENABLE_FORWARDING=0
```

In that mode the relay still verifies signatures and accepts events, but it returns a health warning and does not attempt downstream SIEM delivery.

Optional downstream env vars:

```text
SPLUNK_HEC_URL
SPLUNK_HEC_TOKEN
SENTINEL_LOGIC_APP_URL
SENTINEL_BEARER_TOKEN
```

When you are ready to forward to downstream SIEM tooling, set:

```text
SECURITY_RELAY_ENABLE_FORWARDING=1
```

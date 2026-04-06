import hashlib
import hmac
import json
import os
import smtplib
import time
from email.message import EmailMessage

import requests


def _smtp_use_ssl(smtp_port):
    configured = (os.environ.get('SMTP_USE_SSL') or '').strip().lower()
    if configured in {'1', 'true', 'yes', 'on'}:
        return True
    if configured in {'0', 'false', 'no', 'off'}:
        return False
    return int(smtp_port) == 465


def _open_smtp_client(smtp_host, smtp_port, timeout=10):
    if _smtp_use_ssl(smtp_port):
        return smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout)
    return smtplib.SMTP(smtp_host, smtp_port, timeout=timeout)


def send_email_alert(to_email, subject, body, from_email=None):
    try:
        smtp_host = os.environ.get('SMTP_HOST')
        smtp_port = int(os.environ.get('SMTP_PORT', '25'))
        smtp_user = os.environ.get('SMTP_USER')
        smtp_pass = os.environ.get('SMTP_PASS')
        if not smtp_host:
            return {
                'ok': False,
                'status': 'failed',
                'reason': 'SMTP_HOST is not configured',
            }

        message = EmailMessage()
        message['Subject'] = subject
        message['From'] = from_email or smtp_user or f'no-reply@{smtp_host}'
        message['To'] = to_email
        message.set_content(body)

        smtp_client = _open_smtp_client(smtp_host, smtp_port, timeout=10)
        smtp_client.ehlo()
        if smtp_user and smtp_pass:
            if not _smtp_use_ssl(smtp_port):
                smtp_client.starttls()
                smtp_client.ehlo()
            smtp_client.login(smtp_user, smtp_pass)
        smtp_client.send_message(message)
        smtp_client.quit()
        return {
            'ok': True,
            'status': 'sent',
            'reason': 'Delivered via SMTP',
        }
    except Exception as exc:
        return {
            'ok': False,
            'status': 'failed',
            'reason': str(exc),
        }


def _canonical_webhook_body(payload):
    return json.dumps(payload, separators=(',', ':'), sort_keys=True)


def build_webhook_signature(payload, shared_secret, timestamp=None):
    effective_timestamp = str(timestamp or int(time.time()))
    canonical_body = _canonical_webhook_body(payload)
    signed_text = f'{effective_timestamp}.{canonical_body}'.encode('utf-8')
    signature = hmac.new(
        shared_secret.encode('utf-8'),
        signed_text,
        hashlib.sha256,
    ).hexdigest()
    return {
        'timestamp': effective_timestamp,
        'body': canonical_body,
        'signature': f'sha256={signature}',
    }


def verify_webhook_signature(payload_body, shared_secret, signature, timestamp, tolerance_seconds=300, current_time=None):
    if not shared_secret or not signature or not timestamp:
        return False

    try:
        timestamp_int = int(timestamp)
    except (TypeError, ValueError):
        return False

    now = int(current_time if current_time is not None else time.time())
    if abs(now - timestamp_int) > tolerance_seconds:
        return False

    expected = hmac.new(
        shared_secret.encode('utf-8'),
        f'{timestamp}.{payload_body}'.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    expected_signature = f'sha256={expected}'
    return hmac.compare_digest(expected_signature, signature)


def send_webhook_alert(url, payload, secret_token=None, headers=None, timeout_seconds=10):
    outbound_headers = {'Content-Type': 'application/json'}
    outbound_headers.update(headers or {})
    request_kwargs = {'headers': outbound_headers, 'timeout': timeout_seconds}
    if secret_token:
        outbound_headers['X-Security-Webhook-Token'] = secret_token
        signed = build_webhook_signature(payload, secret_token)
        outbound_headers['X-Security-Webhook-Timestamp'] = signed['timestamp']
        outbound_headers['X-Security-Webhook-Signature'] = signed['signature']
        outbound_headers['X-Security-Webhook-Signature-Version'] = 'v1'
        request_kwargs['data'] = signed['body']
    else:
        request_kwargs['json'] = payload

    try:
        response = requests.post(url, **request_kwargs)
        ok = 200 <= response.status_code < 300
        return {
            'ok': ok,
            'status': 'sent' if ok else 'failed',
            'reason': response.text[:1000] if response.text else response.reason,
            'response_code': response.status_code,
            'response_body': response.text[:1000] if response.text else '',
        }
    except Exception as exc:
        return {
            'ok': False,
            'status': 'failed',
            'reason': str(exc),
        }
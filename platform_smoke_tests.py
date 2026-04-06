#!/usr/bin/env python3
"""Smoke tests for the SaaS control plane rollout.

Run locally:
  python3 platform_smoke_tests.py \
    --base-url http://127.0.0.1:5000 \
    --email super-admin@example.com \
    --password secret123

Recommended use:
  - staging before rollout
  - immediately after deployment
  - again after rollout-mode changes
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass

import requests


CSRF_PATTERN = re.compile(r'name="csrf_token"\s+value="([^"]+)"')


@dataclass
class SmokeResult:
    passed: int = 0
    failed: int = 0


class PlatformSmokeRunner:
    def __init__(self, *, base_url: str, email: str, password: str, timeout: int = 15):
        self.base_url = base_url.rstrip('/')
        self.email = email
        self.password = password
        self.timeout = timeout
        self.session = requests.Session()
        self.result = SmokeResult()

    def log(self, level: str, message: str) -> None:
        print(f'[{level}] {message}')

    def check(self, name: str, fn) -> bool:
        self.log('TEST', name)
        try:
            fn()
        except Exception as exc:
            self.result.failed += 1
            self.log('FAIL', f'{name}: {exc}')
            return False
        self.result.passed += 1
        self.log('PASS', name)
        return True

    def _assert(self, condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(message)

    def _get(self, path: str, *, allow_redirects: bool = True, expected_status: int | None = None):
        response = self.session.get(f'{self.base_url}{path}', timeout=self.timeout, allow_redirects=allow_redirects)
        if expected_status is not None:
            self._assert(response.status_code == expected_status, f'Expected {expected_status}, got {response.status_code} for {path}')
        return response

    def _post(self, path: str, *, data: dict[str, object], allow_redirects: bool = True, expected_status: int | None = None):
        response = self.session.post(f'{self.base_url}{path}', data=data, timeout=self.timeout, allow_redirects=allow_redirects)
        if expected_status is not None:
            self._assert(response.status_code == expected_status, f'Expected {expected_status}, got {response.status_code} for {path}')
        return response

    def _extract_csrf_token(self, html: str) -> str:
        match = CSRF_PATTERN.search(html)
        self._assert(match is not None, 'CSRF token not found in HTML response')
        return match.group(1)

    def test_login_page(self) -> None:
        response = self._get('/platform/login', expected_status=200)
        self._assert('Platform Login' in response.text, 'Platform login heading missing')
        self._extract_csrf_token(response.text)

    def test_unauthenticated_redirect(self) -> None:
        fresh_session = requests.Session()
        response = fresh_session.get(f'{self.base_url}/platform/schools', timeout=self.timeout, allow_redirects=False)
        self._assert(response.status_code == 302, f'Expected redirect, got {response.status_code}')
        self._assert('/platform/login' in (response.headers.get('Location') or ''), 'Expected redirect to /platform/login')

    def test_login(self) -> None:
        login_page = self._get('/platform/login', expected_status=200)
        csrf_token = self._extract_csrf_token(login_page.text)
        response = self._post(
            '/platform/login',
            data={
                'csrf_token': csrf_token,
                'email': self.email,
                'password': self.password,
            },
            allow_redirects=False,
        )
        self._assert(response.status_code in (302, 303), f'Expected redirect after login, got {response.status_code}')
        location = response.headers.get('Location') or ''
        self._assert(location.endswith('/platform/') or '/platform/' in location, f'Unexpected post-login location: {location}')

    def test_dashboard(self) -> None:
        response = self._get('/platform/', expected_status=200)
        self._assert('Platform' in response.text or 'Dashboard' in response.text, 'Dashboard page did not render expected content')

    def test_metrics_json(self) -> None:
        summary = self._get('/platform/metrics/summary?window_days=14', expected_status=200)
        trends = self._get('/platform/metrics/trends?window_days=30', expected_status=200)
        summary_payload = summary.json()
        trends_payload = trends.json()
        self._assert(isinstance(summary_payload, dict), 'Metrics summary is not a JSON object')
        self._assert(isinstance(trends_payload, dict), 'Metrics trends is not a JSON object')

    def test_operator_pages(self) -> None:
        paths = (
            '/platform/schools',
            '/platform/subscriptions',
            '/platform/reports/pricing',
            '/platform/support',
            '/platform/audit',
            '/platform/security/events',
            '/platform/settings/access',
            '/platform/users',
        )
        for path in paths:
            response = self._get(path, expected_status=200)
            self._assert('<html' in response.text.lower() or '<!doctype html' in response.text.lower(), f'{path} did not return HTML')

    def test_csv_exports(self) -> None:
        export_paths = (
            '/platform/schools/export',
            '/platform/subscriptions/export',
            '/platform/reports/pricing/export',
            '/platform/audit/export',
            '/platform/security/events/export',
        )
        for path in export_paths:
            response = self._get(path, expected_status=200)
            content_type = response.headers.get('Content-Type') or ''
            disposition = response.headers.get('Content-Disposition') or ''
            self._assert('text/csv' in content_type, f'{path} did not return CSV content')
            self._assert('attachment;' in disposition, f'{path} missing attachment disposition')

    def test_logout(self) -> None:
        response = self._get('/platform/logout', allow_redirects=False)
        self._assert(response.status_code in (302, 303), f'Expected redirect after logout, got {response.status_code}')
        protected = self._get('/platform/schools', allow_redirects=False)
        self._assert(protected.status_code == 302, f'Expected redirect after logout, got {protected.status_code}')

    def run(self) -> bool:
        self.log('INFO', f'Base URL: {self.base_url}')
        self.log('INFO', f'Operator: {self.email}')
        tests = (
            ('Platform login page', self.test_login_page),
            ('Unauthenticated redirect', self.test_unauthenticated_redirect),
            ('Platform login', self.test_login),
            ('Dashboard', self.test_dashboard),
            ('Metrics JSON endpoints', self.test_metrics_json),
            ('Operator pages', self.test_operator_pages),
            ('CSV exports', self.test_csv_exports),
            ('Logout', self.test_logout),
        )
        for name, fn in tests:
            self.check(name, fn)
        total = self.result.passed + self.result.failed
        self.log('INFO', f'Summary: {self.result.passed}/{total} passed, {self.result.failed} failed')
        return self.result.failed == 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Smoke tests for the SaaS control plane')
    parser.add_argument('--base-url', default='http://127.0.0.1:5000', help='Base URL for the Flask app')
    parser.add_argument('--email', required=True, help='Platform operator email')
    parser.add_argument('--password', required=True, help='Platform operator password')
    parser.add_argument('--timeout', type=int, default=15, help='HTTP timeout in seconds')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runner = PlatformSmokeRunner(
        base_url=args.base_url,
        email=args.email,
        password=args.password,
        timeout=args.timeout,
    )
    return 0 if runner.run() else 1


if __name__ == '__main__':
    sys.exit(main())
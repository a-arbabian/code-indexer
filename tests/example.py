"""Authentication and request processing utilities.

Demonstrates all features extracted by code-indexer:
module doc, exports, imports, constants, dataclass fields,
class methods with decorators, functions, and test collapsing.
"""

import os
import sys
import unittest
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, List

__all__ = ['Config', 'AuthService', 'process', 'MAX_RETRIES', 'BASE_URL']

MAX_RETRIES: int = 3
TIMEOUT: int = 30
BASE_URL = 'https://api.example.com/v1'
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret')


@dataclass
class Config:
    host: str
    port: int = 8080
    debug: bool = False
    timeout: int = TIMEOUT


class AuthService:
    """Handles token-based authentication."""

    def __init__(self, secret: str, max_retries: int = MAX_RETRIES):
        self.secret = secret
        self.max_retries = max_retries

    @staticmethod
    def validate(token: str) -> bool:
        return len(token) > 0

    @classmethod
    def from_env(cls) -> 'AuthService':
        return cls(secret=SECRET_KEY)

    @property
    def name(self) -> str:
        return self.secret[:8] + '...'


class RequestHandler:
    """Processes incoming requests."""

    def __init__(self, config: Config, auth: AuthService):
        self.config = config
        self.auth = auth

    def handle(self, request: dict) -> dict:
        token = request.get('token', '')
        if not self.auth.validate(token):
            return {'error': 'unauthorized'}
        return self.process(request)

    def process(self, request: dict) -> dict:
        return {'status': 'ok', 'data': request}


def process(data: list) -> dict:
    return {'items': data, 'count': len(data)}


@lru_cache(maxsize=128)
def get_config(host: str, port: int = 8080) -> Config:
    return Config(host=host, port=port)


def _internal_helper(x: int, y: int = 0) -> Optional[int]:
    return x + y if x > 0 else None


# ── tests ─────────────────────────────────────────────────────────────────────

def test_process_empty():
    result = process([])
    assert result == {'items': [], 'count': 0}


def test_process_items():
    result = process([1, 2, 3])
    assert result['count'] == 3


class TestAuthService(unittest.TestCase):
    def setUp(self):
        self.auth = AuthService(secret='test-secret')

    def test_validate_valid_token(self):
        self.assertTrue(self.auth.validate('valid-token'))

    def test_validate_empty_token(self):
        self.assertFalse(self.auth.validate(''))

    def test_from_env(self):
        auth = AuthService.from_env()
        self.assertIsInstance(auth, AuthService)

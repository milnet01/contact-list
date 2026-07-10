import os
import sys

# Isolation: set BEFORE importing config/app (see §10 of the spec).
os.environ.setdefault('SECRET_KEY', 'test-key-not-persisted')
os.environ.setdefault('CONTACT_LIST_DB', '/tmp/contact-list-test.db')

from resources import resource_path


def test_resource_path_from_source():
    # From source: base is the repo root (resources.py's dir).
    got = resource_path('migrations')
    assert got == os.path.join(os.path.dirname(os.path.abspath(__import__('resources').__file__)), 'migrations')


def test_resource_path_uses_meipass_when_set(monkeypatch):
    monkeypatch.setattr(sys, '_MEIPASS', '/tmp/frozen', raising=False)
    assert resource_path('templates') == os.path.join('/tmp/frozen', 'templates')

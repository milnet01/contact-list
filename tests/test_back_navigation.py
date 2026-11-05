"""CL-0120: Back returns to the page you came from -- after starring a
contact on its detail page, from Birthdays and Duplicates, and from the merge
page."""

from __future__ import annotations

import datetime
import html
import re
from urllib.parse import parse_qs, urlparse

import pytest

import models
from app import create_app
from db import get_db


@pytest.fixture()
def app(tmp_path):
    gcreds = tmp_path / 'gcreds'
    return create_app({
        'TESTING': True,
        'DATABASE': str(tmp_path / 'test.db'),
        'SECRET_KEY': 'test-secret',
        'GOOGLE_CREDENTIALS_DIR': str(gcreds),
        'GOOGLE_CREDENTIALS_FILE': str(gcreds / 'creds.json'),
        'GOOGLE_TOKEN_FILE': str(gcreds / 'token.json'),
    })


@pytest.fixture()
def client(app):
    return app.test_client()


def _csrf(client) -> str:
    client.get('/contacts/new')
    with client.session_transaction() as sess:
        return sess.get('_csrf_token', '')


def _back_href(page: str) -> str:
    """The href of the detail page's Back button."""
    m = re.search(r'<a href="([^"]*)" class="btn btn-secondary">\s*<svg[^>]*>.*?</svg>\s*Back',
                  page, re.S)
    assert m, 'no Back button'
    return html.unescape(m.group(1))


def _detail_links(page: str, cid: int) -> list[str]:
    return [html.unescape(h) for h in re.findall(rf'href="(/contacts/{cid}(?:\?[^"]*)?)"', page)]


def _two_dupes(app) -> tuple[int, int]:
    with app.app_context():
        db = get_db()
        return (models.create_contact(db, 'individual', 'Ann', 'ann@x.com'),
                models.create_contact(db, 'individual', 'Ann', None, '555-1'))


class TestStarOnDetail:
    def test_starring_keeps_the_detail_page_and_its_back_target(self, client, app):
        with app.app_context():
            cid = models.create_contact(get_db(), 'individual', 'Ann')
        page = client.get(f'/contacts/{cid}?ref=/contacts?page=2').get_data(as_text=True)
        star = re.search(r'<form[^>]*favourite.*?</form>', page, re.S).group(0)
        ref = re.search(r'name="ref" value="([^"]*)"', star)
        assert ref, 'the star form sends no ref'
        resp = client.post(f'/contacts/{cid}/favourite', data={
            '_csrf_token': _csrf(client), 'favourite': '1',
            'ref': html.unescape(ref.group(1)),
        })
        target = urlparse(resp.headers['Location'])
        assert target.path == f'/contacts/{cid}'
        after = client.get(resp.headers['Location']).get_data(as_text=True)
        assert _back_href(after) == '/contacts?page=2'


class TestLinksCarryTheirPage:
    def test_birthdays_links_carry_birthdays(self, client, app):
        soon = datetime.date.today() + datetime.timedelta(days=1)
        with app.app_context():
            cid = models.create_contact(get_db(), 'individual', 'Bea', custom_fields=[
                ('birthday', f'2000-{soon:%m-%d}')])
        page = client.get('/contacts/birthdays').get_data(as_text=True)
        links = _detail_links(page, cid)
        assert links and all(
            parse_qs(urlparse(h).query).get('ref') == ['/contacts/birthdays'] for h in links)
        detail = client.get(links[0]).get_data(as_text=True)
        assert _back_href(detail) == '/contacts/birthdays'

    def test_duplicates_links_carry_duplicates(self, client, app):
        a, _b = _two_dupes(app)
        page = client.get('/contacts/duplicates').get_data(as_text=True)
        links = _detail_links(page, a)
        assert links and all(
            parse_qs(urlparse(h).query).get('ref') == ['/contacts/duplicates'] for h in links)


class TestMergeReturnsWhereItStarted:
    def _preview(self, client, app, ref: str) -> tuple[str, int, int]:
        a, b = _two_dupes(app)
        page = client.post('/contacts/merge', data={
            '_csrf_token': _csrf(client), 'selected': [str(a), str(b)], 'ref': ref,
        }).get_data(as_text=True)
        return page, a, b

    def test_cancel_returns_to_the_list_it_started_from(self, client, app):
        page, _a, _b = self._preview(client, app, '/contacts?page=2')
        cancel = re.search(r'<a href="([^"]*)" class="btn btn-secondary">Cancel', page)
        assert html.unescape(cancel.group(1)) == '/contacts?page=2'
        crumbs = re.search(r'<nav class="breadcrumb".*?</nav>', page, re.S).group(0)
        assert 'Duplicates' not in crumbs

    def test_from_duplicates_keeps_the_duplicates_crumb(self, client, app):
        page, _a, _b = self._preview(client, app, '/contacts/duplicates')
        cancel = re.search(r'<a href="([^"]*)" class="btn btn-secondary">Cancel', page)
        assert cancel.group(1) == '/contacts/duplicates'
        crumbs = re.search(r'<nav class="breadcrumb".*?</nav>', page, re.S).group(0)
        assert '<a href="/contacts/duplicates">Duplicates</a>' in crumbs

    def test_a_refused_merge_returns_to_where_it_started(self, client, app):
        a, b = _two_dupes(app)
        resp = client.post('/contacts/merge/apply', data={
            '_csrf_token': _csrf(client), 'survivor_id': str(a),
            'loser_id': [str(b)], 'field_type': 'individual', 'field_name': '',
            'cf_count': '0', 'ref': '/contacts?page=2',
        })
        assert resp.headers['Location'] == '/contacts?page=2'

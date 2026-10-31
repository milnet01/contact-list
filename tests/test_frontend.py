"""Rendered-HTML checks for the shared template pieces (readability review)."""
import pytest

from app import create_app


@pytest.fixture()
def client(tmp_path):
    gcreds = tmp_path / 'gcreds'
    app = create_app({
        'TESTING': True,
        'DATABASE': str(tmp_path / 'test.db'),
        'SECRET_KEY': 'test-secret',
        'GOOGLE_CREDENTIALS_DIR': str(gcreds),
        'GOOGLE_CREDENTIALS_FILE': str(gcreds / 'creds.json'),
        'GOOGLE_TOKEN_FILE': str(gcreds / 'token.json'),
    })
    return app.test_client()


def _add(client, names):
    client.get('/contacts/new')
    with client.session_transaction() as sess:
        token = sess['_csrf_token']
    for name in names:
        client.post('/contacts', data={
            '_csrf_token': token, 'type': 'individual', 'name': name,
        })


class TestAvatar:
    def test_non_ascii_initial_uses_the_fallback_class(self, client):
        _add(client, ['Élodie', 'Zed', '9Lives'])
        page = client.get('/contacts').get_data(as_text=True)
        assert 'avatar-É' not in page
        assert 'avatar avatar-other">É' in page
        assert 'avatar avatar-Z">Z' in page
        assert 'avatar avatar-other">9' in page


class TestContactTypeLists:
    def test_every_type_is_offered_on_each_page(self, client, monkeypatch):
        import config
        monkeypatch.setattr(config, 'VALID_CONTACT_TYPES',
                            ('individual', 'company', 'trust'))
        for url in ('/contacts', '/contacts/new', '/settings'):
            page = client.get(url).get_data(as_text=True)
            assert '<option value="trust"' in page, url
            assert '>Trust</option>' in page, url

"""Rendered-HTML checks for the shared template pieces (readability review)."""
import html
import re

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


def _hrefs(page: str) -> list[str]:
    return [html.unescape(h) for h in re.findall(r'href="([^"]*)"', page)]


class TestListLinksKeepFilterState:
    def test_pagination_keeps_sort_and_direction(self, client):
        _add(client, ['Ann', 'Ben', 'Cal'])
        page = client.get('/contacts?per_page=1&sort=name&dir=desc').get_data(as_text=True)
        nxt = [h for h in _hrefs(page) if 'page=2' in h]
        assert nxt and 'sort=name' in nxt[0] and 'dir=desc' in nxt[0]

    def test_alphabet_and_tag_links_keep_sort_and_direction(self, client):
        _add(client, ['Ann'])
        page = client.get('/contacts?sort=name&dir=desc').get_data(as_text=True)
        letter = [h for h in _hrefs(page) if 'letter=A' in h]
        assert letter and 'dir=desc' in letter[0]

    def test_unsorted_url_stays_unsorted(self, client):
        """Without sort in the URL the saved default applies; links add none."""
        _add(client, ['Ann', 'Ben'])
        page = client.get('/contacts?per_page=1').get_data(as_text=True)
        nxt = [h for h in _hrefs(page) if 'page=2' in h]
        assert nxt and 'sort=' not in nxt[0]

    def test_bulk_delete_returns_to_the_filtered_list(self, client):
        _add(client, ['Ann', 'Ben'])
        page = client.get('/contacts?q=A&sort=name').get_data(as_text=True)
        form = page[page.index('id="bulk-form"'):]
        ref = html.unescape(re.search(r'name="ref" value="([^"]*)"', form).group(1))
        assert ref == '/contacts?q=A&sort=name'


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


class TestCustomFieldCaps:
    def test_form_carries_the_model_caps_for_the_script(self, client):
        import models
        page = client.get('/contacts/new').get_data(as_text=True)
        assert f'data-max-fields="{models.MAX_CUSTOM_FIELDS}"' in page
        template = page[page.index('<template id="custom-field-template">'):]
        template = template[:template.index('</template>')]
        assert f'maxlength="{models.MAX_CF_NAME_LEN}"' in template
        assert f'maxlength="{models.MAX_CF_VALUE_LEN}"' in template

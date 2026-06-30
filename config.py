import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or os.urandom(32).hex()
    DATABASE = os.environ.get(
        'CONTACT_LIST_DB',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contacts.db'),
    )
    GOOGLE_CREDENTIALS_DIR = os.path.expanduser('~/.config/contact-list')
    GOOGLE_CREDENTIALS_FILE = os.path.join(GOOGLE_CREDENTIALS_DIR, 'credentials.json')
    GOOGLE_TOKEN_FILE = os.path.join(GOOGLE_CREDENTIALS_DIR, 'token.json')
    PORT = int(os.environ.get('CONTACT_LIST_PORT', 5002))
    CONTACTS_PER_PAGE = 50
    MAX_CONTACTS_PER_PAGE = 200

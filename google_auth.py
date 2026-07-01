#!/usr/bin/env python3
"""Standalone Google OAuth authentication for Contact List.

Uses InstalledAppFlow (Desktop client) which opens a browser,
handles the callback on a temporary local port, and saves the token.
"""
from __future__ import annotations

import os
import sys

SCOPES = ['https://www.googleapis.com/auth/contacts.readonly']
CREDS_DIR = os.path.expanduser('~/.config/contact-list')
CREDS_FILE = os.path.join(CREDS_DIR, 'credentials.json')
TOKEN_FILE = os.path.join(CREDS_DIR, 'token.json')


def main() -> int:
    if not os.path.isfile(CREDS_FILE):
        print(f'Error: credentials file not found at {CREDS_FILE}', file=sys.stderr)
        print('Download Desktop OAuth credentials from Google Cloud Console.', file=sys.stderr)
        return 1

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)

    # Lock the config dir to 0700 (defence-in-depth for the token; CL-0011).
    # Inlined rather than importing config, to keep this auth script standalone.
    os.makedirs(CREDS_DIR, exist_ok=True)
    try:
        os.chmod(CREDS_DIR, 0o700)
    except OSError:
        pass
    # Create with 0600 from the start so the token is never briefly
    # world-readable between write and chmod.
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(creds.to_json())
    os.chmod(TOKEN_FILE, 0o600)

    print('Authenticated successfully. You can close this window.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Standalone Google OAuth authentication for Contact List.

Uses InstalledAppFlow (Desktop client) which opens a browser,
handles the callback on a temporary local port, and saves the token.
"""
from __future__ import annotations

import os
import sys

# Single source of truth for the OAuth scope (CL-0033, INV-5): importing it here
# means this standalone auth script can never request a different scope than the
# app's sync code. google_sync pulls in the app's own modules and libraries
# (phonenumbers, Pillow) at import, so this script needs the same environment as
# the app.
from config import Config, ensure_private_dir, write_private_text
from google_sync import SCOPES

CREDS_FILE = Config.GOOGLE_CREDENTIALS_FILE
TOKEN_FILE = Config.GOOGLE_TOKEN_FILE


def main() -> int:
    if not os.path.isfile(CREDS_FILE):
        print(f'Error: credentials file not found at {CREDS_FILE}', file=sys.stderr)
        print('Download Desktop OAuth credentials from Google Cloud Console.', file=sys.stderr)
        return 1

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
    creds = flow.run_local_server(port=0, open_browser=True)

    ensure_private_dir(os.path.dirname(TOKEN_FILE))
    write_private_text(TOKEN_FILE, creds.to_json())

    print('Authenticated successfully. You can close this window.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

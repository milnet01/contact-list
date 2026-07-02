"""Contact photo storage and validation (CL-0026).

Photos are stored as files under ``config['PHOTOS_DIR']`` named
``<contact_id>.<ext>``. Uploads and Google-synced downloads are validated by
magic bytes (an allow-list of JPEG/PNG/GIF/WebP) and a size cap, rather than
decoded/re-encoded — DESIGN.md §3 bars non-stdlib C-extension deps, so no
Pillow. Served same-origin with ``nosniff``, a disguised file can't execute.

DB access (the ``contact_photos`` table) stays in ``models.py``; this module
only touches the filesystem and raw bytes.
"""

from __future__ import annotations

import os

from config import ensure_private_dir

# Deliberately below the app-wide MAX_CONTENT_LENGTH (5 MiB, config.py) so an
# oversize upload reaches our friendly ValueError flash instead of Flask's raw
# 413, with headroom for multipart form overhead.
MAX_PHOTO_BYTES = 4 * 1024 * 1024

_MIME = {
    'jpg': 'image/jpeg',
    'png': 'image/png',
    'gif': 'image/gif',
    'webp': 'image/webp',
}


def detect_image_ext(data: bytes) -> str | None:
    """Return the file extension for a recognised image, else None.

    Matches leading magic bytes only — never a client-supplied name or
    content-type. SVG and everything else are rejected. Slices past the end of
    a short input simply won't match, so short/empty input returns None.
    """
    if data[:3] == b'\xff\xd8\xff':
        return 'jpg'
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if data[:4] == b'GIF8':  # covers GIF87a and GIF89a
        return 'gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    return None


def mime_for_ext(ext: str) -> str:
    """MIME type for a stored extension (falls back to octet-stream)."""
    return _MIME.get(ext, 'application/octet-stream')


def _photo_path(config, contact_id: int, ext: str) -> str:
    # int() on the id + an allow-listed ext means no request string reaches the
    # path — no traversal vector.
    return os.path.join(config['PHOTOS_DIR'], f'{int(contact_id)}.{ext}')


def save_photo(config, contact_id: int, data: bytes, *, old_ext: str | None = None) -> str:
    """Validate ``data`` and store it as ``<contact_id>.<ext>``. Return the ext.

    Checks size first (so an oversize non-image is reported as oversize), then
    magic bytes. Raises ``ValueError`` on either reject. Removes any existing
    file at ``old_ext`` first (the new ext may differ, e.g. png -> jpg).
    """
    if len(data) > MAX_PHOTO_BYTES:
        raise ValueError('Photo exceeds the size limit')
    ext = detect_image_ext(data)
    if ext is None:
        raise ValueError('Unsupported image type')

    if old_ext:
        delete_photo(config, contact_id, old_ext)

    ensure_private_dir(config['PHOTOS_DIR'])
    with open(_photo_path(config, contact_id, ext), 'wb') as fh:
        fh.write(data)
    return ext


def delete_photo(config, contact_id: int, ext: str | None) -> None:
    """Remove a contact's photo file. No-op if ``ext`` is falsy or file absent."""
    if not ext:
        return
    try:
        os.remove(_photo_path(config, contact_id, ext))
    except FileNotFoundError:
        pass

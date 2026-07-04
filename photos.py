"""Contact photo storage, validation, and thumbnailing (CL-0026, CL-0035).

Photos are stored as files under ``config['PHOTOS_DIR']`` named
``<contact_id>.<ext>``, with a downscaled 256 px thumbnail alongside as
``<contact_id>_thumb.<ext>`` (CL-0035). Uploads and Google-synced downloads are
validated by **magic bytes** (an allow-list of JPEG/PNG/GIF/WebP) and a size cap
*before* anything else — that magic-byte check remains the gatekeeper. Pillow is
then used only to generate the thumbnail from the already-validated, size-capped
bytes; thumbnail failures are non-fatal (the full-size original is kept and
served). Served same-origin with ``nosniff``, a disguised file can't execute.

DB access (the ``contact_photos`` table) stays in ``models.py``; this module
only touches the filesystem and raw bytes.
"""

from __future__ import annotations

import io
import os

from PIL import Image, ImageOps

from config import ensure_private_dir

# Deliberately below the app-wide MAX_CONTENT_LENGTH (5 MiB, config.py) so an
# oversize upload reaches our friendly ValueError flash instead of Flask's raw
# 413, with headroom for multipart form overhead.
MAX_PHOTO_BYTES = 4 * 1024 * 1024

# CL-0035: the longest edge of a stored thumbnail. Avatars display at ~35 px
# (list) / ~56 px (detail); 256 px stays crisp on those with Retina/zoom
# headroom while turning a multi-MB upload into a ~20-40 KB avatar payload.
THUMBNAIL_MAX_PX = 256

_MIME = {
    'jpg': 'image/jpeg',
    'png': 'image/png',
    'gif': 'image/gif',
    'webp': 'image/webp',
}

# Stored ext -> Pillow save format. Every ext detect_image_ext can return is a
# key here, so the .get() default is an unreachable defensive branch.
_PIL_FORMAT = {'jpg': 'JPEG', 'png': 'PNG', 'gif': 'GIF', 'webp': 'WEBP'}


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


def generate_thumbnail(data: bytes, ext: str) -> bytes:
    """Downscale image ``data`` to fit a THUMBNAIL_MAX_PX box; return the bytes.

    Aspect ratio is preserved and the image is never upscaled (``thumbnail`` only
    shrinks). EXIF orientation is applied so phone photos aren't sideways. The
    result is re-encoded in the original container format (``ext``). Palette/1-bit
    inputs (e.g. GIF) are promoted to RGB(A) so the LANCZOS resample is valid.
    Raises ``ValueError`` if the bytes can't be decoded/encoded — callers treat
    that as "no thumbnail" (non-fatal), never as a hard error.
    """
    try:
        with Image.open(io.BytesIO(data)) as src:
            img = ImageOps.exif_transpose(src)           # honour phone rotation
            if img.mode in ('P', '1'):
                img = img.convert('RGBA' if 'transparency' in img.info else 'RGB')
            img.thumbnail((THUMBNAIL_MAX_PX, THUMBNAIL_MAX_PX), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            fmt = _PIL_FORMAT.get(ext, 'PNG')
            kwargs = {}
            if fmt in ('JPEG', 'WEBP'):
                kwargs['quality'] = 85
            if fmt in ('JPEG', 'PNG'):
                kwargs['optimize'] = True
            img.save(out, format=fmt, **kwargs)
            return out.getvalue()
    except Exception as exc:
        # Decode/encode of untrusted image bytes is a trust boundary: Pillow can
        # raise OSError, ValueError, Image.DecompressionBombError (a direct
        # Exception subclass — NOT OSError/ValueError), SyntaxError, EOFError, etc.
        # depending on the codec and the malformation. We can't enumerate them,
        # and the whole contract here is "any failure -> no thumbnail", so we
        # catch broadly at this one boundary and normalise to a single ValueError
        # that call-sites catch (the project "specific-exceptions" rule holds
        # everywhere except this documented boundary).
        raise ValueError(f'Cannot generate thumbnail: {exc}') from exc


def _photo_path(config, contact_id: int, ext: str) -> str:
    # int() on the id + an allow-listed ext means no request string reaches the
    # path — no traversal vector.
    return os.path.join(config['PHOTOS_DIR'], f'{int(contact_id)}.{ext}')


def _thumb_path(config, contact_id: int, ext: str) -> str:
    # Same traversal guarantee as _photo_path: int id + allow-listed ext + a
    # fixed literal suffix.
    return os.path.join(config['PHOTOS_DIR'], f'{int(contact_id)}_thumb.{ext}')


def _write_thumbnail(config, contact_id: int, ext: str, data: bytes) -> bool:
    """Generate + atomically write a contact's thumbnail. Return success.

    Returns ``True`` when a thumbnail was written, ``False`` on any swallowed
    failure — both an undecodable body (``generate_thumbnail`` raising
    ``ValueError``) and a filesystem write error (``OSError``: disk full,
    permission, cross-device ``os.replace``). Either way no thumbnail is left and
    the caller falls back to the full-size original. Swallowing the write
    ``OSError`` is what keeps the lazy serve path (which writes on a GET) from
    ever 500-ing where the old read-only route could not.
    """
    try:
        thumb_bytes = generate_thumbnail(data, ext)
    except ValueError:
        return False
    ensure_private_dir(config['PHOTOS_DIR'])
    final = _thumb_path(config, contact_id, ext)
    tmp = f'{final}.{os.getpid()}.tmp'
    try:
        with open(tmp, 'wb') as fh:
            fh.write(thumb_bytes)
        os.replace(tmp, final)           # atomic: a concurrent GET never sees a torn file
        return True
    except OSError:
        try:
            os.remove(tmp)
        except FileNotFoundError:
            pass
        return False


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
    # Eager thumbnail (CL-0035): the common upload/sync case has its avatar ready
    # before the first request. Non-fatal — the original is the source of truth.
    _write_thumbnail(config, contact_id, ext, data)
    return ext


def avatar_filename(config, contact_id: int, ext: str) -> str:
    """Return the basename to serve for a contact's avatar (CL-0035).

    Prefer the cached ``<id>_thumb.<ext>``. If it is missing (a photo saved
    before thumbnails existed, or a cleared cache) regenerate it lazily from the
    stored original — self-healing. If the original is unreadable or Pillow can't
    decode it, fall back to the original basename so the avatar still renders (the
    pre-CL-0035 behaviour). Always a basename, never a path, so
    ``send_from_directory``'s traversal/404 guarantees are preserved.
    """
    thumb_name = f'{int(contact_id)}_thumb.{ext}'
    if os.path.exists(_thumb_path(config, contact_id, ext)):
        return thumb_name
    orig_name = f'{int(contact_id)}.{ext}'
    try:
        with open(_photo_path(config, contact_id, ext), 'rb') as fh:
            data = fh.read()
    except OSError:
        return orig_name                 # original gone — let send_from_directory 404
    if _write_thumbnail(config, contact_id, ext, data):
        return thumb_name
    return orig_name                     # undecodable original — serve it full-size


def delete_photo(config, contact_id: int, ext: str | None) -> None:
    """Remove a contact's photo file and its thumbnail. No-op if ``ext`` is falsy
    or the files are absent."""
    if not ext:
        return
    for path in (_thumb_path(config, contact_id, ext), _photo_path(config, contact_id, ext)):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

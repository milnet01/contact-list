# Photo Thumbnails — Design (CL-0035)

Status: **Signed off** (2026-07-04) — passed `/cold-eyes` to convergence
(10 loops: findings decayed from a real decompression-bomb exception-taxonomy
catch → doc-vs-code accuracy fixes → a genuine "track-latest" Pillow-major
violation caught at loop 8 → clean at loop 10; zero verified findings on the
final pass). Signed off by the implementing session per the project's delegated
sign-off convention. Ready to implement.
Date: 2026-07-04

> **Confirmed design decisions (user-approved 2026-07-04):**
> 1. **Single 256 px thumbnail** (spec §3 — Sizing), not the roadmap's tentative
>    "e.g. 128px" and not a two-size (list + detail) scheme. The CSS avatars are
>    2.2 rem (~35 px, list) and 3.5 rem (~56 px, `avatar-lg` detail/edit); 256 px
>    stays crisp on the larger one with generous headroom for 2–3× / Retina
>    displays and browser zoom, is still ~20–40 KB, and one size = one file + one
>    code path (no over-engineering for a single-user app).
> 2. **Keep the full original on disk; no download link yet** (spec §9 — Out of
>    scope). The original stays as the source of truth (re-thumbnailing, future
>    download) but no "view full photo" UI is added in this scope — that avoids
>    shipping an unused route/link and can be its own small roadmap item.
> 3. **Pillow is added** (spec §2). The user lifted the standing no-C-extension
>    dependency ban specifically for this item (ROADMAP CL-0035).

This change also amends several project docs alongside the code — DESIGN.md §3
and §14, DESIGN.md §6's File-uploads security row, the `photos.py` module
docstring, and the 2026-07-01 photos spec — plus the routine ROADMAP/CHANGELOG
entries on ship. (CLAUDE.md's dependency convention is a cap with no live count
and no C-extension clause, so it needs verifying, not editing.) §7 is the
authoritative, itemised list.

Sections: [1 Overview](#1-overview) · [2 Dependency change](#2-dependency-change-pillow) ·
[3 Thumbnail generation](#3-thumbnail-generation) · [4 Lifecycle](#4-storage-lifecycle) ·
[5 Serve route](#5-serve-route) · [6 Security](#6-security-considerations) ·
[7 Doc amendments](#7-doc-amendments) · [8 Testing](#8-testing) ·
[9 Out of scope](#9-out-of-scope) · [10 Invariants](#10-invariants).

## 1. Overview

Contact avatars render at ~35 px (list rows, 2.2 rem) and ~56 px (detail /
edit-form `avatar-lg`, 3.5 rem), but the app currently serves the **full-size
upload** (up to 4 MiB)
for every one. A list of 50 photographed contacts can push tens of megabytes over
localhost on each page load.

This change generates a small **256 px** thumbnail when a photo is saved and
serves *that* for avatars. The full original is kept on disk unchanged (source of
truth; future download). Every photo save already funnels through
`photos.save_photo` (both the upload route `routes/contacts.py::_apply_photo` and
Google sync `google_sync.py::_store_person_photo`), and every delete through
`photos.delete_photo`, so the thumbnail lifecycle lives **entirely inside
`photos.py`** — the two call-sites are untouched.

Single-user, localhost only. The only new moving part is the Pillow dependency
and one new serve-time helper.

## 2. Dependency change (Pillow)

`photos.py` today validates images by **magic bytes only** (an allow-list of
JPEG/PNG/GIF/WebP) and never decodes them — a deliberate choice recorded in
DESIGN.md §3 ("No C-extension dependencies beyond what ships with Python") and the
2026-07-01 contact-photos spec. Generating a downscaled raster **requires
decoding and re-encoding**, which stdlib cannot do for these formats. The user has
lifted the ban for this item.

- **Package:** `Pillow` (imported as `PIL`). Widely-used, actively-maintained
  imaging library; the standard choice for this task.
- **Budget:** runtime direct deps go 6 → **7**, still under the DESIGN.md §3
  `< 8` cap. `requirements.txt` gains `pillow>=12.0,<13.0` (major-capped, per the
  project's "cap the major, install the newest within it" policy).
- **Versioning:** Pillow tracks its latest stable release like every other dep
  (DESIGN.md §3 versioning policy) — this matters especially because Pillow's
  security fixes ship in point releases (§6).

**Magic-byte validation is retained.** Pillow does **not** become the validator:
`detect_image_ext` still runs first and is still what decides "is this an allowed
image and what is its ext". Pillow only ever runs on bytes that already passed the
magic-byte allow-list and the 4 MiB size cap (§6, defence in depth).

## 3. Thumbnail generation

New in `photos.py`:

```python
import io
from PIL import Image, ImageOps

THUMBNAIL_MAX_PX = 256

_PIL_FORMAT = {'jpg': 'JPEG', 'png': 'PNG', 'gif': 'GIF', 'webp': 'WEBP'}


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
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)           # honour phone rotation
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
        # depending on the codec and the malformation. We cannot enumerate them,
        # and the whole contract here is "any failure -> no thumbnail". So we
        # catch broadly at this one boundary and normalise to a single ValueError
        # — call-sites then catch that specific type (project "specific-exceptions"
        # rule holds everywhere except this documented boundary).
        raise ValueError(f'Cannot generate thumbnail: {exc}') from exc
```

Design notes:
- **Sizing:** one 256 px longest-edge bound. A non-square photo yields a
  non-square thumbnail (aspect ratio preserved — **no server-side crop**). The
  display is unchanged from today: `img.avatar` uses `object-fit: cover`
  (`static/style.css:420`), which center-crops the image into the circular box —
  the thumbnail feeds that exactly as the full-size image does now, so the visible
  result is identical, just far fewer bytes.
- **Resample = LANCZOS:** best-quality downscale; the current Pillow idiom is
  `Image.Resampling.LANCZOS` (the module-level `Image.LANCZOS` alias is
  deprecated). Palette/1-bit modes are converted to RGB(A) first because LANCZOS
  cannot resample those modes.
- **Format preserved:** the thumbnail keeps the original container (`ext`), so
  `mime_for_ext(ext)` serves both the thumbnail and (future) original with the
  same MIME, and transparency/format expectations are unchanged. Animated
  GIF/WebP collapse to the first frame — acceptable for a tiny static avatar.
  (`ext` is always one of the four allow-listed values `detect_image_ext` can
  return, so the `_PIL_FORMAT.get(ext, 'PNG')` default is an unreachable defensive
  branch, never a silent format switch.)
- **Failure is non-fatal by design.** `generate_thumbnail` raising is handled by
  its callers (§4/§5): the original stays the source of truth and is served
  full-size, i.e. today's behaviour. This is why the change never regresses an
  existing photo and why the fake-magic-byte fixtures in `tests/test_photos.py`
  (valid header, undecodable body) keep passing — the original is still written.

## 4. Storage lifecycle

Files in `PHOTOS_DIR`:
- Original: `<id>.<ext>` (unchanged, e.g. `7.png`).
- Thumbnail: `<id>_thumb.<ext>` (new, e.g. `7_thumb.png`).

Both basenames are built from `int(contact_id)` + an allow-listed `ext` + a fixed
literal suffix — no request-derived string reaches the path (no traversal vector),
same guarantee as the existing `_photo_path`.

Changes to `photos.py` — two new helpers (`_thumb_path`, `_write_thumbnail`) and
two existing functions modified (`save_photo`, `delete_photo`):

- **`_thumb_path(config, contact_id, ext)`** — new, mirrors `_photo_path`, returns
  `<dir>/<id>_thumb.<ext>`.
- **`_write_thumbnail(config, contact_id, ext, data) -> bool`** — new;
  validates+writes a thumbnail atomically (temp file in the same dir +
  `os.replace`), so a concurrent avatar GET never observes a half-written
  thumbnail. **Returns `True` when a thumbnail was written, `False` on any
  swallowed failure** — both `generate_thumbnail` raising `ValueError` (undecodable
  bytes) **and** its own filesystem write raising `OSError` (disk full, permission,
  cross-device `os.replace`) are caught and turned into `False`, leaving no
  thumbnail. This bool is what `avatar_filename` (§5) branches on, so it need not
  re-`os.path.exists` the thumb path. Crucially, catching the write `OSError` keeps
  the **lazy serve path** (§5) non-throwing: unlike today's read-only `photo` route,
  it writes on a GET, so an unswallowed write error would be a new way for a GET to
  500 (INV-4/INV-6). Shared by the eager (§4) and lazy (§5) paths — one write path.
  The swallows carry a comment naming the constraint (Pillow can fail on a
  magic-valid but corrupt/exotic body; a full/read-only disk can fail the write;
  both non-fatal by design — §3).
- **`save_photo(...)`** — after writing the original (unchanged), call
  `_write_thumbnail`. This makes the **eager** thumbnail: the common case (a fresh
  upload / sync) has its thumbnail ready before the first avatar request. Return
  value (the ext) is unchanged, so both call-sites and their tests are unaffected.
- **`delete_photo(config, contact_id, ext)`** — additionally unlink
  `_thumb_path` (same `FileNotFoundError`-ignored pattern). Because `save_photo`
  deletes `old_ext` first, replacing a `png` with a `jpg` removes both `<id>.png`
  and `<id>_thumb.png` before writing the new pair — no orphan thumbnail of the
  old ext is left behind.

## 5. Serve route

The one avatar route, `routes/contacts.py::photo` (`GET /contacts/<id>/photo`),
switches from serving the original to serving the thumbnail, with a lazy
fallback for photos saved before this change (or a cleared thumbnail):

```python
@bp.route('/contacts/<int:contact_id>/photo')
def photo(contact_id: int):
    db = get_db()
    ext = get_contact_photo_ext(db, contact_id)
    if not ext:
        abort(404)
    filename = photos.avatar_filename(current_app.config, contact_id, ext)
    return send_from_directory(
        current_app.config['PHOTOS_DIR'],
        filename,
        mimetype=photos.mime_for_ext(ext),
        max_age=86400,
    )
```

New `photos.avatar_filename(config, contact_id, ext) -> str` returns the
**basename** to serve:
1. If `<id>_thumb.<ext>` exists → return it.
2. Else **read the original `<id>.<ext>` bytes** and pass them to
   `_write_thumbnail(config, contact_id, ext, data)` (§4 — it takes decoded
   *bytes*, not a path, so `avatar_filename` does the `open()`/read). If it returns
   `True`, return the thumbnail basename. This **self-heals** pre-existing photos
   on first view and after a manual cache clear.
3. If the original is missing (the read raises `OSError`) or `_write_thumbnail`
   returns `False` (Pillow couldn't decode it — the `ValueError` was swallowed,
   no thumbnail left) → return the **original** basename `<id>.<ext>` (full-size
   fallback — today's behaviour; if the original is also missing,
   `send_from_directory` 404s exactly as before).

`avatar_filename` returns a basename (never a path) so the existing
`send_from_directory` traversal/`404`-on-missing guarantees are preserved
verbatim. The `max_age=86400` browser cache and the `nosniff` header (set app-wide)
are unchanged — the response is byte-for-byte cacheable just as the full-size one
was. The route's existing traversal-safety and cache-rationale comment
(`routes/contacts.py:262-266`) is **retained**, not deleted — the code block above
elides it only for brevity.

One transient consequence of keeping `max_age=86400`: on the first view of a
pre-change photo (self-heal) or a same-ext replace, a browser that already cached
the full-size bytes keeps serving them for up to a day until the cache entry
expires. This is pre-existing avatar-cache behaviour, transient, and single-user —
acceptable, noted here so it isn't mistaken for an omission. (A cache-busting
query param on the `url_for` is a possible future refinement, out of scope.)

Consequence: the **detail** and **edit-form** avatars (`avatar-lg`, ~56 px) and
the **list** avatars (~35 px) all now receive the 256 px thumbnail. No template
changes are required — the three `url_for('contacts.photo', ...)` call-sites are
untouched.

## 6. Security considerations

The 2026-07-01 photos spec rejected Pillow precisely because *decoding untrusted
image bytes* enlarges the attack surface (codec CVEs, decompression bombs). That
reasoning is sound and is addressed here rather than dismissed:

- **Validation is unchanged and still comes first.** On the save path,
  `detect_image_ext` (magic-byte allow-list) and the 4 MiB `MAX_PHOTO_BYTES` cap
  run **before** the photo is ever stored; the lazy self-heal path (§5 step 2)
  then only ever decodes bytes read back from an **already-stored, already-validated**
  original — it does not re-admit new bytes. So Pillow never sees bytes that
  failed the allow-list, and never decides the file type. SVG and non-images are
  still rejected up front.
- **Decompression bombs:** Pillow's built-in `Image.MAX_IMAGE_PIXELS` guard
  (~89 M px default) raises `Image.DecompressionBombError` on a pathological
  small-file-huge-canvas image; combined with the 4 MiB input cap this bounds
  decode cost. That error is one of the decode-boundary failures §3's broad
  `except Exception` catches and normalises to `ValueError` → no thumbnail, the
  original is served → **non-fatal**, no crash, no DoS of the request beyond that
  one avatar.
- **The thumbnail is never executed.** Like the original, it is served
  same-origin with `X-Content-Type-Options: nosniff` and a fixed MIME; a disguised
  payload cannot run in the browser.
- **Latest-Pillow policy (DESIGN.md §3).** Pillow security fixes land in point
  releases; the project's "track latest" rule and the `<13.0` major cap mean those
  fixes are pulled in promptly. This is recorded in DESIGN.md §3's dependency
  audit snapshot (§7).
- **No new input reaches the filesystem path.** Thumbnail filenames are
  `int(id) + allow-listed ext + literal suffix` (§4), so adding Pillow does not
  add a path-traversal vector.

Net: the decode surface grows by exactly one well-known library, gated behind the
pre-existing allow-list + size cap, with failures degrading gracefully. Acceptable
for a single-user localhost app, and explicitly authorised by the user for this
item.

## 7. Doc amendments

Applied in the same change-set as the implementation:

- **`requirements.txt` (the actual manifest):** add `pillow>=12.0,<13.0`. This is
  the functional dependency edit — without it the `from PIL import ...` at the top
  of `photos.py` (§3) `ModuleNotFoundError`s. Listed first so a checklist-follower
  can't miss it (the DESIGN.md fenced block below is documentation, not the
  installed manifest).
- **DESIGN.md §3 (Dependency Budget):** change "No C-extension dependencies
  beyond what ships with Python" to permit Pillow (the one authorised exception,
  for CL-0035 thumbnailing); add `pillow>=12.0,<13.0` to **DESIGN.md §3's fenced
  runtime list** (the illustrative block, DESIGN.md:44-50 — mirrors, but is not,
  `requirements.txt`); update "Six runtime packages" → "Seven runtime packages
  (under the 8-direct budget)";
  and update the `Audited:` version-snapshot note inside the Breakage Register's
  `_None_` row to add `pillow` at the actual latest 12.x installed (12.3.0 at time
  of writing) and re-date it 2026-07-04. (Pillow tracks latest, so it is **not** a
  new exception/below-latest row — the register stays `_None_`; only its audit
  snapshot gains the entry.)
- **`photos.py` module docstring:** replace the "so no Pillow" sentence with a
  description of the 256 px thumbnail behaviour, noting magic-byte validation is
  retained and runs before any decode.
- **`docs/specs/2026-07-01-contact-photos-design.md`:** add a dated one-line note
  at its "Why no image library" / "no server-side resizing" points that CL-0035
  supersedes that decision (security addressed in this spec §6). The historical
  spec's Status stays Implemented; the note is a forward pointer, not a rewrite.
- **DESIGN.md §6 (Security — File uploads row, DESIGN.md:253):** the row currently
  reads "validated by magic bytes … and a 4 MiB cap … served same-origin with
  `nosniff`" — written for a no-decode module. Append a short clause that CL-0035
  thumbnailing now decodes/re-encodes via Pillow **behind** that allow-list + cap
  (see this spec §6), so the row's security posture stays accurate and doesn't lag
  the `photos.py` docstring update below.
- **CLAUDE.md (project):** the dependency convention is "budget: <8 direct pip
  packages" — a cap, not a live count, and there is no C-extension clause. So this
  is a **verify, expected no-op** — only edit if a specific number is present.
- **DESIGN.md §14 (File Size Budget):** the shipped-`.py` **source** row
  (`< 100 KB` soft) is unaffected — `photos.py` grows only ~50–70 LOC. But §14
  also has a **`Total pip install | < 20 MB`** row, which Pillow *does* hit:
  ~21 MB installed (PIL 7 MB + `pillow.libs` 14 MB). That row is **already** far
  exceeded — ~296 MB actual, dominated by `googleapiclient` (~100 MB) and
  `phonenumbers` (~46 MB) — so it is a stale/aspirational figure, not a live gate;
  ROADMAP CL-0044 is filed to re-baseline or retire it. Don't silently paper over
  the pip-install row: leave the shipped-`.py` soft target as the meaningful budget
  and let the ROADMAP item track the pip-install reality.
- **ROADMAP.md:** flip CL-0035 to shipped with a resolution note on implementation.
- **CHANGELOG.md:** one `Changed`/`Added` entry under Unreleased.

## 8. Testing

Extends `tests/test_photos.py` and `tests/test_routes.py`. Because the existing
fixtures are **fake** magic-byte blobs (undecodable), the new decode-path tests
build **real** images with Pillow (now a dependency) via a small helper:

```python
def _real_png(w, h):
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (10, 120, 200)).save(buf, format='PNG')
    return buf.getvalue()
```

- **`generate_thumbnail` downscales:** a 512×512 real PNG → the result opened with
  Pillow has `max(size) == 256`; a 100×80 image is returned **unchanged in
  dimensions** (never upscaled), still ≤ 256.
- **`generate_thumbnail` rejects junk:** a fake magic-byte `PNG` (valid header,
  garbage body) raises `ValueError`.
- **EXIF orientation (firm test):** build a landscape image tagged orientation-6
  (`img.getexif()[0x0112] = 6`, saved as JPEG with that `exif=`), thumbnail it, and
  assert the result's height > width — i.e. `exif_transpose` rotated it upright.
  The fixture is a few lines with Pillow, so this is a hard assertion, not a smoke
  test.
- **`save_photo` writes both files:** a real PNG produces `<id>.png` **and**
  `<id>_thumb.png`; the thumbnail's decoded max-dimension is ≤ 256 and the
  original's bytes are untouched (equal to input).
- **`save_photo` on a fake blob still writes the original** (thumbnail generation
  fails silently) — the existing `TestSavePhoto` cases keep passing unchanged;
  add one asserting **no** `_thumb` file is left for the undecodable input.
- **`delete_photo` removes both** original and thumbnail; missing thumbnail is
  ignored (no raise).
- **Replace ext removes old thumbnail:** save real PNG, then save real JPEG with
  `old_ext='png'` → neither `<id>.png` nor `<id>_thumb.png` remains; `<id>.jpg`
  and `<id>_thumb.jpg` do.
- **`avatar_filename` lazy path:** write only an original `<id>.png` (no thumb),
  call `avatar_filename` → `<id>_thumb.png` now exists and is returned. Second
  call returns it without regenerating.
- **`avatar_filename` fallback:** with an undecodable original present (fake blob)
  → returns the **original** basename (no thumb created, no raise).
- **Route (`test_routes.py`):** upload a real >256 px PNG, `GET
  /contacts/<id>/photo` → 200, and the returned body opened with Pillow has
  `max(size) == 256` (proves the thumbnail, not the original, is served). The
  existing cacheability / 404 / detail-shows-img / remove-photo cases stay green
  (they use the fake fixture, which now serves the full-size fallback — still 200).

## 9. Out of scope

- **A "download / view full photo" link or route.** The original is retained on
  disk for it, but no UI/route is added now (confirmed decision 2 above). Natural
  follow-up roadmap item.
- **Server-side cropping to a square.** The stored thumbnail stays
  aspect-preserved (no server crop); the display center-crops via
  `object-fit: cover` into the circle exactly as today — no new face-centred crop
  logic is added.
- **A background/batch migration** to pre-generate thumbnails for all existing
  photos. Unnecessary — §5's lazy path self-heals each on first view; a single-user
  library is tiny.
- **Two-size (list vs detail) thumbnails / `srcset`.** One 256 px thumbnail is
  crisp for both sizes incl. Retina; multi-size is over-engineering here.
- **Stripping the original after thumbnailing** to reclaim disk. The original is
  deliberately kept (source of truth, future download).

## 10. Invariants

| ID | Invariant | Test surface |
|----|-----------|--------------|
| INV-1 | A saved, decodable photo yields both `<id>.<ext>` and `<id>_thumb.<ext>`; the thumbnail's longest edge is ≤ 256 px. | `test_photos.py` save-writes-both |
| INV-2 | The original file's bytes are never altered by thumbnailing (source of truth preserved). | `test_photos.py` original-bytes-unchanged |
| INV-3 | Thumbnails preserve aspect ratio and never upscale (a ≤ 256 px input is returned at its original dimensions). | `test_photos.py` downscale / no-upscale |
| INV-3b | EXIF orientation is applied so rotated phone photos come back upright. | `test_photos.py` orientation-6 landscape → thumbnail height > width |
| INV-4 | Any thumbnail failure — undecodable bytes *or* a filesystem write error — is non-fatal: the original is still saved and is served full-size; no exception escapes `save_photo` or the serve route (incl. the lazy write on a GET). | `test_photos.py` fake-blob save + fallback |
| INV-5 | `delete_photo` and an ext-changing `save_photo` remove the matching `_thumb` file — no orphan thumbnails. | `test_photos.py` delete / replace-ext |
| INV-6 | The avatar route serves the thumbnail when available, lazily generates it when missing, and falls back to the original otherwise — always via a `send_from_directory` basename (no traversal). | `test_photos.py` avatar_filename + `test_routes.py` served-body-is-256 |
| INV-7 | Pillow only ever decodes bytes that passed `detect_image_ext` + the 4 MiB cap **when first saved** (the lazy path re-decodes an already-validated stored original, never fresh input); magic-byte validation remains the gatekeeper. | code review (§6) + `test_photos.py` junk-rejected |

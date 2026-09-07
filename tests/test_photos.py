"""Tests for photos.py — image validation, on-disk storage (CL-0026), and
256 px thumbnail generation (CL-0035)."""

import io
import os
import tempfile

import pytest
from PIL import Image

import photos

# Minimal valid magic-byte prefixes padded with filler. These are DELIBERATELY
# undecodable (valid header, garbage body) — Pillow can't open them, which
# exercises the non-fatal thumbnail-failure path.
JPEG = b'\xff\xd8\xff' + b'\x00' * 20
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 20
GIF87 = b'GIF87a' + b'\x00' * 20
GIF89 = b'GIF89a' + b'\x00' * 20
WEBP = b'RIFF' + b'\x00\x00\x00\x00' + b'WEBP' + b'\x00' * 20


def _real_png(w: int, h: int) -> bytes:
    """A genuinely decodable PNG of the given size (for the CL-0035 decode path)."""
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (10, 120, 200)).save(buf, format='PNG')
    return buf.getvalue()


def _real_jpeg(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (200, 60, 30)).save(buf, format='JPEG')
    return buf.getvalue()


@pytest.fixture()
def config(tmp_path):
    return {'PHOTOS_DIR': str(tmp_path / 'photos')}


class TestDetectImageExt:
    def test_jpeg(self):
        assert photos.detect_image_ext(JPEG) == 'jpg'

    def test_png(self):
        assert photos.detect_image_ext(PNG) == 'png'

    def test_gif_both_variants(self):
        assert photos.detect_image_ext(GIF87) == 'gif'
        assert photos.detect_image_ext(GIF89) == 'gif'

    def test_webp(self):
        assert photos.detect_image_ext(WEBP) == 'webp'

    def test_text_rejected(self):
        assert photos.detect_image_ext(b'hello world, not an image') is None

    def test_svg_rejected(self):
        assert photos.detect_image_ext(b'<svg xmlns="...">') is None

    def test_riff_but_not_webp_rejected(self):
        # A RIFF container that is a WAV, not WebP.
        assert photos.detect_image_ext(b'RIFF\x00\x00\x00\x00WAVEfmt ') is None

    def test_empty_and_short_input(self):
        assert photos.detect_image_ext(b'') is None
        assert photos.detect_image_ext(b'\xff\xd8') is None  # shorter than any check


class TestSavePhoto:
    def test_writes_file_and_returns_ext(self, config):
        ext = photos.save_photo(config, 7, PNG)
        assert ext == 'png'
        assert os.path.exists(os.path.join(config['PHOTOS_DIR'], '7.png'))

    def test_oversize_rejected(self, config):
        big = JPEG + b'\x00' * (photos.MAX_PHOTO_BYTES + 1)
        with pytest.raises(ValueError):
            photos.save_photo(config, 1, big)

    def test_exactly_max_accepted(self, config):
        # A valid JPEG padded to exactly the cap is accepted (> not >=).
        data = JPEG + b'\x00' * (photos.MAX_PHOTO_BYTES - len(JPEG))
        assert len(data) == photos.MAX_PHOTO_BYTES
        assert photos.save_photo(config, 2, data) == 'jpg'

    def test_non_image_rejected(self, config):
        with pytest.raises(ValueError):
            photos.save_photo(config, 3, b'this is not an image')

    def test_replace_deletes_old_ext(self, config):
        photos.save_photo(config, 5, PNG)
        assert os.path.exists(os.path.join(config['PHOTOS_DIR'], '5.png'))
        # Replace with a JPEG, passing the old ext — the old .png must go.
        photos.save_photo(config, 5, JPEG, old_ext='png')
        assert not os.path.exists(os.path.join(config['PHOTOS_DIR'], '5.png'))
        assert os.path.exists(os.path.join(config['PHOTOS_DIR'], '5.jpg'))


class TestDeletePhoto:
    def test_removes_file(self, config):
        photos.save_photo(config, 9, PNG)
        photos.delete_photo(config, 9, 'png')
        assert not os.path.exists(os.path.join(config['PHOTOS_DIR'], '9.png'))

    def test_missing_file_ignored(self, config):
        os.makedirs(config['PHOTOS_DIR'], exist_ok=True)
        photos.delete_photo(config, 404, 'png')  # no such file — must not raise

    def test_none_ext_noop(self, config):
        photos.delete_photo(config, 1, None)  # must not raise


def _thumb_dims(path):
    with Image.open(path) as im:
        return im.size


class TestGenerateThumbnail:
    def test_downscales_to_256(self):
        thumb = photos.generate_thumbnail(_real_png(512, 512), 'png')
        with Image.open(io.BytesIO(thumb)) as im:
            assert max(im.size) == 256

    def test_preserves_aspect_ratio(self):
        thumb = photos.generate_thumbnail(_real_png(512, 256), 'png')
        with Image.open(io.BytesIO(thumb)) as im:
            assert im.size == (256, 128)  # 2:1 kept, longest edge = 256

    def test_never_upscales(self):
        # A small input comes back at its original dimensions, not enlarged.
        thumb = photos.generate_thumbnail(_real_png(100, 80), 'png')
        with Image.open(io.BytesIO(thumb)) as im:
            assert im.size == (100, 80)

    def test_undecodable_raises_valueerror(self):
        with pytest.raises(ValueError):
            photos.generate_thumbnail(PNG, 'png')  # valid header, garbage body

    def test_exif_orientation_applied(self):
        # A landscape image tagged orientation-6 must come back upright (portrait).
        img = Image.new('RGB', (120, 60), (0, 128, 0))
        exif = img.getexif()
        exif[0x0112] = 6  # rotate 90° CW on display
        buf = io.BytesIO()
        img.save(buf, format='JPEG', exif=exif)
        thumb = photos.generate_thumbnail(buf.getvalue(), 'jpg')
        with Image.open(io.BytesIO(thumb)) as im:
            assert im.height > im.width  # transpose was applied


class TestSavePhotoThumbnail:
    def test_writes_both_original_and_thumb(self, config):
        photos.save_photo(config, 7, _real_png(512, 400))
        orig = os.path.join(config['PHOTOS_DIR'], '7.png')
        thumb = os.path.join(config['PHOTOS_DIR'], '7_thumb.png')
        assert os.path.exists(orig)
        assert os.path.exists(thumb)
        assert max(_thumb_dims(thumb)) == 256

    def test_original_bytes_untouched(self, config):
        data = _real_png(512, 400)
        photos.save_photo(config, 8, data)
        with open(os.path.join(config['PHOTOS_DIR'], '8.png'), 'rb') as fh:
            assert fh.read() == data  # source of truth is byte-for-byte the upload

    def test_undecodable_saves_original_but_no_thumb(self, config):
        # A magic-valid but undecodable blob: original stored, thumbnail skipped.
        assert photos.save_photo(config, 9, PNG) == 'png'
        assert os.path.exists(os.path.join(config['PHOTOS_DIR'], '9.png'))
        assert not os.path.exists(os.path.join(config['PHOTOS_DIR'], '9_thumb.png'))

    def test_replace_ext_removes_old_thumb(self, config):
        photos.save_photo(config, 5, _real_png(400, 400))
        assert os.path.exists(os.path.join(config['PHOTOS_DIR'], '5_thumb.png'))
        photos.save_photo(config, 5, _real_jpeg(400, 400), old_ext='png')
        assert not os.path.exists(os.path.join(config['PHOTOS_DIR'], '5.png'))
        assert not os.path.exists(os.path.join(config['PHOTOS_DIR'], '5_thumb.png'))
        assert os.path.exists(os.path.join(config['PHOTOS_DIR'], '5.jpg'))
        assert os.path.exists(os.path.join(config['PHOTOS_DIR'], '5_thumb.jpg'))


class TestDeletePhotoThumbnail:
    def test_removes_both(self, config):
        photos.save_photo(config, 3, _real_png(300, 300))
        photos.delete_photo(config, 3, 'png')
        assert not os.path.exists(os.path.join(config['PHOTOS_DIR'], '3.png'))
        assert not os.path.exists(os.path.join(config['PHOTOS_DIR'], '3_thumb.png'))

    def test_missing_thumb_ignored(self, config):
        # Only the original exists (pre-CL-0035 photo); delete must not raise.
        os.makedirs(config['PHOTOS_DIR'], exist_ok=True)
        with open(os.path.join(config['PHOTOS_DIR'], '4.png'), 'wb') as fh:
            fh.write(PNG)
        photos.delete_photo(config, 4, 'png')
        assert not os.path.exists(os.path.join(config['PHOTOS_DIR'], '4.png'))


class TestAvatarFilename:
    def test_returns_existing_thumb(self, config):
        photos.save_photo(config, 7, _real_png(512, 512))
        assert photos.avatar_filename(config, 7, 'png') == '7_thumb.png'

    def test_lazily_generates_missing_thumb(self, config):
        # Simulate a pre-CL-0035 photo: original on disk, no thumbnail yet.
        os.makedirs(config['PHOTOS_DIR'], exist_ok=True)
        with open(os.path.join(config['PHOTOS_DIR'], '7.png'), 'wb') as fh:
            fh.write(_real_png(512, 512))
        assert photos.avatar_filename(config, 7, 'png') == '7_thumb.png'
        thumb = os.path.join(config['PHOTOS_DIR'], '7_thumb.png')
        assert os.path.exists(thumb)
        assert max(_thumb_dims(thumb)) == 256

    def test_falls_back_to_original_when_undecodable(self, config):
        os.makedirs(config['PHOTOS_DIR'], exist_ok=True)
        with open(os.path.join(config['PHOTOS_DIR'], '9.png'), 'wb') as fh:
            fh.write(PNG)  # magic-valid, undecodable
        assert photos.avatar_filename(config, 9, 'png') == '9.png'
        assert not os.path.exists(os.path.join(config['PHOTOS_DIR'], '9_thumb.png'))

    def test_falls_back_when_original_missing(self, config):
        os.makedirs(config['PHOTOS_DIR'], exist_ok=True)
        # No files at all: return the original basename (send_from_directory 404s).
        assert photos.avatar_filename(config, 42, 'png') == '42.png'


class TestSavePhotoAtomicReplace:
    """CL-0071: save_photo writes the new file and os.replace()s it into place
    BEFORE any existing file at old_ext is removed.

    Why this exists: the previous order deleted old_ext first, so a write
    failure after the delete (full disk, unwritable dir) destroyed the only
    copy of the photo while the database still named it, 404ing the avatar
    permanently.
    """

    def test_replace_failure_preserves_existing_photo(self, config, monkeypatch):
        original = _real_png(64, 64)
        photos.save_photo(config, 11, original)
        orig_path = os.path.join(config['PHOTOS_DIR'], '11.png')
        assert os.path.exists(orig_path)

        def _boom(*args, **kwargs):
            raise OSError('disk full')

        monkeypatch.setattr(photos.os, 'replace', _boom)
        with pytest.raises(OSError):
            photos.save_photo(config, 11, _real_png(32, 32), old_ext='png')

        # The existing photo must survive untouched, byte-for-byte.
        with open(orig_path, 'rb') as fh:
            assert fh.read() == original
        # And the abandoned temp file must not be left behind.
        leftovers = [f for f in os.listdir(config['PHOTOS_DIR']) if f.endswith('.tmp')]
        assert leftovers == []

    def test_normal_replacement_still_works_across_extension_change(self, config):
        old_data = _real_png(64, 64)
        photos.save_photo(config, 12, old_data)
        new_data = _real_jpeg(64, 64)
        photos.save_photo(config, 12, new_data, old_ext='png')

        assert not os.path.exists(os.path.join(config['PHOTOS_DIR'], '12.png'))
        new_path = os.path.join(config['PHOTOS_DIR'], '12.jpg')
        assert os.path.exists(new_path)
        with open(new_path, 'rb') as fh:
            assert fh.read() == new_data
        leftovers = [f for f in os.listdir(config['PHOTOS_DIR']) if f.endswith('.tmp')]
        assert leftovers == []


class TestWriteThumbnailTempNaming:
    """CL-0071: _write_thumbnail's temp name must be unique per WRITER, not per
    process.

    Why this exists: the old name was f'{final}.{os.getpid()}.tmp' -- unique
    per process, but the server serves on a long-lived background thread, so
    two concurrent regenerations of the same avatar (same contact_id, same
    ext) shared one temp path: one write could truncate the file while the
    other sat between write and os.replace, promoting a half-written image
    that then persisted (the existence check never regenerates it). This locks
    the naming scheme deterministically -- two _write_thumbnail calls for the
    same contact_id/ext must be handed two different tempfile.mkstemp paths --
    rather than a flaky real-threads race test.
    """

    def test_two_writes_for_same_contact_get_different_temp_names(
        self, config, monkeypatch
    ):
        real_mkstemp = tempfile.mkstemp
        names: list[str] = []

        def _recording_mkstemp(*args, **kwargs):
            fd, path = real_mkstemp(*args, **kwargs)
            names.append(path)
            return fd, path

        monkeypatch.setattr(photos.tempfile, 'mkstemp', _recording_mkstemp)

        data = _real_png(64, 64)
        assert photos._write_thumbnail(config, 20, 'png', data) is True
        assert photos._write_thumbnail(config, 20, 'png', data) is True

        assert len(names) == 2
        assert names[0] != names[1]

"""Tests for photos.py — image validation + on-disk photo storage (CL-0026)."""

import os

import pytest

import photos

# Minimal valid magic-byte prefixes padded with filler.
JPEG = b'\xff\xd8\xff' + b'\x00' * 20
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 20
GIF87 = b'GIF87a' + b'\x00' * 20
GIF89 = b'GIF89a' + b'\x00' * 20
WEBP = b'RIFF' + b'\x00\x00\x00\x00' + b'WEBP' + b'\x00' * 20


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

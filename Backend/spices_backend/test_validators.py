"""
Tests for ``spices_backend.validators`` — file upload validators used on
Product/Category image and video fields.

Pure functions with one non-obvious branch: a name with *no* extension means
"already-stored file" (e.g. a Cloudinary public_id) and is intentionally
skipped, so re-validating on every ``full_clean()`` doesn't wrongly reject
unrelated updates. These tests pin both the reject paths and that bypass.
"""
from io import BytesIO

import pytest
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from spices_backend.validators import (
    validate_file_size,
    validate_image_content,
    validate_image_extension,
    validate_video_extension,
)


def _real_png_upload(name='x.png'):
    """A genuinely-decodable PNG wrapped as a fresh upload."""
    from PIL import Image
    buf = BytesIO()
    Image.new('RGB', (2, 2), 'red').save(buf, format='PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


def _file(name='', size=0):
    return SimpleNamespace(name=name, size=size)


# --------------------------------------------------------------------------- #
# validate_file_size
# --------------------------------------------------------------------------- #

class TestValidateFileSize:
    def test_under_limit_ok(self):
        validate_file_size(_file(size=1024))  # no raise

    def test_at_limit_ok(self):
        validate_file_size(_file(size=524288000))  # exactly 500MB

    def test_over_limit_raises(self):
        with pytest.raises(ValidationError):
            validate_file_size(_file(size=524288001))


# --------------------------------------------------------------------------- #
# validate_image_extension
# --------------------------------------------------------------------------- #

class TestValidateImageExtension:
    @pytest.mark.parametrize('name', [
        'turmeric.jpg', 'turmeric.JPG', 'a.jpeg', 'b.png', 'c.webp', 'd.gif',
    ])
    def test_allowed_extensions_ok(self, name):
        validate_image_extension(_file(name=name))

    @pytest.mark.parametrize('name', [
        'evil.exe', 'script.js', 'doc.pdf', 'movie.mp4', 'archive.zip',
    ])
    def test_disallowed_extensions_raise(self, name):
        with pytest.raises(ValidationError):
            validate_image_extension(_file(name=name))

    def test_svg_is_rejected(self):
        """SVG is XML and can carry inline <script> (stored-XSS); no longer allowed."""
        with pytest.raises(ValidationError):
            validate_image_extension(_file(name='logo.svg'))

    def test_extensionless_name_is_skipped(self):
        """A stored Cloudinary public_id has no extension -> nothing to validate."""
        validate_image_extension(_file(name='ngu/products/turmeric_x'))

    def test_empty_name_is_skipped(self):
        validate_image_extension(_file(name=''))

    def test_missing_name_attr_is_skipped(self):
        validate_image_extension(object())


# --------------------------------------------------------------------------- #
# validate_video_extension
# --------------------------------------------------------------------------- #

class TestValidateVideoExtension:
    @pytest.mark.parametrize('name', [
        'clip.mp4', 'clip.MOV', 'a.avi', 'b.mkv', 'c.webm',
    ])
    def test_allowed_extensions_ok(self, name):
        validate_video_extension(_file(name=name))

    @pytest.mark.parametrize('name', ['photo.jpg', 'evil.exe', 'x.gif'])
    def test_disallowed_extensions_raise(self, name):
        with pytest.raises(ValidationError):
            validate_video_extension(_file(name=name))

    def test_extensionless_name_is_skipped(self):
        validate_video_extension(_file(name='ngu/videos/promo_reel'))


# --------------------------------------------------------------------------- #
# validate_image_content  (defence-in-depth: real decode, not just extension)
# --------------------------------------------------------------------------- #

class TestValidateImageContent:
    def test_real_image_upload_passes(self):
        validate_image_content(_real_png_upload())  # no raise

    def test_real_image_rewound_for_save(self):
        """After verification the file pointer is reset so Django can save it."""
        upload = _real_png_upload()
        validate_image_content(upload)
        assert upload.tell() == 0
        assert upload.read()  # content still streamable

    def test_masquerade_html_as_png_rejected(self):
        """The classic 'rename evil.html to evil.png' polyglot must be caught."""
        fake = SimpleUploadedFile(
            'evil.png', b'<html><script>alert(1)</script></html>',
            content_type='image/png')
        with pytest.raises(ValidationError):
            validate_image_content(fake)

    def test_svg_payload_named_png_rejected(self):
        """An SVG-with-script slipped through under a .png name isn't a raster image."""
        svg = SimpleUploadedFile(
            'logo.png', b'<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>',
            content_type='image/png')
        with pytest.raises(ValidationError):
            validate_image_content(svg)

    def test_truncated_image_rejected(self):
        """A corrupt/truncated image (partial header) fails verification."""
        truncated = SimpleUploadedFile('x.png', b'\x89PNG\r\n\x1a\n', content_type='image/png')
        with pytest.raises(ValidationError):
            validate_image_content(truncated)

    def test_empty_upload_rejected(self):
        empty = SimpleUploadedFile('x.png', b'', content_type='image/png')
        with pytest.raises(ValidationError):
            validate_image_content(empty)

    def test_stored_fieldfile_is_skipped(self):
        """An already-stored value (not an UploadedFile) is never re-fetched/decoded."""
        # A plain object stands in for a FieldFile pointing at remote storage;
        # if the validator tried to read it, this would blow up — it must not.
        validate_image_content(SimpleNamespace(name='ngu/products/turmeric_x'))

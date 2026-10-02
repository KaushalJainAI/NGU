from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
import os

def validate_file_size(value):
    """
    Validator to check the file size.
    Maximum size is 500MB (524288000 bytes).
    """
    limit = 524288000  # 500MB
    if value.size > limit:
        raise ValidationError(
            _('File too large. Size should not exceed 500MB.')
        )

def validate_image_extension(value):
    """
    Validator for image extensions.

    Only NEW uploads are checked. An already-stored file may have no extension
    in its name (e.g. a Cloudinary public_id like ``ngu/products/turmeric_x``);
    these validators run again on every ``full_clean()``/save, so re-validating a
    stored, extension-less name would wrongly reject unrelated updates. Uploads
    always carry a filename with an extension, so "no extension" means
    "already persisted" -> nothing to validate.

    Note: ``.svg`` is intentionally NOT allowed. SVG is XML and can carry inline
    ``<script>`` (stored-XSS vector), and it can't be content-verified as a
    raster image the way the formats below can — see ``validate_image_content``.
    """
    ext = os.path.splitext(getattr(value, 'name', '') or '')[1]
    if not ext:
        return
    valid_extensions = ['.jpg', '.jpeg', '.png', '.webp', '.gif']
    if not ext.lower() in valid_extensions:
        raise ValidationError(_('Unsupported file extension. Supported extensions are: ') + ", ".join(valid_extensions))

def validate_image_content(value):
    """
    Defence-in-depth: confirm a freshly-uploaded file really is a decodable
    raster image, not just something with an image extension. Blocks the
    "rename ``evil.html`` to ``evil.png``" polyglot/masquerade trick that the
    extension check alone can't catch.

    Only fresh uploads (``UploadedFile`` instances still in memory / a temp file)
    are inspected. An already-stored value is a ``FieldFile`` pointing at remote
    storage (Cloudinary/S3); reading it here would trigger a needless — possibly
    failing — network fetch on every save, so we skip it, mirroring the
    "already-persisted -> nothing to validate" rule in ``validate_image_extension``.

    If Pillow is somehow unavailable we fail *open* on the content check (the
    extension allow-list still applies) rather than block every legitimate upload.
    """
    from django.core.files.uploadedfile import UploadedFile
    if not isinstance(value, UploadedFile):
        return  # already-stored file — don't refetch from remote storage

    try:
        from PIL import Image
    except ImportError:
        return  # extension allow-list still enforced; don't hard-fail uploads

    try:
        value.seek(0)
        # verify() parses the header/structure and catches truncated or
        # non-image payloads without a full decode. It leaves the image object
        # unusable, which is fine — we only need the pass/fail.
        Image.open(value).verify()
    except ValidationError:
        raise
    except Exception:
        raise ValidationError(_('Uploaded file is not a valid image.'))
    finally:
        # Rewind so Django can still stream the file to storage on save.
        try:
            value.seek(0)
        except Exception:
            pass

def validate_video_extension(value):
    """
    Validator for video extensions. See ``validate_image_extension`` for why an
    extension-less (already-stored) name is treated as nothing-to-validate.
    """
    ext = os.path.splitext(getattr(value, 'name', '') or '')[1]
    if not ext:
        return
    valid_extensions = ['.mp4', '.mov', '.avi', '.mkv', '.webm']
    if not ext.lower() in valid_extensions:
        raise ValidationError(_('Unsupported video extension. Supported extensions are: ') + ", ".join(valid_extensions))

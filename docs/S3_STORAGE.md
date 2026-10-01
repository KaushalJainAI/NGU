# Storage Backend Configuration

The NGU backend supports three storage backends for media files (product/category/profile
images, chat attachments). The active backend is controlled by environment variables.

## Storage Precedence

```
USE_CLOUDINARY=True  →  Cloudinary (production default — hard startup dependency)
USE_S3=True          →  AWS S3 (media + static files; used if Cloudinary is off)
neither              →  local filesystem (development only)
```

Static files (CSS/JS) use S3 when `USE_S3=True`, or the local filesystem otherwise.
When deploying to Render (no S3), add **WhiteNoise** to serve static files from the
backend process itself.

---

## Cloudinary (Production Default)

Cloudinary is the **primary media storage** in production. It provides a fast global
image CDN and automatic image optimization.

### Configuration

```env
USE_CLOUDINARY=True
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret
```

> **Hard dependency:** If any of the three `CLOUDINARY_*` variables are missing, the
> backend container will crash-loop on startup. Always set them before pulling a new
> image.

### Behavior

- All media uploads (`Product.image`, `Category.image`, profile pictures, chat
  attachments, `ProductImage` gallery images) go to Cloudinary under the `ngu/` folder.
- Cloudinary returns absolute `res.cloudinary.com` URLs — `MEDIA_URL` is unused for
  media when Cloudinary is active.
- Static files (CSS/JS) are **not** served through Cloudinary; they use S3 or
  WhiteNoise depending on `USE_S3`.
- Every image upload is validated **before** it reaches any backend (size cap,
  extension allow-list without `.svg`, and a Pillow content-verify on fresh uploads);
  already-stored `FieldFile`s are skipped so re-saves don't refetch remote bytes. See
  `docs/ARCHITECTURE.md` §Security Considerations.

### Migrating existing S3 media to Cloudinary

If you previously stored media on S3, run this one-time migration (idempotent/safe to
re-run):

```bash
# Preview (dry-run, no writes)
python manage.py migrate_s3_to_cloudinary

# Perform the migration
python manage.py migrate_s3_to_cloudinary --apply
```

Covers: Category/Product/ProductImage/ProductCombo images + thumbnails, user profile
pictures, and chat attachments. Requires both `CLOUDINARY_*` and `AWS_*` env vars.

---

## AWS S3 (Static Files / Legacy Media)

S3 is used for **static files** when `USE_S3=True` (and Cloudinary handles media).
It was also the media backend before Cloudinary was introduced — see the migration
command above.

### Configuration

```env
USE_S3=True
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_STORAGE_BUCKET_NAME=ngu-static-files0
AWS_S3_REGION_NAME=ap-south-1
```

### Behavior

- **Static files** (`collectstatic` output) go to the `static/` prefix in the bucket.
- **Media** goes to the `media/` prefix — only used when `USE_CLOUDINARY=False`.
- No AWS ACLs (`AWS_DEFAULT_ACL = None`); permissions set via bucket policy.
- No signed URLs (`AWS_QUERYSTRING_AUTH = False`) — allows CDN proxy caching.
- Public files use `CacheControl: max-age=86400`.

---

## Local Filesystem (Development)

When both `USE_CLOUDINARY=False` and `USE_S3=False` (or neither env var is set),
files are stored locally:

- Media: `Backend/media/`
- Static: `Backend/staticfiles/`

The development server serves these directly. **Never use this in production.**

---

## WhiteNoise (Static Files — Render/No-S3 Deploy)

When deploying to Render (or any host without S3), replace S3 for static files with
**WhiteNoise** so Django serves compressed, cache-busted static files itself:

1. Add `whitenoise==6.9.0` to `requirements.txt`.
2. Insert `whitenoise.middleware.WhiteNoiseMiddleware` after `SecurityMiddleware` in
   `MIDDLEWARE`.
3. Set `USE_S3=False` and add a WhiteNoise `staticfiles` backend when `USE_S3` is off.


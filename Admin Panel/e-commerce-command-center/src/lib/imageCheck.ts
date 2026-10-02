/** Client-side image quality guard for product/category uploads.
 *
 * Non-technical admins often upload tiny WhatsApp thumbnails that look blurry
 * on the storefront. We block truly unusable images and warn on small ones,
 * in plain language.
 *
 * The result carries translation KEYS, not sentences: this module has no React
 * context to call `t` from, and hard-coding English here would leak past the
 * language switch into a toast the admin can't read.
 */
export interface ImageCheckResult {
  ok: boolean;            // false = block the upload
  warningKey?: string;    // set when the image is usable but not great
  errorKey?: string;      // set when ok === false
  /** Interpolation values for whichever key is set. */
  params?: Record<string, string | number>;
}

const MIN_BLOCK_PX = 300;  // below this the image is unusable
const MIN_WARN_PX = 800;   // below this it may look blurry on product pages

export const checkImageFile = (file: File): Promise<ImageCheckResult> =>
  new Promise((resolve) => {
    if (!file.type.startsWith('image/')) {
      resolve({ ok: false, errorKey: 'imageCheck.notAnImage' });
      return;
    }
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const smallest = Math.min(img.width, img.height);
      const params = { width: img.width, height: img.height, min: MIN_WARN_PX };
      if (smallest < MIN_BLOCK_PX) {
        resolve({ ok: false, errorKey: 'imageCheck.tooSmall', params });
      } else if (smallest < MIN_WARN_PX) {
        resolve({ ok: true, warningKey: 'imageCheck.abitSmall', params });
      } else {
        resolve({ ok: true });
      }
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      resolve({ ok: false, errorKey: 'imageCheck.unreadable' });
    };
    img.src = url;
  });

import { useState } from 'react';

interface CachedImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  src: string;
  fallbackSrc?: string;
  lazy?: boolean;        // Enable native lazy loading (loading="lazy")
  /**
   * Kept for API compatibility with older call sites; native lazy loading has no
   * equivalent knob, so it is intentionally ignored.
   */
  rootMargin?: string;
  /**
   * Target display width in CSS px. When set (and the src is a Cloudinary
   * image), the delivered image is capped at ~2x this width so we never ship a
   * 1500px, 2 MB original to fill a 176px tile. Omit for full-resolution
   * contexts (e.g. product detail hero).
   */
  cldWidth?: number;
}

// Ask Cloudinary's f_auto for a modern format (webp/avif) and auto quality.
/**
 * Insert Cloudinary delivery transforms (auto format + auto quality, and an
 * optional width cap) into a res.cloudinary.com /image/upload/ URL. Non-Cloudinary
 * URLs and already-transformed URLs are returned unchanged.
 */
const optimizeCloudinary = (url: string, width?: number): string => {
  if (!url || !url.includes('res.cloudinary.com')) return url;
  const marker = '/image/upload/';
  const i = url.indexOf(marker);
  if (i === -1) return url;
  const after = url.slice(i + marker.length);
  // Already has a transform segment (e.g. "f_auto,..." or "w_400,...")
  if (/^[a-z]{1,3}_[a-z0-9]/i.test(after)) return url;
  const params = ['f_auto', 'q_auto:good'];
  if (width) {
    // c_limit never upscales; request ~2x for crisp rendering on HiDPI screens.
    params.push('c_limit', `w_${Math.round(width * 2)}`);
  }
  return url.slice(0, i + marker.length) + params.join(',') + '/' + after;
};

const getProxiedUrl = (url: string) => {
  if (!url) return url;

  // 1. Handle S3 URLs (any bucket or region)
  if (url.includes('.s3.') || url.includes('.s3-')) {
    // Matches: https://bucket.s3.region.amazonaws.com/path or https://bucket.s3.amazonaws.com/path
    return url.replace(/^https?:\/\/[^/]+\.(s3[\.\-][^/]+)\.amazonaws.com\//, '/s3-media/');
  }

  // 2. Handle absolute URLs to our own backend during local dev (avoiding CORS)
  if (url.includes('127.0.0.1:8000') || url.includes('localhost:8000')) {
    return url.replace(/^https?:\/\/[^/]+\//, '/');
  }

  return url;
};

/**
 * Image with sane defaults: Cloudinary format/quality/width optimization, an
 * S3/dev-host proxy rewrite, a fallback on error, and native lazy loading. The
 * browser's own HTTP cache handles caching — no hand-rolled blob/Cache-API/LRU
 * layer (that duplicated bytes in memory and could revoke a blob URL still shown
 * on screen). A muted pulse fills the box until the image paints.
 */
const CachedImage: React.FC<CachedImageProps> = ({
  src,
  fallbackSrc,
  alt,
  lazy = true,
  rootMargin: _rootMargin,
  cldWidth,
  className,
  onLoad,
  onError,
  ...props
}) => {
  const [loaded, setLoaded] = useState(false);
  const [errored, setErrored] = useState(false);

  const proxiedSrc = optimizeCloudinary(getProxiedUrl(src), cldWidth);
  const proxiedFallback = fallbackSrc ? getProxiedUrl(fallbackSrc) : undefined;
  const displaySrc = errored && proxiedFallback ? proxiedFallback : proxiedSrc;

  // The passed className styles the container <div>, but object-fit / object-position
  // only take effect on the <img> itself. Without this split the inner image keeps
  // CSS's default `object-fit: fill` and stretches to the box (which has a fixed
  // height but viewport-dependent width), so callers passing `object-contain` /
  // `object-cover` see distorted images that vary by device width. Move any
  // `object-*` utility onto the <img>; everything else stays on the container.
  // Default to `object-contain` so images never stretch even if a caller forgets.
  const classTokens = (className || '').split(/\s+/).filter(Boolean);
  const imgObjectClasses = classTokens.filter((c) => /^object-/.test(c));
  const containerClasses = classTokens.filter((c) => !/^object-/.test(c)).join(' ');
  const imgFitClasses = imgObjectClasses.length ? imgObjectClasses.join(' ') : 'object-contain';

  return (
    <div className={`relative overflow-hidden ${containerClasses}`}>
      {!loaded && (
        <div className="absolute inset-0 animate-pulse bg-muted" />
      )}
      <img
        src={displaySrc}
        alt={alt}
        loading={lazy ? 'lazy' : 'eager'}
        decoding="async"
        {...props}
        onLoad={(e) => { setLoaded(true); onLoad?.(e); }}
        onError={(e) => {
          // Swap to the fallback once; if the fallback also fails, stop trying.
          if (!errored && proxiedFallback) setErrored(true);
          setLoaded(true);
          onError?.(e);
        }}
        className={`w-full h-full ${imgFitClasses} transition-opacity duration-300 ${loaded ? 'opacity-100' : 'opacity-0'}`}
      />
    </div>
  );
};

export default CachedImage;

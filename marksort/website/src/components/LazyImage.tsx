import { useEffect, useRef, useState } from 'react';

/**
 * 视口内才加载的图片。分页之后一页只有二十几张，
 * 再叠加这一层，没滚到的卡片一张图都不会请求。
 */
export default function LazyImage({
  src,
  alt,
  className,
  rootMargin = '900px',
}: {
  src: string;
  alt: string;
  className?: string;
  rootMargin?: string;
}) {
  const holder = useRef<HTMLImageElement | null>(null);
  const [wanted, setWanted] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const node = holder.current;
    if (!node || wanted) return;
    if (typeof IntersectionObserver === 'undefined') {
      setWanted(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setWanted(true);
          observer.disconnect();
        }
      },
      { rootMargin },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [wanted, rootMargin]);

  return (
    <img
      ref={holder}
      src={wanted ? src : undefined}
      alt={alt}
      className={`lazy-img${loaded ? ' is-loaded' : ''}${failed ? ' is-failed' : ''}${className ? ' ' + className : ''}`}
      decoding="async"
      onLoad={() => setLoaded(true)}
      onError={() => setFailed(true)}
    />
  );
}

import type { Media } from '../types';
import { imageUrl } from '../services/dataService';

/**
 * 唯一的播放器分发点：只认 media.kind，不认识平台名。
 * 将来加平台，要么复用这里的 kind，要么在这里注册一个新的渲染器。
 */
export default function MediaView({
  media,
  title,
  poster,
  onClose,
}: {
  media: Media;
  title: string;
  poster?: string;
  onClose?: () => void;
}) {
  if (media.kind === 'iframe') {
    const query = new URLSearchParams(
      Object.entries(media.params ?? {}).map(([key, value]) => [key, String(value)]),
    );
    const src = `${media.url}?${query.toString()}`;
    return (
      <div className="media-frame">
        <iframe
          src={src}
          title={title}
          scrolling="no"
          allow="autoplay; fullscreen; encrypted-media; picture-in-picture"
          sandbox="allow-scripts allow-same-origin allow-presentation allow-popups allow-popups-to-escape-sandbox"
        />
        {onClose && <CloseButton onClose={onClose} />}
      </div>
    );
  }

  if (media.kind === 'video') {
    return (
      <div className="media-frame">
        <video src={media.url} controls playsInline poster={poster} />
        {onClose && <CloseButton onClose={onClose} />}
      </div>
    );
  }

  if (media.kind === 'image') {
    return (
      <img
        className="media-image"
        src={imageUrl(media.url || poster)}
        alt={title}
        loading="lazy"
      />
    );
  }

  return (
    <>
      {poster && (
        <img
          src={imageUrl(poster)}
          alt={title}
          loading="lazy"
          onError={(event) => {
            (event.target as HTMLImageElement).style.display = 'none';
          }}
        />
      )}
    </>
  );
}

function CloseButton({ onClose }: { onClose: () => void }) {
  return (
    <button className="media-close" onClick={onClose} title="关闭播放" type="button">
      ✕
    </button>
  );
}

import { useState } from 'react';
import { formatDuration, imageUrl } from '../services/dataService';
import { itemFolder, type Item } from '../types';
import LazyImage from './LazyImage';
import MediaView from './MediaView';
import './NoteCard.css';

const PLATFORM_LABEL: Record<string, string> = {
  bilibili: 'B 站',
  rednote: '小红书',
  xiaohongshu: '小红书',
  demo: '演示',
};

export default function NoteCard({ item }: { item: Item }) {
  const [playing, setPlaying] = useState(false);
  const folder = itemFolder(item);
  const duration = formatDuration(item.media.duration);
  const playable = item.media.kind === 'iframe' || item.media.kind === 'video';
  const stats = [
    ['播放', item.stats.play_text || item.stats.play],
    ['收藏', item.stats.collect],
    ['点赞', item.stats.liked],
  ].filter(([, value]) => value && value !== '0') as [string, string][];

  return (
    <article className="note-card">
      <div className="note-cover" onClick={() => playable && setPlaying(true)}>
        {playing ? (
          <MediaView media={item.media} title={item.title} onClose={() => setPlaying(false)} />
        ) : (
          <>
            {item.cover ? (
              <LazyImage src={imageUrl(item.cover, 'cover')} alt={item.title} />
            ) : (
              <div className="cover-placeholder" />
            )}
            {playable && <span className="play-badge">▶</span>}
            {duration && <span className="duration-badge">{duration}</span>}
          </>
        )}
      </div>

      <div className="note-body">
        <div className="note-title-row">
          <h3 title={item.title}>{item.title}</h3>
          <span className={`platform-badge platform-${item.platform}`}>
            {PLATFORM_LABEL[item.platform] ?? item.platform}
          </span>
        </div>

        <div className="note-author">
          {item.author.avatar ? (
            <LazyImage
              src={imageUrl(String(item.author.avatar), 'avatar')}
              alt=""
              className="author-avatar"
              rootMargin="1400px"
            />
          ) : (
            <span className="avatar-dot" />
          )}
          <span>{item.author.name || '未知作者'}</span>
        </div>

        {item.description && <p className="note-desc">{item.description}</p>}

        <div className="note-meta">
          {folder && <span className="folder-chip">{folder}</span>}
          {item.collected_at && <span className="collected-at">{item.collected_at.slice(0, 10)}</span>}
          {stats.map(([label, value]) => (
            <span key={label} className="stat">
              {label} {value}
            </span>
          ))}
        </div>

        {item.url && (
          <a className="note-link" href={item.url} target="_blank" rel="noopener noreferrer">
            查看原文 →
          </a>
        )}
      </div>
    </article>
  );
}

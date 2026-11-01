import { useEffect, useMemo, useRef, useState } from 'react';
import {
  applyFilters,
  folderFacets,
  loadItems,
  platformFacets,
} from '../services/dataService';
import FilterBar from '../components/FilterBar';
import NoteCard from '../components/NoteCard';
import { itemKey, type Item } from '../types';

const BATCH = 24;

export default function FeedView() {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [platform, setPlatform] = useState<string | null>(null);
  const [folder, setFolder] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  const [shown, setShown] = useState(BATCH);
  const sentinel = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    loadItems()
      .then((loaded) => {
        setItems(loaded);
        setError(null);
      })
      .catch((reason: unknown) => setError(String(reason)))
      .finally(() => setLoading(false));
  }, []);

  const platforms = useMemo(() => platformFacets(items), [items]);
  const folders = useMemo(() => folderFacets(items), [items]);
  const filtered = useMemo(
    () => applyFilters(items, { platform, folder, query }),
    [items, platform, folder, query],
  );

  useEffect(() => {
    setShown(BATCH);
  }, [platform, folder, query]);

  useEffect(() => {
    const node = sentinel.current;
    if (!node || shown >= filtered.length) return;
    if (typeof IntersectionObserver === 'undefined') {
      setShown(filtered.length);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setShown((current) => (current >= filtered.length ? current : current + BATCH));
        }
      },
      { rootMargin: '800px 0px' },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [shown, filtered.length]);

  const visible = useMemo(() => filtered.slice(0, shown), [filtered, shown]);

  if (loading) {
    return (
      <div className="loading-container">
        <div className="loading-spinner" />
        <p>加载中…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-container">
        <p>{error}</p>
        <p className="error-hint">
          先跑 <code>python -m marksort serve</code>，再在设置页抓取一次，页面才有数据。
        </p>
      </div>
    );
  }

  return (
    <>
      <FilterBar
        platforms={platforms}
        folders={folders}
        platform={platform}
        folder={folder}
        query={query}
        total={items.length}
        onPlatform={setPlatform}
        onFolder={setFolder}
        onQuery={setQuery}
      />

      <main className="app-main">
        <div className="notes-container">
          {visible.length === 0 ? (
            <div className="empty-state">这个筛选下没有内容</div>
          ) : (
            <>
              <div className="notes-grid">
                {visible.map((item) => (
                  <NoteCard key={itemKey(item)} item={item} />
                ))}
              </div>
              <div className="feed-status" ref={sentinel}>
                {shown < filtered.length ? (
                  <>
                    <div className="feed-spinner" />
                    <span>
                      下滑继续加载（{visible.length} / {filtered.length}）
                    </span>
                  </>
                ) : (
                  <span>已经到底了 · 共 {filtered.length} 条</span>
                )}
              </div>
            </>
          )}
        </div>
      </main>
    </>
  );
}

import { useEffect, useState } from 'react';
import FeedView from './views/FeedView';
import SettingsView from './views/SettingsView';
import SyncView from './views/SyncView';
import { loadItems, totalHours } from './services/dataService';
import type { Item } from './types';
import './App.css';

type View = 'feed' | 'settings' | 'sync';

const TABS: { id: View; label: string }[] = [
  { id: 'feed', label: '内容' },
  { id: 'settings', label: '设置' },
  { id: 'sync', label: '图片同步' },
];

function readHash(): View {
  const raw = window.location.hash.replace(/^#\/?/, '');
  return (TABS.find((tab) => tab.id === raw)?.id ?? 'feed') as View;
}

export default function App() {
  const [view, setView] = useState<View>(readHash);
  const [items, setItems] = useState<Item[]>([]);

  useEffect(() => {
    const onHash = () => setView(readHash());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  useEffect(() => {
    loadItems()
      .then(setItems)
      .catch(() => setItems([]));
  }, []);

  const go = (next: View) => {
    window.location.hash = `#/${next}`;
    setView(next);
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="header-content">
          <h1 className="app-title">
            <span className="title-icon">MS</span>
            MarkSort
          </h1>
          <nav className="app-nav">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className={view === tab.id ? 'active' : ''}
                onClick={() => go(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </nav>
          <p className="app-subtitle">
            {items.length > 0
              ? `共 ${items.length} 条 · 合计 ${totalHours(items)} 小时`
              : '还没有数据，先去「设置」抓取一次'}
          </p>
        </div>
      </header>

      {view === 'feed' && <FeedView />}
      {view === 'settings' && <SettingsView />}
      {view === 'sync' && <SyncView />}
    </div>
  );
}

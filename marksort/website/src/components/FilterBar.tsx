import type { Facet } from '../services/dataService';
import './FilterBar.css';

interface FilterBarProps {
  platforms: Facet[];
  folders: Facet[];
  platform: string | null;
  folder: string | null;
  query: string;
  total: number;
  onPlatform: (value: string | null) => void;
  onFolder: (value: string | null) => void;
  onQuery: (value: string) => void;
}

export default function FilterBar({
  platforms,
  folders,
  platform,
  folder,
  query,
  total,
  onPlatform,
  onFolder,
  onQuery,
}: FilterBarProps) {
  return (
    <div className="filter-bar">
      <div className="filter-row">
        <button
          className={`chip ${platform === null ? 'active' : ''}`}
          onClick={() => onPlatform(null)}
          type="button"
        >
          全部平台
          <span className="chip-count">{total}</span>
        </button>
        {platforms.map((facet) => (
          <button
            key={facet.id}
            className={`chip ${platform === facet.id ? 'active' : ''}`}
            onClick={() => onPlatform(facet.id)}
            type="button"
          >
            {facet.name}
            <span className="chip-count">{facet.count}</span>
          </button>
        ))}

        <input
          className="filter-search"
          placeholder="搜索标题 / 简介 / 作者"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
        />
      </div>

      {folders.length > 1 && (
        <div className="filter-row folder-row">
          <button
            className={`chip small ${folder === null ? 'active' : ''}`}
            onClick={() => onFolder(null)}
            type="button"
          >
            全部收藏夹
          </button>
          {folders.map((facet) => (
            <button
              key={facet.id}
              className={`chip small ${folder === facet.id ? 'active' : ''}`}
              onClick={() => onFolder(facet.id)}
              type="button"
            >
              {facet.name}
              <span className="chip-count">{facet.count}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

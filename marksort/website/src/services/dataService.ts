import { itemFolder, type Item } from '../types';

/**
 * 图床都有防盗链（B 站校验 Referer），浏览器从 localhost 直连会被 403。
 * 统一走本地代理：服务端补 Referer 并落磁盘缓存。
 *
 * size 决定取多大：卡片要缩略图（B 站图床支持尾缀缩放，334KB → 16KB），
 * 只有真正播放/看大图时才取原图。
 */
export type ImageSize = 'cover' | 'avatar' | 'full';

const HDSLB = /^https?:\/\/[^/]*hdslb\.com\//i;

const SIZE_SUFFIX: Record<Exclude<ImageSize, 'full'>, string> = {
  cover: '@480w_360h_1c.webp',
  avatar: '@72w_72h_1c.webp',
};

export function imageUrl(raw: string | undefined | null, size: ImageSize = 'full'): string {
  if (!raw) return '';
  if (raw.startsWith('/')) return raw;
  if (!/^https?:\/\//i.test(raw)) return raw;
  let target = raw;
  if (size !== 'full' && HDSLB.test(raw) && !raw.includes('@')) {
    target = raw + SIZE_SUFFIX[size];
  }
  return `/api/image?u=${encodeURIComponent(target)}`;
}

/** 数据只有一个来源：本地 marksort 服务读 data/unified.json 后吐出来。 */
export async function loadItems(): Promise<Item[]> {
  const response = await fetch('/api/items');
  if (!response.ok) {
    throw new Error(`读取 /api/items 失败：HTTP ${response.status}`);
  }
  const data = await response.json();
  return Array.isArray(data) ? (data as Item[]) : [];
}

export interface Facet {
  id: string;
  name: string;
  count: number;
}

function tally(values: string[]): Facet[] {
  const map = new Map<string, number>();
  values.forEach((value) => map.set(value, (map.get(value) ?? 0) + 1));
  return Array.from(map.entries())
    .sort((a, b) => b[1] - a[1])
    .map(([name, count]) => ({ id: name, name, count }));
}

export function platformFacets(items: Item[]): Facet[] {
  return tally(items.map((item) => item.platform));
}

/** 收藏夹来自抓取时的原始字段，不是我们造的标签体系。 */
export function folderFacets(items: Item[]): Facet[] {
  return tally(items.map((item) => itemFolder(item) ?? '未归类'));
}

export interface Filters {
  platform?: string | null;
  folder?: string | null;
  query?: string;
}

export function applyFilters(items: Item[], filters: Filters): Item[] {
  const query = (filters.query ?? '').trim().toLowerCase();
  return items.filter((item) => {
    if (filters.platform && item.platform !== filters.platform) return false;
    if (filters.folder) {
      const folder = itemFolder(item) ?? '未归类';
      if (folder !== filters.folder) return false;
    }
    if (query) {
      const haystack = `${item.title} ${item.description} ${item.author.name ?? ''}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    return true;
  });
}

export function formatDuration(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return '';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  const pad = (n: number) => String(n).padStart(2, '0');
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${minutes}:${pad(secs)}`;
}

export function totalHours(items: Item[]): number {
  const total = items.reduce((sum, item) => sum + (item.media.duration ?? 0), 0);
  return Math.round((total / 3600) * 10) / 10;
}

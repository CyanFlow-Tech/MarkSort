// 与后端 marksort/core/item.py 一一对应的前端类型。
// 平台差异只体现在 media.kind 上，渲染层不认识「平台」这个概念。

export type Platform = string;

export type MediaKind = 'iframe' | 'video' | 'image' | 'none';

export interface Media {
  kind: MediaKind;
  url: string;
  params: Record<string, unknown>;
  duration: number | null;
}

export interface Item {
  schema_version: number;
  platform: Platform;
  external_id: string;
  title: string;
  description: string;
  url: string;
  cover: string;
  author: { name?: string; avatar?: string; id?: string } & Record<string, unknown>;
  tags: string[];
  category: string | null;
  summary: string | null;
  stats: Record<string, string>;
  media: Media;
  collected_at: string | null;
  raw: Record<string, unknown>;
}

export function itemKey(item: Item): string {
  return `${item.platform}:${item.external_id}`;
}

/** 后端 raw 里带的收藏夹信息（目前只有 B 站插件写）。 */
export function itemFolder(item: Item): string | null {
  const folder = (item.raw as Record<string, unknown> | undefined)?.folder as
    | { title?: string }
    | undefined;
  return folder?.title ?? null;
}

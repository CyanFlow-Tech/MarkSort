// 在已登录的 bilibili 页面上下文里抓收藏夹，推给本地 ingest 端口。
// 用法（浏览器控制台或 browser_evaluate）：
//   await marksortIngestBilibili({ folders: [{id: 320435219, title: '默认收藏夹'}] })
// 不读 Cookie：请求由页面自己发出，登录态留在浏览器。

const MARKSORT_INGEST = 'http://127.0.0.1:17330/ingest';

async function marksortIngestBilibili(options) {
  const opts = options || {};
  const port = opts.port || 17330;
  const endpoint = opts.endpoint || ('http://127.0.0.1:' + port + '/ingest');
  const pageSize = opts.pageSize || 20;
  const maxPages = opts.maxPages || 100;
  const folders = opts.folders || [];
  const results = [];

  for (const folder of folders) {
    const collected = [];
    let page = 1;
    let hasMore = true;
    while (hasMore && page <= maxPages) {
      const url =
        'https://api.bilibili.com/x/v3/fav/resource/list?media_id=' + folder.id +
        '&pn=' + page + '&ps=' + pageSize +
        '&keyword=&order=mtime&type=0&tid=0&platform=web&web_location=333.1387';
      const response = await fetch(url, { credentials: 'include' });
      const payload = await response.json();
      if (payload.code !== 0) {
        results.push({ folder: folder.title, error: payload.message || String(payload.code), sent: collected.length });
        break;
      }
      const medias = (payload.data && payload.data.medias) || [];
      for (const media of medias) {
        collected.push({
          bvid: media.bvid,
          avid: media.id,
          title: media.title,
          intro: media.intro || '',
          cover: (media.cover || '').replace(/^http:/, 'https:'),
          duration: media.duration,
          fav_time: media.fav_time,
          pubtime: media.pubtime,
          ctime: media.ctime,
          btype: media.btype,
          attr: media.attr,
          upper: media.upper ? { mid: media.upper.mid, name: media.upper.name, face: media.upper.face } : null,
          cnt_info: media.cnt_info || {},
          link: media.link,
        });
      }
      hasMore = !!(payload.data && payload.data.has_more);
      page += 1;
      if (!medias.length) break;
    }
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: JSON.stringify({
        platform: 'bilibili',
        key: 'bvid',
        folder: { id: folder.id, title: folder.title },
        items: collected,
      }),
    });
    const ack = await response.json().catch(() => ({}));
    results.push({ folder: folder.title, sent: collected.length, ack });
  }
  return { ok: true, results };
}

// 拉收藏夹清单（用于设置页展示可选项）
async function marksortListBilibiliFolders(mid) {
  const url =
    'https://api.bilibili.com/x/v3/fav/folder/created/list-all?up_mid=' + mid + '&web_location=333.1387';
  const payload = await (await fetch(url, { credentials: 'include' })).json();
  const list = (payload.data && payload.data.list) || [];
  return list.map((f) => ({ id: f.id, title: f.title, media_count: f.media_count, attr: f.attr }));
}

import { useCallback, useEffect, useRef, useState } from 'react';

type SyncStatus = {
  running: boolean;
  total: number;
  done: number;
  failed: number;
  percent: number;
  rate: number;
  eta_s: number;
  elapsed_s: number;
  last: string | null;
  errors: string[];
  finished_at: number | null;
};

export default function SyncView() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [delayMs, setDelayMs] = useState(300);
  const [workers, setWorkers] = useState(3);
  const [covers, setCovers] = useState(true);
  const [avatars, setAvatars] = useState(true);
  const [message, setMessage] = useState('');
  const timer = useRef<number | null>(null);

  const poll = useCallback(async () => {
    try {
      const response = await fetch('/api/sync/status');
      const data: SyncStatus = await response.json();
      setStatus(data);
      if (!data.running && timer.current) {
        window.clearInterval(timer.current);
        timer.current = null;
      }
    } catch (reason) {
      setMessage(`读取状态失败：${reason}`);
    }
  }, []);

  const startPolling = useCallback(() => {
    if (timer.current) return;
    timer.current = window.setInterval(poll, 800);
  }, [poll]);

  useEffect(() => {
    poll();
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [poll]);

  const start = async () => {
    const kinds: string[] = [];
    if (covers) kinds.push('cover');
    if (avatars) kinds.push('avatar');
    setMessage('正在排队…');
    const response = await fetch('/api/sync/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ delay_ms: delayMs, workers, kinds }),
    });
    const result = await response.json();
    if (!result.ok) {
      setMessage(`启动失败：${result.error ?? JSON.stringify(result)}`);
      return;
    }
    setMessage('');
    startPolling();
    poll();
  };

  const stop = async () => {
    await fetch('/api/sync/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    poll();
  };

  const percent = status?.percent ?? 0;
  const running = Boolean(status?.running);

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>图片同步</h2>
        <span className="muted">
          把封面与头像一次性拉到 <code>data/cache/images/</code>；展示端仍然只加载视口里的图
        </span>
      </div>

      <div className="sync-form">
        <label>
          <span>每张间隔（毫秒）</span>
          <input
            type="number"
            min={0}
            max={5000}
            step={50}
            value={delayMs}
            onChange={(event) => setDelayMs(Number(event.target.value))}
          />
        </label>
        <label>
          <span>并发数</span>
          <input
            type="number"
            min={1}
            max={8}
            value={workers}
            onChange={(event) => setWorkers(Number(event.target.value))}
          />
        </label>
        <label className="inline">
          <input type="checkbox" checked={covers} onChange={(e) => setCovers(e.target.checked)} />
          封面
        </label>
        <label className="inline">
          <input type="checkbox" checked={avatars} onChange={(e) => setAvatars(e.target.checked)} />
          头像
        </label>
      </div>

      <div className="sync-actions">
        <button type="button" onClick={start} disabled={running}>
          开始同步
        </button>
        <button type="button" className="ghost" onClick={stop} disabled={!running}>
          停止
        </button>
        <span className="muted">{message || (running ? '同步中…' : '待开始')}</span>
      </div>

      <div className="sync-bar">
        <i style={{ width: `${percent}%` }} />
      </div>

      <div className="sync-stats">
        <span>进度 <b>{percent}%</b></span>
        <span>完成 <b>{status?.done ?? 0}</b> / <b>{status?.total ?? 0}</b></span>
        <span>失败 <b>{status?.failed ?? 0}</b></span>
        <span>速度 <b>{status?.rate ?? 0}</b> 张/秒</span>
        <span>已用 <b>{status?.elapsed_s ?? 0}</b> 秒</span>
        <span>剩余 <b>{running && status?.eta_s ? `${status.eta_s} 秒` : '—'}</b></span>
      </div>

      {status?.last && <p className="muted small">最近：{status.last}</p>}
      {status?.errors && status.errors.length > 0 && (
        <pre className="settings-log error-text">{status.errors.join('\n')}</pre>
      )}
    </div>
  );
}

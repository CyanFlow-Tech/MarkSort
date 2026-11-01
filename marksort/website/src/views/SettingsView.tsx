import { useEffect, useState } from 'react';

type FieldSpec = {
  type?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  items?: FieldSpec;
  properties?: Record<string, FieldSpec>;
  'x-secret'?: boolean;
};

type PluginInfo = {
  name: string;
  kind: string;
  version: string;
  description: string;
  enabled: boolean;
  missing_services: string[];
  schema: { properties?: Record<string, FieldSpec>; required?: string[] };
};

type SettingsPayload = {
  paths: { default: string; local: string };
  local: Record<string, unknown>;
  failures: Record<string, string[]>;
  plugins: PluginInfo[];
};

const KIND_PLURAL: Record<string, string> = {
  source: 'sources',
  enricher: 'enrichers',
  sink: 'sinks',
};

type Drafts = Record<string, Record<string, Record<string, unknown>>>;

export default function SettingsView() {
  const [data, setData] = useState<SettingsPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState('还没跑过');
  const [reveal, setReveal] = useState<Record<string, boolean>>({});

  const load = () =>
    fetch('/api/settings')
      .then((response) => response.json())
      .then((payload: SettingsPayload) => {
        setData(payload);
        setDrafts({});
        setError(null);
      })
      .catch((reason: unknown) => setError(String(reason)));

  useEffect(() => {
    load();
  }, []);

  const valueOf = (plugin: PluginInfo, field: string): unknown => {
    const localSection = (data?.local?.[KIND_PLURAL[plugin.kind]] ?? {}) as Record<
      string,
      Record<string, unknown>
    >;
    const own = localSection[plugin.name] ?? {};
    if (field in own) return own[field];
    const spec = plugin.schema.properties?.[field];
    return spec?.default;
  };

  const isEnabled = (plugin: PluginInfo): boolean => {
    const localSection = (data?.local?.[KIND_PLURAL[plugin.kind]] ?? {}) as Record<
      string,
      Record<string, unknown>
    >;
    const own = localSection[plugin.name] ?? {};
    if ('enabled' in own) return Boolean(own.enabled);
    return true;
  };

  const put = (plugin: PluginInfo, field: string, value: unknown) => {
    const plural = KIND_PLURAL[plugin.kind];
    setDrafts((current) => ({
      ...current,
      [plural]: {
        ...(current[plural] ?? {}),
        [plugin.name]: { ...((current[plural] ?? {})[plugin.name] ?? {}), [field]: value },
      },
    }));
  };

  const save = async () => {
    setBusy(true);
    setStatus('保存中…');
    // 启用开关一并落盘，否则「填了凭据但没启用」会让抓取静默跳过
    const patch: Drafts = { ...drafts };
    (data?.plugins ?? []).forEach((plugin) => {
      const plural = KIND_PLURAL[plugin.kind];
      patch[plural] = patch[plural] ?? {};
      patch[plural][plugin.name] = patch[plural][plugin.name] ?? {};
      const current = drafts[plural]?.[plugin.name] ?? {};
      if (!('enabled' in current)) {
        patch[plural][plugin.name].enabled = isEnabled(plugin);
      }
    });
    const response = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ patch }),
    });
    const result = await response.json();
    setStatus(result.ok ? `已保存到 ${result.saved}` : `保存失败：${result.error}`);
    setBusy(false);
    if (result.ok) await load();
  };

  const runFetch = async () => {
    setBusy(true);
    setStatus('抓取中…');
    setLog('正在调用来源插件…');
    try {
      const response = await fetch('/api/fetch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      const result = await response.json();
      if (!result.ok) {
        setStatus('抓取失败');
        setLog(result.error ?? JSON.stringify(result));
      } else {
        setStatus(`抓到 ${result.items} 条，用时 ${result.elapsed_ms}ms`);
        setLog(JSON.stringify(result, null, 2));
      }
    } catch (reason) {
      setStatus('请求失败');
      setLog(String(reason));
    } finally {
      setBusy(false);
    }
  };

  if (error) return <div className="panel error-container">{error}</div>;
  if (!data) return <div className="panel">读取设置…</div>;

  const failures = Object.entries(data.failures ?? {});

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>设置</h2>
        <span className="muted">
          模板 settings.default.json 入库；真实值写 {data.paths.local}（已 gitignore）
        </span>
      </div>

      {failures.length > 0 && (
        <pre className="settings-log error-text">
          {failures.map(([name, list]) => `${name}：${list.join('；')}`).join('\n')}
        </pre>
      )}

      {data.plugins.map((plugin) => {
        const enabled = Boolean(
          drafts[KIND_PLURAL[plugin.kind]]?.[plugin.name]?.enabled ?? isEnabled(plugin),
        );
        const fields = Object.entries(plugin.schema.properties ?? {}).filter(
          ([name]) => name !== 'enabled',
        );
        return (
          <section className="plugin-card" key={`${plugin.kind}.${plugin.name}`}>
            <header>
              <strong>{plugin.name}</strong>
              <span className="badge">{plugin.kind}</span>
              <span className={`badge ${plugin.missing_services.length ? 'warn' : 'ok'}`}>
                {plugin.missing_services.length
                  ? `缺服务：${plugin.missing_services.join(',')}`
                  : 'ok'}
              </span>
              <label className="switch">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(event) => {
                    const plural = KIND_PLURAL[plugin.kind];
                    setDrafts((current) => ({
                      ...current,
                      [plural]: {
                        ...(current[plural] ?? {}),
                        [plugin.name]: {
                          ...((current[plural] ?? {})[plugin.name] ?? {}),
                          enabled: event.target.checked,
                        },
                      },
                    }));
                  }}
                />
                启用
              </label>
            </header>
            {plugin.description && <p className="muted small">{plugin.description}</p>}

            <div className={enabled ? '' : 'plugin-disabled'}>
              {fields.map(([field, spec]) => {
                const value = drafts[KIND_PLURAL[plugin.kind]]?.[plugin.name]?.[field] ?? valueOf(plugin, field);
                const key = `${plugin.kind}.${plugin.name}.${field}`;
                return (
                  <label className="field-row" key={key}>
                    <span className="field-label">
                      {field}
                      {spec.description && <em>{spec.description}</em>}
                    </span>
                    <span className="field-input">
                      {spec.enum ? (
                        <select
                          value={String(value ?? spec.enum[0])}
                          onChange={(event) => put(plugin, field, event.target.value)}
                        >
                          {spec.enum.map((option) => (
                            <option key={String(option)} value={String(option)}>
                              {String(option)}
                            </option>
                          ))}
                        </select>
                      ) : spec.type === 'boolean' ? (
                        <input
                          type="checkbox"
                          checked={Boolean(value)}
                          onChange={(event) => put(plugin, field, event.target.checked)}
                        />
                      ) : spec.type === 'array' ? (
                        <input
                          type="text"
                          placeholder="逗号分隔，可留空"
                          value={Array.isArray(value) ? value.join(', ') : ''}
                          onChange={(event) =>
                            put(
                              plugin,
                              field,
                              event.target.value
                                .split(',')
                                .map((part) => part.trim())
                                .filter(Boolean),
                            )
                          }
                        />
                      ) : (
                        <input
                          type={spec['x-secret'] && !reveal[key] ? 'password' : 'text'}
                          inputMode={spec.type === 'integer' ? 'numeric' : undefined}
                          value={value === undefined || value === null ? '' : String(value)}
                          onChange={(event) =>
                            put(
                              plugin,
                              field,
                              spec.type === 'integer'
                                ? Number(event.target.value || 0)
                                : event.target.value,
                            )
                          }
                        />
                      )}
                      {spec['x-secret'] && (
                        <button
                          type="button"
                          className="link-button"
                          onClick={() =>
                            setReveal((current) => ({ ...current, [key]: !current[key] }))
                          }
                        >
                          {reveal[key] ? '隐藏' : '显示'}
                        </button>
                      )}
                    </span>
                  </label>
                );
              })}
            </div>
          </section>
        );
      })}

      <div className="panel-actions">
        <button type="button" onClick={save} disabled={busy}>
          保存到本地设置
        </button>
        <button type="button" className="ghost" onClick={runFetch} disabled={busy}>
          抓取到 data/unified.json
        </button>
        <span className={status.startsWith('保存失败') || status === '抓取失败' ? 'error-text' : 'muted'}>
          {status}
        </span>
      </div>

      <pre className="settings-log">{log}</pre>
    </div>
  );
}

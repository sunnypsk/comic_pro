import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Badge, ErrorBox, Spinner, Toggle } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { queryKeys, useHealth, useSettings, useSources } from "../lib/queries";
import type { AppSettings } from "../lib/types";

interface ProbeResult {
  url: string;
  base_url: string;
  id: string;
  site_name: string;
  engine: string;
  confidence: number;
  markers: string[];
  yaml: string;
}

export default function Settings() {
  const settings = useSettings();
  const sources = useSources();
  const health = useHealth();
  const queryClient = useQueryClient();

  const [cacheGb, setCacheGb] = useState("5");
  const [intervalMin, setIntervalMin] = useState("360");
  const [notice, setNotice] = useState("");

  const [editorFor, setEditorFor] = useState<string | null>(null);
  const [editorYaml, setEditorYaml] = useState("");
  const [editorError, setEditorError] = useState("");

  const [probeUrl, setProbeUrl] = useState("");
  const [probeResult, setProbeResult] = useState<ProbeResult | null>(null);
  const [probeYaml, setProbeYaml] = useState("");

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");

  useEffect(() => {
    if (settings.data) {
      setCacheGb(String(settings.data.cache_max_gb));
      setIntervalMin(String(settings.data.check_interval_min));
    }
  }, [settings.data]);

  const saveRuntime = useMutation({
    mutationFn: (body: Record<string, number>) =>
      api<AppSettings & { ok: boolean }>("/api/settings", { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: () => {
      setNotice("运行设置已保存");
      queryClient.invalidateQueries({ queryKey: queryKeys.settings });
    },
    onError: (error) => setNotice(error instanceof ApiError ? error.message : "保存失败"),
  });

  const toggleSource = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api(`/api/sources/${id}`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.sources }),
  });

  const reloadSources = useMutation({
    mutationFn: () => api<{ sources: number; errors: Record<string, string> }>("/api/sources/reload", { method: "POST" }),
    onSuccess: (result) => {
      const errorCount = Object.keys(result.errors).length;
      setNotice(`已重载 ${result.sources} 个源${errorCount ? `，${errorCount} 个配置有错误` : ""}`);
      queryClient.invalidateQueries({ queryKey: queryKeys.sources });
    },
  });

  const saveConfig = useMutation({
    mutationFn: ({ id, yaml }: { id: string; yaml: string }) =>
      api<{ ok: boolean; errors: Record<string, string> }>(`/api/sources/${id}/config`, {
        method: "PUT",
        body: JSON.stringify({ yaml }),
      }),
    onSuccess: (result) => {
      const errors = Object.values(result.errors);
      setEditorError(errors.length ? errors.join("; ") : "");
      setNotice(errors.length ? "配置已写入，但加载失败" : "源配置已保存并重载");
      queryClient.invalidateQueries({ queryKey: queryKeys.sources });
    },
    onError: (error) => setEditorError(error instanceof ApiError ? error.message : "保存失败"),
  });

  const deleteConfig = useMutation({
    mutationFn: (id: string) => api(`/api/sources/${id}/config`, { method: "DELETE" }),
    onSuccess: () => {
      setEditorFor(null);
      setNotice("已删除用户配置");
      queryClient.invalidateQueries({ queryKey: queryKeys.sources });
    },
  });

  const probe = useMutation({
    mutationFn: (url: string) =>
      api<ProbeResult>("/api/sources/probe", { method: "POST", body: JSON.stringify({ url }) }),
    onSuccess: (result) => {
      setProbeResult(result);
      setProbeYaml(result.yaml);
    },
  });

  const saveProbe = useMutation({
    mutationFn: () =>
      api(`/api/sources/${probeResult?.id}/config`, {
        method: "PUT",
        body: JSON.stringify({ yaml: probeYaml }),
      }),
    onSuccess: () => {
      setNotice("新源已保存并启用");
      queryClient.invalidateQueries({ queryKey: queryKeys.sources });
    },
    onError: (error) => setNotice(error instanceof ApiError ? error.message : "保存失败"),
  });

  const changePassword = useMutation({
    mutationFn: () =>
      api("/api/auth/password", {
        method: "POST",
        body: JSON.stringify({ current: currentPassword, new: newPassword }),
      }),
    onSuccess: () => {
      setNotice("访问密码已更新");
      setCurrentPassword("");
      setNewPassword("");
      queryClient.invalidateQueries({ queryKey: queryKeys.auth });
    },
    onError: (error) => setNotice(error instanceof ApiError ? error.message : "修改失败"),
  });

  async function openEditor(id: string) {
    setEditorFor(id);
    setEditorYaml("");
    setEditorError("");
    try {
      const data = await api<{ yaml: string }>(`/api/sources/${id}/config`);
      setEditorYaml(data.yaml);
    } catch (error) {
      setEditorError(error instanceof ApiError ? error.message : "无法读取源配置");
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">设置</h1>
        <p className="mt-1 text-sm text-slate-400">漫画源、下载、缓存与访问控制。</p>
      </header>

      {notice && <p className="rounded-xl bg-accent-500/10 px-4 py-2 text-sm text-accent-300">{notice}</p>}

      {health.data && (
        <div className="card flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-4 text-sm text-slate-300">
          <span className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-emerald-400" /> 服务正常
          </span>
          <span>版本 {health.data.version}</span>
          <span>磁盘剩余 {health.data.disk.free_gb} GB</span>
          <span>源 {health.data.sources.enabled}/{health.data.sources.total} 启用</span>
          <span>本地章节 {health.data.counts.library_chapters}</span>
        </div>
      )}

      <section className="card space-y-4 p-5">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-base font-semibold">漫画源</h2>
            <p className="mt-0.5 text-xs text-slate-400">
              内置 Madara / MangaStream / 通用 YAML 引擎，也可粘贴站点地址自动生成配置。
            </p>
          </div>
          <button type="button" className="btn-ghost text-xs" onClick={() => reloadSources.mutate()}>
            重载配置
          </button>
        </div>

        {sources.isLoading && <Spinner />}
        {sources.error && <ErrorBox message="源列表加载失败" />}

        <ul className="divide-y divide-white/5">
          {(sources.data?.sources ?? []).map((source) => (
            <li key={source.id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="truncate text-sm font-medium text-slate-100">{source.name}</p>
                  <Badge tone="muted">{source.engine}</Badge>
                  {source.nsfw && <Badge tone="danger">NSFW</Badge>}
                  {source.last_error && <Badge tone="danger">有错误</Badge>}
                </div>
                <p className="mt-0.5 truncate text-xs text-slate-500">
                  {source.id} · {source.base_url || "内置"}
                </p>
                {source.last_error && <p className="mt-0.5 text-[11px] text-rose-300">{source.last_error}</p>}
              </div>
              <div className="flex items-center gap-2">
                {source.has_config && (
                  <button type="button" className="btn-ghost px-2.5 py-1 text-xs" onClick={() => openEditor(source.id)}>
                    编辑 YAML
                  </button>
                )}
                <Toggle
                  checked={source.enabled}
                  label={`启用 ${source.name}`}
                  onChange={(enabled) => toggleSource.mutate({ id: source.id, enabled })}
                />
              </div>
            </li>
          ))}
        </ul>

        {editorFor && (
          <div className="space-y-2 rounded-xl border border-white/10 bg-ink-950/60 p-4">
            <div className="flex items-center justify-between">
              <p className="text-sm font-medium">编辑 {editorFor}.yaml</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="btn-ghost text-xs"
                  onClick={() => deleteConfig.mutate(editorFor)}
                >
                  删除配置
                </button>
                <button type="button" className="btn-ghost text-xs" onClick={() => setEditorFor(null)}>
                  关闭
                </button>
              </div>
            </div>
            <textarea
              className="input min-h-[260px] font-mono text-xs leading-relaxed"
              spellCheck={false}
              value={editorYaml}
              onChange={(event) => setEditorYaml(event.target.value)}
              placeholder="id: my-source&#10;name: My Source&#10;engine: madara&#10;base_url: https://example.org"
            />
            {editorError && <p className="text-xs text-rose-300">{editorError}</p>}
            <button
              type="button"
              className="btn-primary text-xs"
              disabled={saveConfig.isPending || !editorYaml.trim()}
              onClick={() => saveConfig.mutate({ id: editorFor, yaml: editorYaml })}
            >
              保存并重载
            </button>
          </div>
        )}
      </section>

      <section className="card space-y-4 p-5">
        <div>
          <h2 className="text-base font-semibold">添加源（按站点自动识别）</h2>
          <p className="mt-0.5 text-xs text-slate-400">
            填入站点首页地址，自动识别 Madara / MangaStream 等常见引擎并生成 YAML 草稿。
          </p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            className="input flex-1"
            value={probeUrl}
            onChange={(event) => setProbeUrl(event.target.value)}
            placeholder="https://manga.example.org"
          />
          <button
            type="button"
            className="btn-primary"
            disabled={probe.isPending || !probeUrl.trim()}
            onClick={() => probe.mutate(probeUrl.trim())}
          >
            {probe.isPending ? "识别中…" : "识别"}
          </button>
        </div>

        {probe.error && (
          <p className="text-xs text-rose-300">
            {probe.error instanceof ApiError ? probe.error.message : "识别失败"}
          </p>
        )}

        {probeResult && (
          <div className="space-y-2 rounded-xl border border-white/10 bg-ink-950/60 p-4">
            <p className="text-xs text-slate-400">
              识别为 <span className="text-accent-400">{probeResult.engine}</span> ·{" "}
              {Math.round(probeResult.confidence * 100)}% 置信度 · {probeResult.site_name}
            </p>
            <textarea
              className="input min-h-[240px] font-mono text-xs leading-relaxed"
              spellCheck={false}
              value={probeYaml}
              onChange={(event) => setProbeYaml(event.target.value)}
            />
            <button
              type="button"
              className="btn-primary text-xs"
              disabled={saveProbe.isPending}
              onClick={() => saveProbe.mutate()}
            >
              保存并启用
            </button>
          </div>
        )}
      </section>

      <section className="card space-y-4 p-5">
        <h2 className="text-base font-semibold">运行设置</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1.5">
            <span className="label">图片缓存上限（GB）</span>
            <input
              className="input"
              type="number"
              min={0}
              step={0.5}
              value={cacheGb}
              onChange={(event) => setCacheGb(event.target.value)}
            />
          </label>
          <label className="space-y-1.5">
            <span className="label">追更检查间隔（分钟，0 关闭）</span>
            <input
              className="input"
              type="number"
              min={0}
              value={intervalMin}
              onChange={(event) => setIntervalMin(event.target.value)}
            />
          </label>
        </div>
        <p className="text-xs text-slate-500">
          下载并发 {settings.data?.env.download_concurrency ?? "—"} 章 · 每章页并发{" "}
          {settings.data?.env.page_concurrency ?? "—"} · 数据目录 {settings.data?.env.data_dir}
        </p>
        <button
          type="button"
          className="btn-primary text-xs"
          disabled={saveRuntime.isPending}
          onClick={() =>
            saveRuntime.mutate({
              cache_max_gb: Number(cacheGb),
              check_interval_min: Number(intervalMin),
            })
          }
        >
          保存运行设置
        </button>
      </section>

      <section className="card space-y-4 p-5">
        <h2 className="text-base font-semibold">访问密码</h2>
        <p className="text-xs text-slate-400">
          {settings.data?.env.auth_password_set
            ? "当前由 AUTH_PASSWORD 环境变量管理，请在 compose 中修改。"
            : "设置后所有 API 与页面都需要登录；POST 使用 X-Api-Token 可放行自动化调用。"}
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1.5">
            <span className="label">当前密码（未设置可留空）</span>
            <input
              className="input"
              type="password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              autoComplete="current-password"
            />
          </label>
          <label className="space-y-1.5">
            <span className="label">新密码（至少 4 位）</span>
            <input
              className="input"
              type="password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              autoComplete="new-password"
            />
          </label>
        </div>
        <button
          type="button"
          className="btn-primary text-xs"
          disabled={changePassword.isPending || newPassword.length < 4 || settings.data?.env.auth_password_set}
          onClick={() => changePassword.mutate()}
        >
          更新密码
        </button>
      </section>

      <section className="card space-y-2 p-5 text-xs text-slate-500">
        <h2 className="text-base font-semibold text-slate-100">关于</h2>
        <p>ComicPro {health.data?.version ?? ""} · 单容器 · SQLite + CBZ</p>
        <p>反向代理子路径部署请设置 COMICPRO_BASE_PATH，例如 /comic。</p>
        <p>镜像支持 linux/amd64 与 linux/arm64，数据全部保存在 /data。</p>
      </section>
    </div>
  );
}

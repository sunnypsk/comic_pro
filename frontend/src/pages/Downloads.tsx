import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Badge, ErrorBox, ProgressBar, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { queryKeys, useDownloads } from "../lib/queries";
import type { DownloadJob, DownloadStats } from "../lib/types";

const STATUS_LABEL: Record<DownloadJob["status"], string> = {
  queued: "排队中",
  running: "下载中",
  done: "完成",
  partial: "部分完成",
  error: "失败",
  canceled: "已取消",
};

const STATUS_TONE: Record<DownloadJob["status"], "success" | "warning" | "danger" | "muted" | "default"> = {
  queued: "muted",
  running: "default",
  done: "success",
  partial: "warning",
  error: "danger",
  canceled: "muted",
};

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="card px-4 py-3">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1 text-xl font-bold ${tone ?? "text-slate-100"}`}>{value}</p>
    </div>
  );
}

export default function Downloads() {
  const downloads = useDownloads();
  const queryClient = useQueryClient();

  const cancel = useMutation({
    mutationFn: (id: number) => api(`/api/downloads/${id}/cancel`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.downloads }),
  });

  const retry = useMutation({
    mutationFn: (id: number) => api(`/api/downloads/${id}/retry`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.downloads }),
  });

  const stats: DownloadStats | undefined = downloads.data?.stats;
  const jobs = downloads.data?.jobs ?? [];

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">下载队列</h1>
        <p className="mt-1 text-sm text-slate-400">
          队列持久化在 SQLite 中，容器重启后自动续传；产物写入 /data/library。
        </p>
      </header>

      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="进行中" value={stats.running} tone="text-accent-400" />
          <Stat label="排队" value={stats.queued} />
          <Stat label="完成" value={stats.done} tone="text-emerald-400" />
          <Stat label="部分" value={stats.partial} tone="text-amber-400" />
          <Stat label="失败" value={stats.error} tone="text-rose-400" />
          <Stat label="取消" value={stats.canceled} />
        </div>
      )}

      {downloads.isLoading && <Spinner />}
      {downloads.error && <ErrorBox message="队列加载失败" onRetry={() => downloads.refetch()} />}

      {!downloads.isLoading && jobs.length === 0 && (
        <div className="card p-10 text-center text-sm text-slate-400">
          还没有下载任务。去{" "}
          <Link to="/search" className="text-accent-400 hover:text-accent-300">
            在线搜索
          </Link>{" "}
          选几章试试。
        </div>
      )}

      <div className="space-y-3">
        {jobs.map((job) => (
          <div key={job.id} className="card p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-100">
                  {job.manga?.title ?? "未知作品"}
                </p>
                <p className="mt-0.5 truncate text-xs text-slate-400">
                  {job.chapter?.title ?? `chapter #${job.chapter?.id ?? "?"}`}
                  {job.manga?.source_id ? ` · ${job.manga.source_id}` : ""}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={STATUS_TONE[job.status]}>{STATUS_LABEL[job.status]}</Badge>
                <span className="text-xs text-slate-500">
                  {job.pages_done}/{job.pages_total} 页
                </span>
                {(job.status === "running" || job.status === "queued") && (
                  <button
                    type="button"
                    className="btn-ghost px-2.5 py-1 text-xs"
                    onClick={() => cancel.mutate(job.id)}
                    disabled={cancel.isPending}
                  >
                    取消
                  </button>
                )}
                {(job.status === "error" || job.status === "canceled" || job.status === "partial") && (
                  <button
                    type="button"
                    className="btn-ghost px-2.5 py-1 text-xs"
                    onClick={() => retry.mutate(job.id)}
                    disabled={retry.isPending}
                  >
                    重试
                  </button>
                )}
              </div>
            </div>

            <ProgressBar
              value={job.pages_total ? job.pages_done / job.pages_total : 0}
              className="mt-3"
            />
            {job.error && <p className="mt-2 line-clamp-2 text-xs text-rose-300">{job.error}</p>}
            {job.target_path && job.status === "done" && (
              <p className="mt-1 truncate text-[11px] text-slate-500">library/{job.target_path}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

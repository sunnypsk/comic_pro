import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ComicCard } from "../components/ComicCard";
import { EmptyState, ErrorBox, Spinner } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { queryKeys, useLibrary } from "../lib/queries";

export default function Library() {
  const [query, setQuery] = useState("");
  const library = useLibrary(query);
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState("");

  const scan = useMutation({
    mutationFn: () => api<{ items: number; inserted: number; removed: number }>("/api/library/scan", { method: "POST" }),
    onSuccess: (result) => {
      setNotice(`扫描完成：${result.items} 个章节文件`);
      queryClient.invalidateQueries({ queryKey: queryKeys.library("") });
      queryClient.invalidateQueries({ queryKey: ["library"] });
    },
    onError: (error) => setNotice(error instanceof ApiError ? error.message : "扫描失败"),
  });

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold">本地书架</h1>
          <p className="mt-1 text-sm text-slate-400">
            直接读取 /data/library 下的 CBZ 文件，可被 Komga / Kavita 等工具同时识别。
          </p>
        </div>
        <button type="button" className="btn-ghost self-start" onClick={() => scan.mutate()} disabled={scan.isPending}>
          {scan.isPending ? "扫描中…" : "重新扫描"}
        </button>
      </header>

      <input
        className="input max-w-md"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="筛选书架标题"
        aria-label="筛选书架"
      />
      {notice && <p className="text-sm text-accent-400">{notice}</p>}

      {library.isLoading && <Spinner />}
      {library.error && <ErrorBox message="书架加载失败" onRetry={() => library.refetch()} />}

      {library.data && library.data.series.length === 0 && (
        <EmptyState
          title="书架还是空的"
          hint="在在线搜索里下载章节，完成后会自动出现在这里。"
          action={
            <Link to="/search?q=star" className="btn-primary mt-2">
              去搜索
            </Link>
          }
        />
      )}

      {library.data && library.data.series.length > 0 && (
        <>
          <p className="text-xs text-slate-500">共 {library.data.total} 部作品</p>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {library.data.series.map((series) => (
              <ComicCard
                key={series.id}
                to={`/library/${series.id}`}
                title={series.title}
                subtitle={`${series.chapter_count} 章 · ${(series.size_bytes / 1024 / 1024).toFixed(1)} MB`}
                cover={series.cover}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

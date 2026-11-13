import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Cover } from "../components/Cover";
import { Badge, ErrorBox, ProgressBar, Spinner } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { queryKeys, useManga } from "../lib/queries";

export default function Manga() {
  const { source, key } = useParams();
  const manga = useManga(source, key);
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [notice, setNotice] = useState("");
  const lastIndex = useRef<number | null>(null);

  const enqueue = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<{ count: number }>("/api/downloads", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: (result) => {
      setNotice(`已加入队列：${result.count} 个章节`);
      setSelected(new Set());
      queryClient.invalidateQueries({ queryKey: queryKeys.downloads });
    },
    onError: (error) => setNotice(error instanceof ApiError ? error.message : "加入队列失败"),
  });

  const follow = useMutation({
    mutationFn: (next: { follow?: boolean; auto_download?: boolean }) =>
      api(`/api/sources/${source}/manga/${key}/follow`, {
        method: "POST",
        body: JSON.stringify(next),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.manga(source ?? "", key ?? "") }),
    onError: (error) => setNotice(error instanceof ApiError ? error.message : "操作失败"),
  });

  if (manga.isLoading) return <Spinner label="正在获取章节目录…" />;
  if (manga.error) return <ErrorBox message="漫画详情加载失败" onRetry={() => manga.refetch()} />;
  if (!manga.data) return null;

  const data = manga.data;
  const chapters = data.chapters;
  const allSelected = chapters.length > 0 && selected.size === chapters.length;

  function toggle(index: number, checked: boolean, shift: boolean) {
    const next = new Set(selected);
    if (shift && lastIndex.current !== null) {
      const start = Math.min(lastIndex.current, index);
      const end = Math.max(lastIndex.current, index);
      for (let i = start; i <= end; i += 1) {
        if (checked) next.add(chapters[i].id);
        else next.delete(chapters[i].id);
      }
    } else if (checked) {
      next.add(chapters[index].id);
    } else {
      next.delete(chapters[index].id);
    }
    setSelected(next);
    lastIndex.current = index;
  }

  function toggleAll(checked: boolean) {
    setSelected(checked ? new Set(chapters.map((chapter) => chapter.id)) : new Set());
  }

  return (
    <div className="space-y-8">
      <Link to="/search" className="text-sm text-slate-400 hover:text-accent-400">
        ← 返回搜索
      </Link>

      <header className="card flex flex-col gap-6 p-5 sm:flex-row">
        <div className="w-36 shrink-0 self-start overflow-hidden rounded-xl border border-white/10">
          <Cover src={data.cover} alt={data.title} className="aspect-[2/3] w-full" />
        </div>
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold leading-tight">{data.title}</h1>
            {data.status && <Badge tone="muted">{data.status}</Badge>}
          </div>
          <p className="text-sm text-slate-400">
            {data.author || "未知作者"} · {data.source_name} · {chapters.length} 章
          </p>
          {data.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {data.tags.map((tag) => (
                <span key={tag} className="chip">
                  {tag}
                </span>
              ))}
            </div>
          )}
          {data.description && (
            <p className="max-h-24 overflow-y-auto whitespace-pre-line text-sm leading-relaxed text-slate-300">
              {data.description}
            </p>
          )}

          <div className="flex flex-wrap gap-2 pt-1">
            <button
              type="button"
              className="btn-primary"
              disabled={enqueue.isPending}
              onClick={() => enqueue.mutate({ manga_id: data.id, all: true })}
            >
              下载全部
            </button>
            <button
              type="button"
              className="btn-ghost"
              disabled={enqueue.isPending || selected.size === 0}
              onClick={() => enqueue.mutate({ chapter_ids: Array.from(selected) })}
            >
              下载所选 {selected.size > 0 ? `(${selected.size})` : ""}
            </button>
            <button
              type="button"
              className="btn-ghost"
              disabled={follow.isPending}
              onClick={() => follow.mutate({ follow: !data.follow })}
            >
              {data.follow ? "取消关注" : "关注追更"}
            </button>
            {data.follow && (
              <button
                type="button"
                className="btn-ghost"
                disabled={follow.isPending}
                onClick={() => follow.mutate({ auto_download: !data.auto_download })}
              >
                {data.auto_download ? "自动下载：开" : "自动下载：关"}
              </button>
            )}
          </div>

          {notice && <p className="text-sm text-accent-400">{notice}</p>}
        </div>
      </header>

      <section className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/5 px-4 py-3">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              className="h-4 w-4 accent-[#4d8bff]"
              checked={allSelected}
              onChange={(event) => toggleAll(event.target.checked)}
            />
            章节列表
          </label>
          <span className="text-xs text-slate-500">Shift + 点击可连续选择</span>
        </div>

        <ul className="divide-y divide-white/5">
          {chapters.map((chapter, index) => (
            <li key={chapter.id} className="flex items-center gap-3 px-4 py-2.5 hover:bg-white/[0.03]">
              <input
                type="checkbox"
                className="h-4 w-4 shrink-0 accent-[#4d8bff]"
                checked={selected.has(chapter.id)}
                onChange={(event) =>
                  toggle(index, event.target.checked, (event.nativeEvent as MouseEvent).shiftKey)
                }
                aria-label={`选择 ${chapter.title}`}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-slate-200">{chapter.title}</p>
                <p className="mt-0.5 flex items-center gap-2 text-[11px] text-slate-500">
                  {chapter.number !== null && <span>第 {chapter.number} 话</span>}
                  {chapter.downloaded && <span className="text-emerald-400">已下载 · {chapter.page_count} 页</span>}
                </p>
              </div>
              <Link
                to={`/reader/online/${data.id}/${chapter.id}`}
                className="btn-ghost shrink-0 px-3 py-1.5 text-xs"
              >
                阅读
              </Link>
            </li>
          ))}
          {chapters.length === 0 && <li className="px-4 py-10 text-center text-sm text-slate-500">该源没有返回章节</li>}
        </ul>
      </section>

      {enqueue.isPending && <ProgressBar value={0.35} className="opacity-60" />}
    </div>
  );
}

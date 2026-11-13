import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Cover } from "../components/Cover";
import { Badge, ErrorBox, Spinner } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { queryKeys, useLibraryDetail } from "../lib/queries";

export default function LibraryDetail() {
  const { id } = useParams();
  const detail = useLibraryDetail(id);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const remove = useMutation({
    mutationFn: () => api(`/api/library/${id}?confirm=true`, { method: "DELETE" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.library("") });
      queryClient.invalidateQueries({ queryKey: queryKeys.home });
      navigate("/library", { replace: true });
    },
  });

  if (detail.isLoading) return <Spinner />;
  if (detail.error) return <ErrorBox message="加载失败" onRetry={() => detail.refetch()} />;
  if (!detail.data) return null;
  const data = detail.data;

  function confirmDelete() {
    if (window.confirm(`确定删除《${data.title}》的全部 ${data.chapters.length} 个章节文件？此操作不可恢复。`)) {
      remove.mutate();
    }
  }

  return (
    <div className="space-y-8">
      <Link to="/library" className="text-sm text-slate-400 hover:text-accent-400">
        ← 返回书架
      </Link>

      <header className="card flex flex-col gap-6 p-5 sm:flex-row">
        <div className="w-36 shrink-0 overflow-hidden rounded-xl border border-white/10">
          <Cover src={data.cover} alt={data.title} className="aspect-[2/3] w-full" />
        </div>
        <div className="min-w-0 flex-1 space-y-3">
          <h1 className="text-2xl font-bold">{data.title}</h1>
          <p className="text-sm text-slate-400">{data.chapters.length} 个章节</p>
          <div className="flex flex-wrap gap-2">
            <Link to={`/reader/library/${data.id}/0`} className="btn-primary">
              开始阅读
            </Link>
            <button type="button" className="btn-danger" onClick={confirmDelete} disabled={remove.isPending}>
              删除整部
            </button>
          </div>
          {remove.error && (
            <p className="text-sm text-rose-300">
              {remove.error instanceof ApiError ? remove.error.message : "删除失败"}
            </p>
          )}
        </div>
      </header>

      <section className="card overflow-hidden">
        <div className="border-b border-white/5 px-4 py-3 text-sm text-slate-300">章节</div>
        <ul className="divide-y divide-white/5">
          {data.chapters.map((chapter) => (
            <li key={chapter.index} className="flex items-center gap-3 px-4 py-3 hover:bg-white/[0.03]">
              <span className="w-10 shrink-0 text-xs text-slate-500">
                #{String(chapter.index + 1).padStart(2, "0")}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-slate-200">{chapter.title}</p>
                <p className="mt-0.5 text-[11px] text-slate-500">
                  {chapter.page_count} 页 · {(chapter.size_bytes / 1024 / 1024).toFixed(1)} MB
                </p>
              </div>
              {chapter.page_count > 0 ? (
                <Badge tone="success">可读</Badge>
              ) : (
                <Badge tone="warning">无图片</Badge>
              )}
              <Link
                to={`/reader/library/${data.id}/${chapter.index}`}
                className="btn-ghost shrink-0 px-3 py-1.5 text-xs"
              >
                阅读
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

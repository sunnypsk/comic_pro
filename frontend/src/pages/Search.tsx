import { FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ComicCard } from "../components/ComicCard";
import { Badge, EmptyState, ErrorBox, Spinner } from "../components/ui";
import { useSearch, useSources } from "../lib/queries";

export default function Search() {
  const [params, setSearchParams] = useSearchParams();
  const query = (params.get("q") ?? "").trim();
  const [draft, setDraft] = useState(query);
  const search = useSearch(query);
  const sources = useSources();

  useEffect(() => setDraft(query), [query]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const value = draft.trim();
    setSearchParams(value ? { q: value } : {});
  }

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold">在线搜索</h1>
        <p className="mt-1 text-sm text-slate-400">
          一次请求并发到全部启用的漫画源，单源超时不会影响其它结果。
        </p>
      </header>

      <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
        <input
          className="input flex-1"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="输入标题、作者或关键词"
          aria-label="搜索关键词"
        />
        <button type="submit" className="btn-primary sm:w-28">
          搜索
        </button>
      </form>

      {!query && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            {(sources.data?.sources ?? [])
              .filter((source) => source.enabled)
              .map((source) => (
                <span key={source.id} className="chip">
                  {source.name}
                  <span className="text-slate-500">· {source.engine}</span>
                </span>
              ))}
          </div>
          <EmptyState
            title="输入关键词开始搜索"
            hint="在设置页可以启用/停用源、粘贴站点地址自动生成配置。"
          />
        </div>
      )}

      {query && search.isLoading && <Spinner label={`正在搜索 “${query}”…`} />}
      {query && search.error && <ErrorBox message="搜索请求失败" onRetry={() => search.refetch()} />}

      {search.data && (
        <div className="space-y-8">
          {search.data.sources.map((outcome) => (
            <section key={outcome.id}>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <h2 className="text-base font-semibold text-slate-100">{outcome.source_name}</h2>
                {outcome.nsfw && <Badge tone="danger">NSFW</Badge>}
                {outcome.status === "ok" && (
                  <Badge tone="success">{outcome.items.length} 个结果</Badge>
                )}
                {outcome.status === "timeout" && <Badge tone="warning">超时</Badge>}
                {outcome.status === "error" && <Badge tone="danger">失败</Badge>}
                <span className="text-xs text-slate-500">{outcome.elapsed_ms} ms</span>
                {outcome.error && <span className="text-xs text-rose-300">{outcome.error}</span>}
              </div>

              {outcome.items.length > 0 ? (
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5">
                  {outcome.items.map((item) => (
                    <ComicCard
                      key={item.key}
                      to={`/manga/${item.source_id}/${item.key}`}
                      title={item.title}
                      subtitle={item.tags.slice(0, 3).join(" · ")}
                      cover={item.cover}
                    />
                  ))}
                </div>
              ) : (
                <p className="text-sm text-slate-500">没有匹配结果</p>
              )}
            </section>
          ))}

          {search.data.sources.length === 0 && (
            <EmptyState
              title="没有启用的漫画源"
              hint="到设置页启用内置 Demo 源，或添加你自己的站点配置。"
            />
          )}
        </div>
      )}
    </div>
  );
}

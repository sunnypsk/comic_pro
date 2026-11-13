import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ComicCard } from "../components/ComicCard";
import { EmptyState, ErrorBox, SectionHeader, Spinner } from "../components/ui";
import { useHome } from "../lib/queries";

export default function Home() {
  const { data, isLoading, error, refetch } = useHome();
  const [query, setQuery] = useState("");
  const navigate = useNavigate();

  function submit(event: FormEvent) {
    event.preventDefault();
    const value = query.trim();
    if (value) navigate(`/search?q=${encodeURIComponent(value)}`);
  }

  const queue = data?.queue;
  const active = (queue?.queued ?? 0) + (queue?.running ?? 0);

  return (
    <div className="space-y-10">
      <section className="overflow-hidden rounded-3xl border border-white/5 bg-gradient-to-br from-accent-500/20 via-ink-900 to-ink-950 p-6 shadow-2xl shadow-black/40 sm:p-10">
        <p className="text-xs font-semibold uppercase tracking-[0.25em] text-accent-400">Self-hosted · NAS ready</p>
        <h1 className="mt-3 max-w-2xl text-3xl font-black leading-tight text-white sm:text-4xl">
          把在线漫画，收进你的私有书架
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-300">
          配置任意漫画源，一次搜索全部来源；在线阅读走签名图片代理，喜欢就下载为 CBZ 存进 NAS，断网也能看。
        </p>

        <form onSubmit={submit} className="mt-6 flex max-w-2xl flex-col gap-2 sm:flex-row">
          <input
            className="input flex-1"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索漫画标题，例如 star / garden"
            aria-label="搜索漫画"
          />
          <button type="submit" className="btn-primary sm:w-28">
            搜索
          </button>
        </form>

        <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-slate-400">
          <span>试试：</span>
          {["star", "garden", "detective"].map((word) => (
            <Link key={word} to={`/search?q=${word}`} className="chip hover:border-accent-500/40 hover:text-accent-400">
              {word}
            </Link>
          ))}
        </div>
      </section>

      {error && <ErrorBox message="首页数据加载失败" onRetry={() => refetch()} />}
      {isLoading && <Spinner />}

      {data && data.continue.length > 0 && (
        <section>
          <SectionHeader title="继续阅读" subtitle="上次看到的位置" />
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {data.continue.map((entry) => (
              <ComicCard
                key={`${entry.kind}-${entry.href}`}
                to={entry.href}
                title={entry.title}
                subtitle={entry.subtitle}
                cover={entry.cover}
                progress={entry.page_total ? entry.page / entry.page_total : 0}
              />
            ))}
          </div>
        </section>
      )}

      {data && data.continue.length === 0 && data.recent.length === 0 && (
        <EmptyState
          title="书架还是空的"
          hint="先在「在线搜索」里找一本漫画，下载后会出现在这里。内置 Demo 源可以离线体验完整流程。"
          action={
            <Link to="/search?q=star" className="btn-primary mt-2">
              搜索示例漫画
            </Link>
          }
        />
      )}

      {data && data.recent.length > 0 && (
        <section>
          <SectionHeader
            title="最近入库"
            subtitle="下载完成并扫描到的本地漫画"
            action={
              <Link to="/library" className="text-sm text-accent-400 hover:text-accent-300">
                全部书架 →
              </Link>
            }
          />
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {data.recent.map((entry) => (
              <ComicCard key={entry.id} to={entry.href} title={entry.title} cover={entry.cover} />
            ))}
          </div>
        </section>
      )}

      <section className="grid gap-4 sm:grid-cols-2">
        <div className="card flex items-center justify-between p-5">
          <div>
            <p className="text-sm font-semibold text-slate-200">下载队列</p>
            <p className="mt-1 text-xs text-slate-400">
              {active > 0 ? `${active} 个任务进行中` : "队列空闲"}
              {queue && queue.error > 0 ? ` · ${queue.error} 个失败` : ""}
            </p>
          </div>
          <Link to="/downloads" className="btn-ghost">
            查看
          </Link>
        </div>
        <div className="card flex items-center justify-between p-5">
          <div>
            <p className="text-sm font-semibold text-slate-200">想加更多来源？</p>
            <p className="mt-1 text-xs text-slate-400">粘贴站点地址自动识别引擎，生成 YAML 源配置</p>
          </div>
          <Link to="/settings" className="btn-ghost">
            加源
          </Link>
        </div>
      </section>
    </div>
  );
}

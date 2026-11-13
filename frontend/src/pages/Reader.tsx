import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { IconArrowLeft, IconArrowRight, IconClose } from "../components/icons";
import { ErrorBox, Spinner } from "../components/ui";
import { api, assetUrl } from "../lib/api";
import { useManifest } from "../lib/queries";

type Mode = "paged" | "webtoon";
type Fit = "width" | "height";

function readMode(): Mode {
  return localStorage.getItem("comicpro.reader.mode") === "webtoon" ? "webtoon" : "paged";
}

function readFit(): Fit {
  return localStorage.getItem("comicpro.reader.fit") === "width" ? "width" : "height";
}

export default function Reader() {
  const { kind, id, chapter } = useParams();
  const navigate = useNavigate();
  const isOnline = kind === "online";
  const path = isOnline
    ? `/api/read/online?manga_id=${id}&chapter_id=${chapter}`
    : `/api/read/library?series=${encodeURIComponent(id ?? "")}&chapter=${chapter}`;

  const manifest = useManifest(path);
  const data = manifest.data;
  const total = data?.total ?? 0;

  const [page, setPage] = useState(1);
  const [mode, setMode] = useState<Mode>(readMode);
  const [fit, setFit] = useState<Fit>(readFit);
  const scroller = useRef<HTMLDivElement | null>(null);

  useEffect(() => localStorage.setItem("comicpro.reader.mode", mode), [mode]);
  useEffect(() => localStorage.setItem("comicpro.reader.fit", fit), [fit]);

  useEffect(() => {
    if (!data) return;
    const target = Math.min(Math.max(data.progress || 1, 1), Math.max(data.total, 1));
    setPage(target);
    scroller.current?.scrollTo({ top: 0 });
  }, [data?.item_ref, data?.chapter_ref]);

  const rtl = data?.direction === "rtl";
  const goNext = useCallback(() => setPage((current) => Math.min(total, current + 1)), [total]);
  const goPrev = useCallback(() => setPage((current) => Math.max(1, current - 1)), [total]);

  const goChapter = useCallback(
    (target: { id: number } | null | undefined) => {
      if (!target) return;
      navigate(`/reader/${kind}/${id}/${target.id}`);
    },
    [kind, id, navigate],
  );

  useEffect(() => {
    if (!data) return;
    const saved = setTimeout(() => {
      void api("/api/progress", {
        method: "POST",
        body: JSON.stringify({
          kind: data.kind,
          item_ref: data.item_ref,
          chapter_ref: data.chapter_ref,
          page,
          page_total: data.total,
        }),
      }).catch(() => undefined);
    }, 700);
    return () => clearTimeout(saved);
  }, [page, data]);

  useEffect(() => {
    if (!data) return;
    [page + 1, page + 2].forEach((number) => {
      const entry = data.pages[number - 1];
      if (entry) {
        const image = new Image();
        image.src = assetUrl(entry.url);
      }
    });
  }, [data, page]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      switch (event.key) {
        case "ArrowRight":
          rtl ? goPrev() : goNext();
          break;
        case "ArrowLeft":
          rtl ? goNext() : goPrev();
          break;
        case " ":
          event.preventDefault();
          goNext();
          break;
        case "Escape":
          navigate(-1);
          break;
        case "f":
        case "F":
          if (document.fullscreenElement) void document.exitFullscreen();
          else void document.documentElement.requestFullscreen();
          break;
        default:
          break;
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goNext, goPrev, navigate, rtl]);

  if (manifest.isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-black">
        <Spinner label="正在加载章节…" />
      </div>
    );
  }

  if (manifest.error) {
    return (
      <div className="flex h-screen items-center justify-center bg-black px-6">
        <ErrorBox message="章节加载失败（源站可能不可用或该章节已下架）" onRetry={() => manifest.refetch()} />
      </div>
    );
  }

  if (!data) return null;

  if (total === 0) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-black text-slate-300">
        <p>该章节没有可用页面</p>
        <button type="button" className="btn-ghost" onClick={() => navigate(-1)}>
          返回
        </button>
      </div>
    );
  }

  const current = data.pages[Math.min(page, total) - 1];

  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-black">
      <header className="flex items-center gap-2 border-b border-white/10 bg-black/90 px-3 py-2 backdrop-blur sm:px-4">
        <button type="button" className="btn-ghost px-2 py-1.5" onClick={() => navigate(-1)} aria-label="返回">
          <IconClose className="h-4 w-4" />
        </button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-slate-100">{data.series.title}</p>
          <p className="truncate text-xs text-slate-400">
            {data.chapter.title} · {page}/{total}
          </p>
        </div>

        <div className="hidden items-center gap-1 rounded-lg bg-white/5 p-1 sm:flex">
          <button
            type="button"
            className={`rounded-md px-2 py-1 text-xs ${mode === "paged" ? "bg-accent-500 text-white" : "text-slate-300"}`}
            onClick={() => setMode("paged")}
          >
            分页
          </button>
          <button
            type="button"
            className={`rounded-md px-2 py-1 text-xs ${mode === "webtoon" ? "bg-accent-500 text-white" : "text-slate-300"}`}
            onClick={() => setMode("webtoon")}
          >
            条漫
          </button>
        </div>

        <button
          type="button"
          className="btn-ghost px-2 py-1.5 text-xs"
          onClick={() => setFit(fit === "height" ? "width" : "height")}
          title="切换适配方式"
        >
          {fit === "height" ? "适高" : "适宽"}
        </button>

        <div className="flex items-center gap-1">
          <button
            type="button"
            className="btn-ghost px-2 py-1.5 disabled:opacity-30"
            onClick={() => goChapter(data.prev)}
            disabled={!data.prev}
            aria-label="上一章"
          >
            <IconArrowLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            className="btn-ghost px-2 py-1.5 disabled:opacity-30"
            onClick={() => goChapter(data.next)}
            disabled={!data.next}
            aria-label="下一章"
          >
            <IconArrowRight className="h-4 w-4" />
          </button>
        </div>
      </header>

      <div ref={scroller} className="relative flex-1 overflow-auto">
        {mode === "paged" ? (
          <div className="relative flex h-full min-h-full items-center justify-center">
            <button
              type="button"
              aria-label="上一页"
              className="absolute inset-y-0 left-0 z-10 w-1/3 cursor-w-resize"
              onClick={rtl ? goNext : goPrev}
            />
            <button
              type="button"
              aria-label="下一页"
              className="absolute inset-y-0 right-0 z-10 w-1/3 cursor-e-resize"
              onClick={rtl ? goPrev : goNext}
            />
            <img
              key={current.url}
              src={assetUrl(current.url)}
              alt={`第 ${page} 页`}
              className={
                fit === "width"
                  ? "mx-auto block h-auto w-full max-w-5xl object-contain"
                  : "mx-auto block max-h-full max-w-full object-contain"
              }
            />
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-0 pb-24">
            {data.pages.map((entry) => (
              <img
                key={entry.url}
                src={assetUrl(entry.url)}
                alt={`第 ${entry.n} 页`}
                loading="lazy"
                className="block w-full"
              />
            ))}
          </div>
        )}
      </div>

      <footer className="border-t border-white/10 bg-black/90 px-3 py-2 backdrop-blur sm:px-4">
        <div className="flex items-center gap-3">
          <button
            type="button"
            className="btn-ghost px-2 py-1 disabled:opacity-30"
            onClick={rtl ? goNext : goPrev}
            disabled={page <= 1}
            aria-label="上一页"
          >
            <IconArrowLeft className="h-4 w-4" />
          </button>
          <input
            type="range"
            min={1}
            max={total}
            value={Math.min(page, total)}
            onChange={(event) => setPage(Number(event.target.value))}
            className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-white/15 accent-[#4d8bff]"
            aria-label="页码"
          />
          <span className="w-16 text-center text-xs tabular-nums text-slate-400">
            {page} / {total}
          </span>
          <button
            type="button"
            className="btn-ghost px-2 py-1 disabled:opacity-30"
            onClick={rtl ? goPrev : goNext}
            disabled={page >= total}
            aria-label="下一页"
          >
            <IconArrowRight className="h-4 w-4" />
          </button>
          {page >= total && data.next && (
            <button type="button" className="btn-primary px-3 py-1 text-xs" onClick={() => goChapter(data.next)}>
              下一章
            </button>
          )}
        </div>
      </footer>
    </div>
  );
}

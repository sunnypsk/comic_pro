import { NavLink, Outlet } from "react-router-dom";
import { useDownloadStream, useDownloads } from "../lib/queries";
import { runtime } from "../lib/api";
import { IconDownload, IconHome, IconLibrary, IconSearch, IconSettings } from "./icons";

const NAV = [
  { to: "/", label: "首页", icon: IconHome, end: true },
  { to: "/search", label: "在线搜索", icon: IconSearch, end: false },
  { to: "/library", label: "本地书架", icon: IconLibrary, end: false },
  { to: "/downloads", label: "下载队列", icon: IconDownload, end: false },
  { to: "/settings", label: "设置", icon: IconSettings, end: false },
];

export default function Layout() {
  useDownloadStream();
  const downloads = useDownloads();
  const queue = downloads.data ? downloads.data.stats.queued + downloads.data.stats.running : 0;

  return (
    <div className="min-h-full lg:flex">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-white/5 bg-ink-950/60 px-4 py-6 lg:flex">
        <div className="mb-8 flex items-center gap-2.5 px-1">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent-500 text-lg font-black text-ink-950">
            C
          </span>
          <div>
            <p className="text-sm font-bold tracking-wide text-slate-100">ComicPro</p>
            <p className="text-[11px] text-slate-500">v{runtime.version}</p>
          </div>
        </div>

        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) => `nav-link ${isActive ? "nav-link-active" : ""}`}
            >
              <Icon />
              <span>{label}</span>
              {to === "/downloads" && queue > 0 && (
                <span className="ml-auto rounded-full bg-accent-500 px-2 py-0.5 text-[11px] font-bold text-white">
                  {queue}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        <p className="px-1 text-[11px] leading-relaxed text-slate-600">
          自托管漫画阅读器
          <br />
          数据保存在 NAS 的 /data 卷
        </p>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 flex items-center justify-between border-b border-white/5 bg-ink-950/80 px-4 py-3 backdrop-blur lg:hidden">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-500 text-sm font-black text-ink-950">
              C
            </span>
            <span className="text-sm font-bold">ComicPro</span>
          </div>
          {queue > 0 && <span className="chip">{queue} 个下载中</span>}
        </header>

        <main className="mx-auto w-full max-w-7xl px-4 pb-28 pt-6 lg:px-8 lg:pb-12">
          <Outlet />
        </main>

        <nav className="fixed inset-x-0 bottom-0 z-20 grid grid-cols-5 border-t border-white/10 bg-ink-950/95 backdrop-blur lg:hidden">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex flex-col items-center gap-1 py-2.5 text-[11px] ${
                  isActive ? "text-accent-400" : "text-slate-500"
                }`
              }
            >
              <Icon className="h-5 w-5" />
              {label}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}

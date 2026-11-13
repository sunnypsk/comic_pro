import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Cover } from "./Cover";
import { ProgressBar } from "./ui";

export function ComicCard({
  to,
  title,
  subtitle,
  cover,
  progress,
  badge,
}: {
  to: string;
  title: string;
  subtitle?: string;
  cover?: string;
  progress?: number;
  badge?: ReactNode;
}) {
  return (
    <Link
      to={to}
      className="group card overflow-hidden transition hover:-translate-y-0.5 hover:border-accent-500/40 hover:shadow-accent-500/10"
    >
      <div className="relative aspect-[2/3] overflow-hidden bg-ink-800">
        <Cover
          src={cover}
          alt={title}
          className="h-full w-full transition duration-300 group-hover:scale-[1.03]"
        />
        {badge && <div className="absolute left-2 top-2">{badge}</div>}
      </div>
      <div className="space-y-1.5 p-3">
        <p className="line-clamp-2 text-sm font-semibold leading-snug text-slate-100">{title}</p>
        {subtitle && <p className="line-clamp-1 text-xs text-slate-400">{subtitle}</p>}
        {typeof progress === "number" && progress > 0 && <ProgressBar value={progress} />}
      </div>
    </Link>
  );
}

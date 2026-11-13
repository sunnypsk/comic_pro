import { useEffect, useState } from "react";
import { assetUrl } from "../lib/api";
import { IconBook } from "./icons";

export function Cover({ src, alt, className = "" }: { src?: string; alt: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);

  if (!src || failed) {
    return (
      <div className={`flex items-center justify-center bg-gradient-to-br from-ink-800 to-ink-700 ${className}`}>
        <IconBook className="h-8 w-8 text-slate-600" />
      </div>
    );
  }

  return (
    <img
      src={assetUrl(src)}
      alt={alt}
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
      className={`object-cover ${className}`}
    />
  );
}

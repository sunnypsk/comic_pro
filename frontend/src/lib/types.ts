export interface SourceInfo {
  id: string;
  name: string;
  lang: string;
  nsfw: boolean;
  engine: string;
  base_url: string;
  direction: string;
  enabled: boolean;
  last_error: string;
  last_ok: number | null;
  has_config: boolean;
}

export interface SearchItem {
  source_id: string;
  key: string;
  title: string;
  cover: string;
  description: string;
  tags: string[];
}

export interface SearchOutcome {
  id: string;
  source_name: string;
  nsfw: boolean;
  status: "ok" | "timeout" | "error";
  error: string;
  elapsed_ms: number;
  page: number;
  has_next: boolean;
  items: SearchItem[];
}

export interface SearchResponse {
  query: string;
  page: number;
  sources: SearchOutcome[];
}

export interface Chapter {
  id: number;
  key: string;
  title: string;
  number: number | null;
  downloaded: boolean;
  page_count: number;
}

export interface MangaDetail {
  id: number;
  source_id: string;
  source_name: string;
  key: string;
  title: string;
  cover: string;
  description: string;
  author: string;
  status: string;
  tags: string[];
  follow: boolean;
  auto_download: boolean;
  direction: string;
  chapters: Chapter[];
}

export interface LibrarySeries {
  id: string;
  title: string;
  source_dir: string;
  chapter_count: number;
  page_count: number;
  size_bytes: number;
  updated_at: number;
  cover: string;
}

export interface LibraryChapter {
  index: number;
  title: string;
  page_count: number;
  size_bytes: number;
  updated_at: number;
}

export interface LibraryDetail {
  id: string;
  title: string;
  cover: string;
  chapters: LibraryChapter[];
}

export interface DownloadJob {
  id: number;
  status: "queued" | "running" | "done" | "partial" | "error" | "canceled";
  pages_done: number;
  pages_total: number;
  progress: number;
  error: string;
  attempts: number;
  target_path: string;
  created_at: string;
  updated_at: string;
  chapter: { id: number; title: string; number: number | null } | null;
  manga: { id: number; title: string; source_id: string; key: string } | null;
}

export interface DownloadStats {
  queued: number;
  running: number;
  done: number;
  partial: number;
  error: number;
  canceled: number;
}

export interface DownloadList {
  stats: DownloadStats;
  jobs: DownloadJob[];
}

export interface PageEntry {
  n: number;
  url: string;
}

export interface Manifest {
  kind: "online" | "library";
  series: { id: number | string; title: string; source_id?: string };
  chapter: { id: number | string; title: string; number: number | null };
  item_ref: string;
  chapter_ref: string;
  total: number;
  pages: PageEntry[];
  prev: { id: number; title: string } | null;
  next: { id: number; title: string } | null;
  direction: "ltr" | "rtl";
  progress: number;
}

export interface HomeEntry {
  kind: "online" | "library";
  title: string;
  subtitle: string;
  cover: string;
  href: string;
  page: number;
  page_total: number;
  updated_at: string;
}

export interface HomeRecent {
  id: string;
  title: string;
  chapter_count: number;
  cover: string;
  href: string;
}

export interface HomeResponse {
  continue: HomeEntry[];
  recent: HomeRecent[];
  queue: DownloadStats;
}

export interface HealthResponse {
  status: string;
  version: string;
  db: string;
  uptime_s: number;
  disk: { free_gb: number; total_gb: number };
  queue: DownloadStats;
  counts: { manga: number; library_chapters: number };
  sources: { total: number; enabled: number; errors: Record<string, string> };
}

export interface AppSettings {
  cache_max_gb: number;
  check_interval_min: number;
  env: {
    download_concurrency: number;
    page_concurrency: number;
    source_timeout: number;
    search_timeout: number;
    data_dir: string;
    base_path: string;
    auth_password_set: boolean;
  };
  auth_required: boolean;
  version: string;
  source_count: number;
}

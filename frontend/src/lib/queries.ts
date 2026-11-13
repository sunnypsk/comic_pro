import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "./api";
import type {
  AppSettings,
  DownloadList,
  DownloadStats,
  HealthResponse,
  HomeResponse,
  LibraryDetail,
  LibrarySeries,
  MangaDetail,
  Manifest,
  SearchResponse,
  SourceInfo,
} from "./types";

export const queryKeys = {
  auth: ["auth"] as const,
  health: ["health"] as const,
  sources: ["sources"] as const,
  home: ["home"] as const,
  library: (q: string) => ["library", q] as const,
  libraryDetail: (id: string) => ["library", id] as const,
  manga: (source: string, key: string) => ["manga", source, key] as const,
  search: (q: string) => ["search", q] as const,
  downloads: ["downloads"] as const,
  settings: ["settings"] as const,
};

export interface AuthState {
  required: boolean;
  authenticated: boolean;
  env_managed: boolean;
}

export function useAuthState() {
  return useQuery({
    queryKey: queryKeys.auth,
    queryFn: () => api<AuthState>("/api/auth/state", { skipAuthRedirect: true }),
    staleTime: 30_000,
  });
}

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: () => api<HealthResponse>("/api/health"),
    refetchInterval: 30_000,
  });
}

export function useSources() {
  return useQuery({
    queryKey: queryKeys.sources,
    queryFn: () => api<{ sources: SourceInfo[]; errors: Record<string, string> }>("/api/sources"),
  });
}

export function useHome() {
  return useQuery({ queryKey: queryKeys.home, queryFn: () => api<HomeResponse>("/api/home") });
}

export function useLibrary(query: string) {
  return useQuery({
    queryKey: queryKeys.library(query),
    queryFn: () =>
      api<{ series: LibrarySeries[]; total: number }>(`/api/library?q=${encodeURIComponent(query)}`),
  });
}

export function useLibraryDetail(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.libraryDetail(id ?? ""),
    queryFn: () => api<LibraryDetail>(`/api/library/${id}`),
    enabled: Boolean(id),
  });
}

export function useManga(source: string | undefined, key: string | undefined) {
  return useQuery({
    queryKey: queryKeys.manga(source ?? "", key ?? ""),
    queryFn: () => api<MangaDetail>(`/api/sources/${source}/manga/${key}`),
    enabled: Boolean(source && key),
  });
}

export function useSearch(query: string) {
  return useQuery({
    queryKey: queryKeys.search(query),
    queryFn: () => api<SearchResponse>(`/api/search?q=${encodeURIComponent(query)}`),
    enabled: query.trim().length > 0,
    staleTime: 60_000,
  });
}

export function useDownloads() {
  return useQuery({
    queryKey: queryKeys.downloads,
    queryFn: () => api<DownloadList>("/api/downloads?limit=100"),
    refetchInterval: 5_000,
  });
}

export interface QueueEvent {
  type: string;
  job?: {
    id: number;
    chapter_id: number;
    manga_id: number;
    status: string;
    pages_done: number;
    pages_total: number;
    error: string;
  };
}

/** Subscribe to download progress over SSE; polling in useDownloads is the fallback. */
export function useDownloadStream(onEvent?: (event: QueueEvent) => void): void {
  const queryClient = useQueryClient();
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    const source = new EventSource(`${basePath()}/api/downloads/stream`);
    source.onmessage = (message) => {
      try {
        handler.current?.(JSON.parse(message.data) as QueueEvent);
      } catch {
        /* ignore malformed events */
      }
      queryClient.invalidateQueries({ queryKey: queryKeys.downloads });
      queryClient.invalidateQueries({ queryKey: queryKeys.home });
    };
    return () => source.close();
  }, [queryClient]);
}

function basePath(): string {
  return (window.__COMICPRO__?.basePath ?? "").replace(/\/$/, "");
}

export function useSettings() {
  return useQuery({ queryKey: queryKeys.settings, queryFn: () => api<AppSettings>("/api/settings") });
}

export function useManifest(path: string) {
  return useQuery({
    queryKey: ["manifest", path],
    queryFn: () => api<Manifest>(path),
    staleTime: 0,
    gcTime: 0,
    refetchOnWindowFocus: false,
  });
}

export type { DownloadStats };

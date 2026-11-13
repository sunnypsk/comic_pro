export interface RuntimeConfig {
  basePath: string;
  authRequired: boolean;
  version: string;
}

declare global {
  interface Window {
    __COMICPRO__?: RuntimeConfig;
  }
}

function inferBasePath(): string {
  if (typeof document === "undefined") return "";
  const script = document.querySelector<HTMLScriptElement>('script[type="module"][src]');
  const src = script?.src;
  if (!src) return "";
  const marker = src.indexOf("/assets/");
  if (marker < 0) return "";
  try {
    return new URL(src).pathname.slice(0, marker);
  } catch {
    return "";
  }
}

export const runtime: RuntimeConfig = window.__COMICPRO__ ?? {
  basePath: inferBasePath(),
  authRequired: false,
  version: "dev",
};

export const basePath = runtime.basePath.replace(/\/$/, "");

export function apiUrl(path: string): string {
  return `${basePath}${path}`;
}

/** Prefix server-relative asset/API paths with BASE_PATH; keep absolute URLs untouched. */
export function assetUrl(url: string | null | undefined): string {
  if (!url) return "";
  if (/^(https?:|data:|blob:)/.test(url)) return url;
  if (url.startsWith(basePath + "/")) return url;
  if (url.startsWith("/")) return basePath + url;
  return url;
}

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(message: string, status: number, code = "ERROR") {
    super(message);
    this.status = status;
    this.code = code;
  }
}

interface RequestOptions extends RequestInit {
  skipAuthRedirect?: boolean;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { skipAuthRedirect, headers, ...rest } = options;
  const response = await fetch(apiUrl(path), {
    credentials: "include",
    ...rest,
    headers: {
      ...(rest.body ? { "Content-Type": "application/json" } : {}),
      ...(headers as Record<string, string> | undefined),
    },
  });

  if (response.status === 401 && !skipAuthRedirect) {
    window.dispatchEvent(new Event("comicpro:unauthorized"));
  }

  if (!response.ok) {
    let code = "HTTP_" + response.status;
    let message = `请求失败 (${response.status})`;
    try {
      const payload = await response.json();
      const detail = payload?.detail;
      if (detail && typeof detail === "object") {
        code = detail.code ?? code;
        message = detail.message ?? message;
      } else if (typeof detail === "string") {
        message = detail;
      }
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(message, response.status, code);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function apiText(path: string): Promise<string> {
  const response = await fetch(apiUrl(path), { credentials: "include" });
  if (!response.ok) throw new ApiError(`请求失败 (${response.status})`, response.status);
  return response.text();
}

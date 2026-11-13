import { FormEvent, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Navigate, useNavigate } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { queryKeys, useAuthState } from "../lib/queries";

export default function Login() {
  const auth = useAuthState();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (auth.data && !auth.data.required) {
    return <Navigate to="/" replace />;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ password }),
        skipAuthRedirect: true,
      });
      await queryClient.invalidateQueries({ queryKey: queryKeys.auth });
      queryClient.clear();
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center px-4 py-16">
      <form onSubmit={submit} className="card w-full max-w-sm space-y-5 p-8">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-accent-500 text-xl font-black text-ink-950">
            C
          </span>
          <div>
            <h1 className="text-lg font-bold">ComicPro</h1>
            <p className="text-xs text-slate-400">需要密码才能访问</p>
          </div>
        </div>

        <label className="block space-y-2">
          <span className="label">访问密码</span>
          <input
            className="input"
            type="password"
            autoFocus
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="••••••••"
          />
        </label>

        {error && <p className="rounded-lg bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{error}</p>}

        <button type="submit" className="btn-primary w-full" disabled={busy}>
          {busy ? "验证中…" : "进入"}
        </button>
        <p className="text-center text-[11px] text-slate-500">
          密码保存在服务端 SQLite，可通过 AUTH_PASSWORD 环境变量覆盖
        </p>
      </form>
    </div>
  );
}

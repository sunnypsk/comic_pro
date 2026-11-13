import { useEffect, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import Layout from "./components/Layout";
import { Spinner } from "./components/ui";
import { basePath } from "./lib/api";
import { useAuthState } from "./lib/queries";
import Downloads from "./pages/Downloads";
import Home from "./pages/Home";
import Library from "./pages/Library";
import LibraryDetail from "./pages/LibraryDetail";
import Login from "./pages/Login";
import Manga from "./pages/Manga";
import Reader from "./pages/Reader";
import Search from "./pages/Search";
import Settings from "./pages/Settings";

function Guard({ children }: { children: ReactNode }) {
  const auth = useAuthState();
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    const handler = () => navigate("/login");
    window.addEventListener("comicpro:unauthorized", handler);
    return () => window.removeEventListener("comicpro:unauthorized", handler);
  }, [navigate]);

  if (auth.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner label="正在连接 ComicPro…" />
      </div>
    );
  }

  if (auth.data?.required && !auth.data.authenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}

function NotFound() {
  return (
    <div className="card mx-auto mt-16 max-w-md p-8 text-center">
      <p className="text-3xl">🧭</p>
      <h1 className="mt-3 text-lg font-semibold">页面不存在</h1>
      <p className="mt-1 text-sm text-slate-400">返回首页继续浏览。</p>
      <a href={basePath + "/"} className="btn-primary mt-5">
        回到首页
      </a>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter basename={basePath || "/"}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/reader/:kind/:id/:chapter"
          element={
            <Guard>
              <Reader />
            </Guard>
          }
        />
        <Route
          element={
            <Guard>
              <Layout />
            </Guard>
          }
        >
          <Route index element={<Home />} />
          <Route path="/search" element={<Search />} />
          <Route path="/manga/:source/:key" element={<Manga />} />
          <Route path="/library" element={<Library />} />
          <Route path="/library/:id" element={<LibraryDetail />} />
          <Route path="/downloads" element={<Downloads />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

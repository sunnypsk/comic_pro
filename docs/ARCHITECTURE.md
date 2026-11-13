# 架构说明

ComicPro 是**单进程、单容器**的自托管应用：FastAPI 同时提供 JSON API、图片流和 React 静态资源；下载队列、追更循环、缓存清理都跑在同一个事件循环里；状态落在 SQLite 与 `/data/library` 的 CBZ 文件中。

## 运行时组件

```
浏览器
  │  fetch/SSE/img
  ▼
FastAPI (uvicorn, 单 worker)
  ├─ /api/*            路由：search / sources / downloads / library / reader / settings / auth
  ├─ /api/img          签名图片代理 ──► httpx ──► 源站/CDN
  ├─ /assets, /        React 构建产物（注入 base href 与运行时配置）
  ├─ SourceRegistry    每个源一个 SourceHTTP（限速/重试/连接池）
  ├─ DownloadManager   N 个 worker，DB 队列 + 原子 CBZ 写入
  ├─ Subscriptions     定时刷新关注漫画，自动入队新章节
  ├─ PageCache         磁盘 LRU（cache/pages）
  └─ AuthService       scrypt 密码 + 签名 Cookie（可选开启）
        │
        ▼
SQLite (WAL) + /data/library/**/*.cbz
```

## 关键数据流

### 1. 搜索

`GET /api/search?q=` → `SourceRegistry.search()` 对所有启用源 `asyncio.gather`：

- 每源超时 `search_timeout`，异常/超时被收敛成 `status: error|timeout`，不影响其它源
- 结果统一为 `SearchOutcome`，前端按源分组展示耗时
- 源内部再受 `SourceHTTP` 的并发信号量、最小间隔、429/5xx 指数退避约束
- `BangumiTitles` 与原关键词搜索并发运行，通过公开 API 查询名称和别名；只有与原文、中文名或别名吻合的漫画主条目才用于扩展，排除单行本、小说、动画和歧义匹配。数据来自 Bangumi，无本地作品名称字典。
- 名称查询总时限默认 2 秒，内存 LRU 最多 512 项、成功缓存 24 小时；无匹配缓存 5 分钟、失败缓存 30 秒，429 暂停请求。可用 `COMICPRO_BANGUMI_ENABLED=0` 关闭，不改动 SQLite 或书架数据。
- 每源保留原关键词，再按源语言选择最多两个别名；所有查询共用该源搜索截止时间。按漫画 key 去重，原关键词结果优先，别名失败或超时不会丢弃已取得的结果。分页与源筛选继续生效。
- `/api/search` 增加 `aliases` 名称列表，前端展示识别到的其他名称。原有 `query`、`page`、`sources` 及其结果字段保持兼容。

### 2. 打开详情

`GET /api/sources/{id}/manga/{key}`：

1. `Source.get_manga(key)` 抓取并解析
2. `_upsert_detail()` 把 manga/chapters 写入 SQLite（按 `(source_id, source_key)`、`(manga_id, chapter_key)` 幂等 upsert）
3. 返回章节 ID、下载状态、关注状态，供前端发起下载/阅读

章节 ID 是下载与阅读的稳定引用；站点章节 URL 变化时重新打开详情即可刷新。

### 3. 在线阅读

`GET /api/read/online?manga_id=&chapter_id=`：

1. 用章节 URL 调 `Source.get_pages()` 得到有序图片 URL
2. 每个 URL 生成 **HMAC 签名**：`sig = HMAC(secret, "img|source|url|expires")`，有效期 6 小时
3. 前端 `<img src="/api/img?...">` → 代理校验签名、解析源 `Referer`、抓图、写缓存
4. 前端按 2s 防抖 POST `/api/progress` 保存页码

签名让代理不是开放代理：只有服务端签发过的 URL 可被代理，且代理层仍会做私网地址拦截与图片类型校验。

### 4. 下载

`POST /api/downloads` → `DownloadManager.enqueue()` 写 `download_job` 行 → worker 领取：

```
queued → running → (done | partial | error | canceled)
```

- worker 数 = `download_concurrency`；页级并发由全局信号量 `page_concurrency` 控制
- 每页写入 `library/<source>/<series>/.parts/<index>/pNNNN.ext`，已存在的页在重试时跳过（断点续传）
- 全部页完成后按 `0001.jpg`… 顺序写 ZIP（`ZIP_STORED`，不压缩图片），附 `ComicInfo.xml` 与 `metadata.json`，`os.replace` 原子落盘
- 每章完成后触发一次库扫描（幂等 upsert `library_item`）
- 磁盘写满、全部页失败、源 404 等错误写入 `job.error`；`attempts < 2` 自动重排，否则 `error`

容器启动时 `recover()` 把所有 `running` 任务改回 `queued`，因此重启/断电不会丢任务。

### 5. 本地书架

`POST /api/library/scan` 递归扫描 `library/**/*.cbz`（跳过 `.parts`）：

- 从 `ComicInfo.xml` 读 Series/Title/PageCount，读不到则解析文件名
- 以 `rel_path` 为唯一键 upsert；磁盘上消失的文件同步删除
- 封面按需从第一章 CBZ 的第一页生成缩略图（`cache/covers`）
- 阅读单页时直接从 ZIP 中央目录取目标 entry，`ETag` 支持 304

书架不依赖在线源，源站挂掉后仍可正常阅读。

### 6. 订阅追更

每个 `check_interval_min` 分钟（带 ±10% 抖动），遍历 `manga.follow = 1`：

1. 重新抓章节列表，upsert 新章节
2. `auto_download = 1` 时把新章节加入下载队列
3. 失败只记录日志，不阻塞下一本

## 数据模型

| 表 | 作用 | 关键约束 |
| --- | --- | --- |
| `manga` | 在线作品 | `UNIQUE(source_id, source_key)` |
| `chapter` | 在线章节 | `UNIQUE(manga_id, source_key)` |
| `download_job` | 下载任务 | `UNIQUE(chapter_id)`，状态机 |
| `library_item` | 单个 CBZ 文件 | `UNIQUE(rel_path)`，按 `series_dir` 聚合 |
| `reading_progress` | 阅读进度 | `UNIQUE(kind, item_ref)` |
| `settings` | 运行时设置 | key/value JSON |

SQLite 启用 WAL、`synchronous=NORMAL`、`busy_timeout=5000`；所有事务短小，下载网络请求不持有数据库连接。

## 文件命名

```
library/
└── demo/
    └── Starfall Chronicles-bd0546/      # slug(title)-short_hash(manga_key)
        ├── .parts/0001/                 # 下载中的临时页（断点续传）
        └── 0001 Chapter 1 - The First Star.cbz
```

- 系列目录带 6 位 hash，避免同源下同名作品冲突
- 章节文件以 4 位序号开头，保证文件系统与漫画工具排序稳定
- slug 会过滤 `< > : " / \ | ? *` 与控制字符，并限制长度
- 所有路径经 `ensure_within(library_dir, ...)` 校验，阻止路径穿越

## 缓存与磁盘

| 目录 | 清理策略 |
| --- | --- |
| `cache/pages` | 每 10 分钟按 mtime LRU 清理到 `cache_max_gb * 0.9`；可整目录删除 |
| `cache/covers` | 小文件，按需重生成；可整目录删除 |
| `library` | 只由下载/用户删除操作改变，不会被自动清理 |

## 安全设计

- **鉴权**：可选单密码；scrypt 哈希存 SQLite，环境变量优先；会话 Cookie 带密码指纹，改密即失效；登录 5 次/分钟限速
- **CSRF**：Cookie `SameSite=Lax`，所有写操作走 JSON API（非表单跨站提交）
- **SSRF**：图片抓取只允许 http(s)，解析域名并拒绝私网/回环/链路本地/保留地址，重定向后再次校验
- **开放代理**：图片 URL 必须带服务端 HMAC 签名与过期时间
- **路径**：库文件路径全部规范化并限制在 `DATA_DIR` 内
- **进程**：容器以 root 启动完成 `chown` 后立即 `gosu` 到 PUID/PGID，应用进程非 root

## 扩展点

| 需求 | 位置 |
| --- | --- |
| 新声明式源 | `/data/config/sources/*.yaml` + 设置页编辑 |
| 新抓取逻辑 | `backend/app/sources/` 增加 `Source` 子类并注册 |
| 新下载产物格式 | `services/cbz.py` 的写出函数 |
| 外部通知（Webhook/Telegram） | `services/events.py` 的 `Broadcaster.publish` 处挂订阅者 |
| 定时任务 | `services/subscriptions.py` 的循环 |
| 前端页面 | `frontend/src/pages` + 路由 |

## 明确不做

- 多用户/权限体系（单管理员模型）
- CBR/RAR（需额外解压二进制）
- 内置浏览器渲染（Playwright 体积与内存不适合 NAS 常驻）
- 在线源内容托管/分发：ComicPro 只做客户端抓取与本地存储

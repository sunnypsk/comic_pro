# 编写漫画源

ComicPro 的源是「站点 → ComicPro 数据结构」的适配器。两种方式：

1. **YAML 声明式源**（推荐）：CSS 选择器 + 少量正则，覆盖绝大多数 Madara / MangaStream / 自建 CMS。
2. **Python 源类**：站点有 JSON API、特殊加密、分页签名等复杂逻辑时，继承 `backend/app/sources/base.py` 的 `Source`。

本文只讲 YAML 源。用户源放在 `/data/config/sources/*.yaml`，与内置源同 `id` 时**用户配置覆盖内置配置**。

## 内置源

除了 YAML 引擎，ComicPro 自带两个可直接使用的真实站点适配器（Python `Source` 子类，位于 `backend/app/sources/`）：

| id | 站点 | 抓取方式 | 关闭方式 |
| --- | --- | --- | --- |
| `mangapill` | mangapill.com | 静态 HTML：搜索页、漫画页、`img.js-page` | `COMICPRO_MANGAPILL=0` |
| `weebcentral` | weebcentral.com | 静态 HTML + HTMX 片段：`/search/data`、`/full-chapter-list`、`/chapters/{id}/images` | `COMICPRO_WEEBCENTRAL=0` |
| `dongman` | dongmanmanhua.cn | 官方简体中文条漫：`/search?keyword=`、详情页、阅读页 `img._images[data-url]` | `COMICPRO_DONGMAN=0` |
| `nhentai` | nhentai.net | 公共 API v2：`/api/v2/search`、`/api/v2/galleries/{id}`、`/api/v2/cdn`；NSFW | `COMICPRO_NHENTAI=0` |
| `demo` | 本地生成 | Python 占位页，离线验证全链路 | `COMICPRO_DEMO_SOURCE=0` |

它们和 YAML 源共享搜索聚合、章节入库、下载队列、图片代理与书架逻辑；在设置页可以单独停用。真实源的搜索页结构与站点主题相关，站点改版时按本文的解析思路更新对应 `.py` 即可。

`nhentai` 走公开 API v2（`/api/v2/search`、`/api/v2/galleries/{id}`、`/api/v2/cdn`），无需 API Key；匿名限流约 20 次/分钟，适配器以 1 秒间隔节流并在 429 时退避。搜索框支持站点语法，例如 `language:chinese`、`artist:name`。

## 最小示例

```yaml
id: my-site
name: My Site
engine: madara
base_url: https://manga.example.org
enabled: true
```

`engine: madara` 会自动带入整套默认选择器（见下文），一般只需要改 `base_url`。

## 选择器语法

所有字段都是「选择器字符串」，ComicPro 统一解析：

| 写法 | 含义 |
| --- | --- |
| `.post-title h3 a` | 取第一个匹配节点的文本 |
| `.post-title h3 a@href` | 取第一个匹配节点的 `href` 属性 |
| `.cover img@data-src` | 取懒加载属性 |
| `a, .alt-link a@href` | 逗号分隔的备选，取第一个非空结果 |
| `regex:<pattern>` | 在当前块 HTML 上正则，取第 1 个捕获组 |
| `meta:og:image` | `<meta property/name="og:image">` 的 content |

相对 URL 会基于 `base_url` 自动补全；`data:`、`javascript:`、`about:` 会被忽略。

## 完整 YAML 结构

```yaml
id: my-site                 # 必填，唯一，建议小写短横线
name: My Site               # 展示名
engine: generic             # generic | madara | mangastream
base_url: https://example.org
lang: en                    # 写入 CBZ 的 LanguageISO
nsfw: false
enabled: true
direction: rtl              # 阅读器默认方向：rtl（日漫）或 ltr
headers:                    # 所有请求都会带上
  User-Agent: "Mozilla/5.0 ..."
  Referer: "https://example.org/"
cookies:                    # 可选，字符串或 map；需要登录/过验证时使用
  cf_clearance: "..."

search:
  url: "/?s={q}&page={page}"   # {q}=URL 编码关键词，{page}=页码
  item: ".c-tabs-item__content"
  title: ".post-title h3 a"
  link: ".post-title h3 a@href"
  cover: "img@src"
  description: ".summary-content"
  next: "a.next@href"          # 可选：存在则 has_next=true
  paginated: false             # 可选：站点永远有下一页时置 true

popular:                    # 可选，详情页/搜索页的「热门」
  url: "/?post_type=wp-manga&m_orderby=views"
  item: ".c-tabs-item__content"
  title: ".post-title h3 a"
  link: ".post-title h3 a@href"
  cover: "img@src"

manga:
  title: ".post-title h1"
  cover: ".summary_image img@src"
  description: ".description-summary"
  author: ".author-content"
  status: ".post-status .summary-content"
  tags: ".genres-content a"          # 多个节点 → 数组
  chapters:
    item: ".wp-manga-chapter"
    title: "a"
    link: "a@href"
    date: "span.chapter-release-date"

chapter:
  images:                            # 依次尝试，命中即停止
    - ".reading-content img"
    - ".page-break img"
  attrs: [data-src, data-lazy-src, data-original, src]   # 图片属性优先级
  regex: "https://cdn\\.example\\.org/pages/[0-9]+\\.jpg"  # 可选：直接从 HTML 抽 URL
```

## 引擎预设

`engine` 决定默认值；YAML 中显式写的字段会深度合并覆盖默认值。

| engine | 适用 | 默认 search | 默认章节 | 默认图片 |
| --- | --- | --- | --- | --- |
| `madara` | WordPress Madara 主题（大量漫画站） | `/?s={q}&post_type=wp-manga` | `.wp-manga-chapter` | `.reading-content img` + 懒加载属性 |
| `mangastream` | MangaStream / Themesia 系 | `/?s={q}` | `#chapterlist li a` | `#readerarea img` |
| `generic` | 任意静态 HTML | `/?s={q}`，`article` | `.chapter-list a` | 多容器回退 |

`engine` 只影响默认选择器，不影响抓取逻辑；站点改版时改选择器即可，不必换引擎。

## 章节列表

- 站点通常「新章节在前」，ComicPro 解析后统一**反转为旧 → 新**，写入数据库的顺序即文件名 `0001、0002…` 的顺序。
- 章节号从标题里提取（`Chapter 12`、`第 12 话`、`Ch.12.5`），用于 ComicInfo `Number`。
- 章节 key 由章节 URL 编码而来，站点换域名后旧记录仍指向旧 URL，必要时重新抓取详情即可更新。

## 图片抽取细节

1. 按 `chapter.images` 的顺序尝试容器，**第一个能取到图片的选择器生效**。
2. 每个 `<img>` 按 `chapter.attrs` 顺序找第一个非空属性（默认 `data-src → data-lazy-src → data-original → src`）。
3. 自动去重、忽略 `data:` 占位图。
4. 结果交给图片代理：带上 `headers`（含 Referer）去抓，磁盘缓存 + LRU 清理。

如果站点把页码放在 `<select>` 或接口里，用 `chapter.regex` 直接从 HTML 抓绝对 URL。

## 自动识别（probe）

设置页「添加源」调用 `POST /api/sources/probe`：

```bash
curl -s -X POST http://NAS:8080/api/sources/probe \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://manga.example.org"}' | jq
```

返回：

```json
{
  "engine": "madara",
  "confidence": 0.8,
  "base_url": "https://manga.example.org",
  "id": "manga-example-org",
  "yaml": "id: manga-example-org\n..."
}
```

识别依据是首页 HTML 里的主题指纹（`wp-manga`、`reading-content`、`readerarea` 等）。生成的 YAML 是**完整默认模板**，可直接编辑后保存。

## 调试清单

1. 保存后看设置页源列表是否出现「有错误」；错误来自 YAML 解析或实例化。
2. `POST /api/sources/reload` 返回 `errors` map，文件名 → 错误原因。
3. 用 `curl` 直接请求搜索接口，确认该源 `status` 与 `error`：

   ```bash
   curl -s 'http://NAS:8080/api/search?q=test&sources=my-site' | jq '.sources[0]'
   ```
4. 单章阅读失败时，检查 `GET /api/read/online?manga_id=..&chapter_id=..` 的报错；403 一般是 Cookie/Referer。
5. 需要看完整请求日志：`COMICPRO_LOG_LEVEL=DEBUG docker compose restart comicpro`。

## 已知边界

- **纯 JS 渲染**的站点（图片地址由前端请求接口后再渲染）无法只靠 CSS 抽取。可先用浏览器开发者工具找到该 JSON 接口，再写 Python 源类，或换用提供静态章节页的镜像站。
- Cloudflare 人机校验不提供自动绕过；把浏览器里有效的 `cf_clearance` 等 Cookie 填进源配置即可（Cookie 有时效）。
- 源站限流由 `source_min_interval`（默认 0.25s/请求）与失败退避控制；大规模下载请调低并发。
- 同一 `id` 的源在多个 YAML 中出现时，以 `/data/config/sources` 下的用户配置为准。

## Python 源（进阶）

特殊站点可实现 `Source`：

```python
from app.sources.base import MangaDetail, PageRef, SearchPage, SearchResult, Source, encode_key

class MyApiSource(Source):
    id = "my-api"
    name = "My API"
    base_url = "https://api.example.org"
    engine = "python"

    async def search(self, query: str, page: int = 1) -> SearchPage:
        data = await self.http.json(f"{self.base_url}/search", params={"q": query, "page": page})
        items = [
            SearchResult(
                source_id=self.id,
                key=encode_key(item["url"]),
                title=item["title"],
                url=item["url"],
                cover=item.get("cover", ""),
            )
            for item in data["results"]
        ]
        return SearchPage(items=items, page=page, has_next=bool(data.get("next")))

    async def get_manga(self, key: str) -> MangaDetail: ...
    async def get_pages(self, chapter_url: str) -> list[PageRef]: ...
```

在 `SourceRegistry.load()` 中注册（或作为内置模块加入 `sources/`），即可与 YAML 源一起参与搜索与下载。`PageRef.inline` 可直接返回图片字节，适合需要本地解密的站点。

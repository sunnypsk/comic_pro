# 部署指南（NAS / Docker）

## 前置条件

- Docker Engine 24+ 或 Docker Desktop，支持 `docker compose`
- 一个持久化目录（示例：`/volume1/docker/comicpro/data`），建议 ≥ 20 GB
- 端口 `8080` 可映射；如需外网访问，建议加反向代理 + HTTPS + 访问密码

镜像可本地构建（`docker compose build`），也可先 `docker buildx build --platform linux/amd64,linux/arm64 -t <registry>/comicpro:0.1.0 --push .` 推到自己的镜像仓库，再在各设备拉取。

## 通用 compose

```yaml
services:
  comicpro:
    image: comicpro:latest
    build: .
    container_name: comicpro
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      PUID: 1000
      PGID: 1000
      TZ: Asia/Shanghai
      COMICPRO_CACHE_MAX_GB: 2
      COMICPRO_AUTH_PASSWORD: "change-me"
    volumes:
      - ./data:/data
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/api/health"]
      interval: 30s
      timeout: 5s
      retries: 3
    stop_grace_period: 30s
```

```bash
docker compose up -d --build
docker compose logs -f
```

## 群晖 Synology（DSM 7.x）

1. 套件中心安装 **Container Manager**。
2. 打开「项目」→「新增」，来源选「创建 docker-compose.yml」。
3. 路径选 `/volume1/docker/comicpro`，粘贴上面的 compose（把 `./data` 保持为相对路径）。
4. 通过 SSH 查权限用户：

   ```bash
   id yourname        # 例如 uid=1026(yourname) gid=100(users)
   ```

   把 `PUID` 设为 `1026`、`PGID` 设为 `100`。
5. 构建并启动，访问 `http://群晖IP:8080`。

> 群晖的「项目」会自动执行 `docker compose up`；首次构建约 2–5 分钟（取决于网络与 CPU）。

## Unraid

在 Docker 页点击 **Add Container**，填写：

| 设置 | 值 |
| --- | --- |
| Name | `comicpro` |
| Repository | `ghcr.io/sunnypsk/comic_pro:latest` |
| Network Type | `Bridge` |
| WebUI | `http://[IP]:[PORT:8080]` |
| Container Port / Host Port | `8080` / `8080`（Host Port 可自行更改） |
| Container Path / Host Path | `/data` / `/mnt/user/appdata/comicpro/data` |
| Environment | `PUID=99`、`PGID=100`、`TZ=Asia/Hong_Kong` |

镜像公开后无需 `docker login`。访问 `http://NAS-IP:8080`；需要访问密码时，添加 `COMICPRO_AUTH_PASSWORD` 环境变量，值只保存在 NAS 的容器设置中。

使用 Compose Manager 时，可以直接使用仓库中的 `docker-compose.unraid.yml`。更新只需拉取和重建容器，保留原 `/data` 映射：

```bash
docker compose -f docker-compose.unraid.yml pull
docker compose -f docker-compose.unraid.yml up -d
```

`latest` 跟随通过 CI 的 `master`，`sha-<完整 commit SHA>` 可固定版本；`v1.2.3` 格式的 Git 标签会生成 `1.2.3` 和 `1.2` 镜像标签。GHCR 的 package visibility 与 repository 独立；首次发布后，需要在 package settings 中设为 Public，才能匿名拉取。

## TrueNAS SCALE

1. Apps → **Custom App**（或使用 `docker compose` 的 Sandbox/ jailmaker 环境）。
2. 镜像填你推送的 registry 地址；卷挂载 `pool/apps/comicpro/data` → `/data`。
3. 环境变量同上；`PUID/PGID` 用 `id` 查到的应用用户。
4. 若用官方 Apps 的「Install via YAML」，直接粘贴 compose，注意把 `build:` 去掉改用镜像。

## QNAP

Container Station →「创建」→「应用程序」→ 粘贴 compose；共享文件夹选 `/share/Container/comicpro/data`。QNAP 上常见 `PUID=1000`、`PGID=1000`，以 `id` 输出为准。

## 反向代理

### Nginx（含子路径）

```nginx
# 根路径部署
server {
    listen 443 ssl http2;
    server_name comics.example.com;

    location / {
        proxy_pass http://192.168.1.10:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;          # 下载进度 SSE 需要
        proxy_read_timeout 300s;
    }
}

# 子路径部署：同时设置 COMICPRO_BASE_PATH=/comic
location /comic/ {
    proxy_pass http://192.168.1.10:8080/;   # 末尾斜杠会剥离 /comic
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
}
```

### Nginx Proxy Manager

- Forward Hostname/IP：NAS 内网 IP；Forward Port：`8080`
- 开启 **Block Common Exploits**、申请 Let's Encrypt 证书
- 子路径：Advanced 里加 `proxy_buffering off;`，并让应用设置 `COMICPRO_BASE_PATH=/comic`；NPM 的自定义 location 需使用 `proxy_pass http://IP:8080/;`（带斜杠）

### Traefik

```yaml
labels:
  - traefik.enable=true
  - traefik.http.routers.comicpro.rule=Host(`comics.example.com`)
  - traefik.http.routers.comicpro.tls=true
  - traefik.http.services.comicpro.loadbalancer.server.port=8080
  # SSE 需要关闭响应缓冲（Traefik 默认不缓冲，通常无需额外配置）
```

### Caddy

```caddy
comics.example.com {
    reverse_proxy 192.168.1.10:8080 {
        flush_interval -1
    }
}
```

`flush_interval -1` 用于及时推送 SSE 下载进度。

## 权限（PUID/PGID）

容器以 root 启动，先 `chown -R $PUID:$PGID /data`，再 `gosu` 到该用户运行 uvicorn。这样下载出来的 CBZ 在 NAS 上属于你自己的账号，SMB/NFS 可以直接读写。

排查：

```bash
docker exec comicpro id            # 期望 uid=1000 gid=1000
ls -ln ./data/library | head       # 属主应与 PUID/PGID 一致
```

如果宿主机目录属主不是 PUID/PGID，容器内的 chown 可能因 NFS/ACL 失败；此时在宿主机上执行一次 `chown -R 1000:1000 data`。

## 备份与迁移

```bash
# 停止写入，打包数据
docker compose stop
tar czf comicpro-backup-$(date +%F).tar.gz -C . data
docker compose start
```

恢复：解压回原路径，保持 `data` 属主为 PUID/PGID，再启动。

`data/db/comicpro.db` 使用 WAL，热备份时请连同 `-wal`/`-shm` 一起复制，或先 `stop`。`cache/` 可排除在备份外。

## 升级

```bash
git pull
docker compose up -d --build
```

数据库结构变更由启动时的迁移器处理（`PRAGMA user_version`），升级前建议按上面的方式备份 `data`。

## 资源建议

| NAS 规格 | 建议 |
| --- | --- |
| 2 GB RAM / 双核 ARM | `DOWNLOAD_CONCURRENCY=1`、`PAGE_CONCURRENCY=3`、`CACHE_MAX_GB=1` |
| 4 GB RAM / x86 | 默认值（2/6/5）足够 |
| 多人/大批量下载 | 并发不超过 3；调大 `CHECK_INTERVAL_MIN` 避免频繁抓取 |

在线抓取不占 CPU，瓶颈通常是源站限速与磁盘写入；CBZ 使用 ZIP_STORED，几乎无压缩开销。

## 监控

```bash
curl -s http://NAS:8080/api/health | jq
docker inspect --format '{{.State.Health.Status}}' comicpro
```

`/api/health` 返回数据库状态、磁盘余量、队列统计与各源错误；可接入 Uptime Kuma 等探活。

## 真实源与出网

内置的 Mangapill / Weeb Central / 咚漫 / nhentai 需要容器能访问对应站点与图片 CDN（`mangapill.com`、`cdn.readdetectiveconan.com`、`weebcentral.com`、`temp.compsci88.com`、`scans-hot.planeptune.us`、`dongmanmanhua.cn`、`cdn.dongmanmanhua.cn`、`cdn-sns.dongmanmanhua.cn`、`nhentai.net`、`i1-i4.nhentai.net`、`t1-t4.nhentai.net`）。

- NAS 无法直连时，给容器设置 `COMICPRO_HTTP_PROXY=http://代理地址:端口`（抓取源站与图片都走该代理）
- 也可以只保留自己的源：`COMICPRO_MANGAPILL=0`、`COMICPRO_WEEBCENTRAL=0`、`COMICPRO_DONGMAN=0`、`COMICPRO_NHENTAI=0`
- 源站改版后选择器可能失效，此时搜索会显示该源错误，其它源不受影响；更新 `backend/app/sources/` 下对应适配器即可

## 常见问题

| 问题 | 处理 |
| --- | --- |
| 启动即退出，日志 `Permission denied: /data` | 宿主机目录属主与 `PUID/PGID` 不匹配，或挂载为只读 |
| 页面能开但接口 502 | 反向代理没转发 `/api`，或 `proxy_pass` 少了结尾斜杠导致路径重复 |
| 下载进度不动 | 反代缓冲了 SSE；加 `proxy_buffering off`（Nginx）/ `flush_interval -1`（Caddy） |
| 外网访问没有登录框 | 未设置 `COMICPRO_AUTH_PASSWORD`，或已有 UI 密码但反代缓存了旧页面；强刷并检查 `/api/auth/state` |
| 子路径白屏 | 未设 `COMICPRO_BASE_PATH`，或代理没有剥离前缀 |
| arm64 设备启动报 exec format | 镜像不是多架构构建；用 `buildx --platform linux/arm64` 重新构建/拉取 |

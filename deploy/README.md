# Docker 部署文件

所有构建从仓库根目录执行。每个 Dockerfile 的构建上下文只包含需要的文件；权重、缓存、私有配置和测试记录不会进入镜像。Dockerfile 专用的 ignore 文件优先于根目录规则，参见 [Docker 文档](https://docs.docker.com/build/concepts/context/#dockerignore-files)。

| 文件 | 产物与用途 |
|---|---|
| `Dockerfile` | 自带 Python 依赖和前端的 hub，可独立运行 Mock，也可连接 Scope |
| `compose.yaml` | 无 GPU Mock，项目名 `longlive-mock` |
| `deploy/Dockerfile.scope` | 固定 Scope 镜像 + 本项目 supervisor 和兼容层 |
| `deploy/Dockerfile.runtime` | 小型应用镜像；Python 环境、Scope 源码从共享盘只读挂载 |
| `compose.scope.local.yaml` | 按显式 GPU 列表生成，不进入 Git |

## 已验证的共享盘方式

按 [共享盘部署步骤](../docs/shared-disk-runtime.md) 安装固定依赖、验证权重、生成配置，再启动。此方式已验证 A800 双路实际画面和故障回收。它依赖稳定的绝对路径，移动目录后需要重建虚拟环境和 Compose。

## 完整镜像部署

此方式把 Python/CUDA 依赖放在 Docker 镜像内，镜像占用更多系统盘空间。本次只检查其生成配置，真实 GPU 验收使用的是共享盘方式。

```bash
uv sync --frozen --no-dev
mkdir -p models logs results/raw
python3 scripts/download_verified_models.py
python3 scripts/verify_models.py
uv run python scripts/render_scope_deployment.py --gpu-ids 0,1 --port 8080
# 0,1 仅为示例，必须换成自己获准使用且空闲的 GPU。
docker compose -f compose.scope.local.yaml build
docker compose -f compose.scope.local.yaml up -d
```

可选镜像源保持官方权重哈希不变：

```bash
python3 scripts/download_verified_models.py --mirrors configs/models.mirrors.json --workers 8 --file-workers 2
```

Scope 和 Python 基础镜像摘要来自 `configs/images.lock.json`。Node 构建阶段固定到 22.16.0；`--node-image`、`--scope-image` 可覆盖构建来源，改变版本后需要重新验证兼容性。不要把新版本的结果视为已有性能结论。

## 配置与运维

```bash
docker compose -f compose.scope.local.yaml ps
docker compose -f compose.scope.local.yaml logs --tail=100 hub worker-1 worker-2
uv run python scripts/smoke_api.py --rooms 2 --seconds 30
uv run python scripts/smoke_recovery.py --room night-walk --other-room floating-garden
```

恢复测试会停止并重开指定房间。初次模型加载可能耗时数分钟。`--worker-startup-timeout`、`--pipeline-ready-timeout`、`--first-frame-timeout` 分别控制进程、模型加载和连接后首帧的等待期限。

生成器拒绝覆盖已有配置。明确需要替换时，先保存手动修改，再使用 `--force` 及完整的 GPU、目录和端口参数。增加 Worker 后须重新生成并审阅配置，不把房间数硬编码为上限。

```bash
docker compose -f compose.scope.local.yaml down
```

只停止本项目。hub 不挂载 Docker socket，supervisor 仅管理自己创建的子进程。容器 stdout 使用每份 10 MB、最多 3 份的日志轮转；`logs/` 中的应用事件日志独立保存，由部署者按需清理。

完整镜像不含权重。`models/` 与 `logs/` 通过目录挂载持久保存；下载先于启动，Worker 以离线模型模式运行。只对 hub 发布 `127.0.0.1` 端口，Scope 和控制端口保持在 Compose 内部网络。

# LongLive Rooms

面向课程演示的共享 AI 视频直播间。左侧选择房间，大家观看同一条持续生成的视频；每条提示词显示为弹幕，模型优先接收最新的想法。默认两路，规模由配置决定。

本地开发，Docker 部署。一个房间只运行一份模型推理，增加观众不增加生成槽位。当前实现和验证状态见 [验证记录](results/validation.md)。

## 本地运行：无需 GPU

需要 Python 3.12、uv、Node.js 20.19+ 或 22。

```bash
cp configs/example.env .env
bash scripts/dev_mock.sh
```

打开 `http://127.0.0.1:8080`。Mock 是带房间标识和帧号的测试画面，经真实 WebRTC 传入房间服务；它不代表 AI 模型效果或性能。

```bash
MOCK_WORKER_COUNT=4 bash scripts/dev_mock.sh
uv run pytest -q
bash scripts/smoke_test.sh --rooms 2 --seconds 15
uv run python scripts/browser_smoke.py
```

浏览器测试需要 Playwright Chromium；可执行 `uv run playwright install chromium`，或用 `--browser /path/to/chrome` 指定已有浏览器。原始结果与截图写入 `artifacts/`。按 Ctrl+C 停止本地服务。

## Docker：Mock

```bash
docker compose up --build -d
docker compose logs -f hub
docker compose down
```

入口仅发布到服务器 `127.0.0.1:8080`。不需要 GPU、外部 STUN/TURN 或 Docker socket 挂载。

## Docker：真实 LongLive

需要 Linux、Docker Compose、NVIDIA Container Toolkit，以及可用的 NVIDIA GPU。先检查授权 GPU 是否空闲。以下 `0,1` 是一个两卡示例，需按自己的设备权限配置。

1. 下载固定模型到持久目录。`models/`、缓存和日志不进入 Git 或应用镜像。

```bash
mkdir -p models logs results/raw
python3 scripts/download_verified_models.py
python3 scripts/verify_models.py
```

若服务器访问 Hugging Face 较慢，可使用已核对文件哈希的国内镜像。镜像只改变下载地址；全部文件仍须通过原始官方清单的 SHA256 校验。已完成的分块可在重跑时复用。

```bash
python3 scripts/download_verified_models.py --mirrors configs/models.mirrors.json --workers 8 --file-workers 2
python3 scripts/verify_models.py
```

`--workers` 是每个文件的分块并发数，`--file-workers` 是同时下载的文件数。未列入镜像清单的配置和分词器文件仍从 Hugging Face 下载；可用 `--endpoint` 指定 HTTPS 镜像，哈希要求保持不变。

2. 生成当前部署的 Worker 清单和 Compose 文件。这两个 `.local.yaml` 文件包含设备与部署参数，被 Git 忽略。

```bash
uv run python scripts/render_scope_deployment.py --gpu-ids 0,1
docker compose -f compose.scope.local.yaml up --build -d
docker compose -f compose.scope.local.yaml logs -f hub worker-1 worker-2
```

首次启动要加载模型；页面会显示准备状态。要降低生成分辨率，生成配置时加 `--width 384 --height 224`，两者必须为 16 的倍数。更多 Worker 使用显式设备列表，例如 `--gpu-ids 0,1,2,3`；默认房间仍为两个，可在网页创建更多房间，或编辑生成的房间配置。

3. 从自己的电脑访问：

```bash
bash scripts/tunnel.sh YOUR_SSH_ALIAS
```

保持终端打开，在浏览器访问 `http://127.0.0.1:8080`。网页、弹幕和画面共享同一个 TCP 隧道。服务器内部仍使用 WebRTC；浏览器使用有界的 JPEG WebSocket 流，避免把“HTTP 隧道可达”误当成浏览器 WebRTC 媒体可达。

4. 验证与停止：

```bash
bash scripts/smoke_test.sh --rooms 2 --seconds 30 --output artifacts/real-smoke.json
docker compose -f compose.scope.local.yaml logs --no-color > results/raw/compose.log
docker compose -f compose.scope.local.yaml down
```

只使用本项目 Compose 文件和项目名停止服务。不要按 GPU 编号批量终止其他人的进程。

## 实现约定

Docker 系统盘空间较小时，可使用[共享磁盘运行环境方案](docs/shared-disk-runtime.md)，将模型和 Python 环境放在项目数据盘，并以只读挂载接入小型应用镜像。

- FastAPI 单管理进程；真实后端、Mock、Worker 数量、分辨率、超时都由配置控制。
- Scope Worker 每个进程只承载一个生成房间。进程内 supervisor 只重启自己创建的子进程；模型重新就绪后才释放槽位。
- 观众断线只回收自己的连接；停播才回收房间的生成资源。
- 提示词状态分别显示已提交、被替代、已投递、过期或失败。“已投递”不表示画面已符合提示词。
- 消息、帧、重试记录均有界；慢观众不会让直播积压大量旧帧。
- 当前房间、历史与幂等记录为进程内状态；重启后重新开始，不承诺历史恢复。
- 只面向受控演示访问，当前没有公开服务的身份与权限系统。

## 项目文件

| 路径 | 用途 |
|---|---|
| `docs/implementation_spec.md` | 当前共享直播间规格 |
| `api/openapi.yaml` | 与运行服务一致的 HTTP 契约 |
| `docs/stream-protocol.md` | 弹幕、心跳和二进制画面协议 |
| `docs/compatibility.md` | 固定 Scope 版本与兼容改动 |
| `longlive/` | 控制服务、媒体适配器、生命周期 |
| `web/` | TypeScript 网页 |
| `deploy/` | Scope 容器和自有子进程管理 |
| `configs/models*.json` | 模型 revision、文件尺寸与哈希 |
| `tests/`、`scripts/` | 自动化检查和运行工具 |

原始中文 Markdown 和 OpenAPI v2 保留为历史输入，不再是共享直播间的当前接口。修改 API 后执行 `PYTHONPATH=. uv run python scripts/export_openapi.py` 并运行测试。

## 排错与测量

- 入口有响应、画面未出现：查看房间状态与 hub 日志，再检查对应 Worker 的模型加载和媒体连接。
- Worker 被隔离：查看 reset/进程退出错误。不能仅凭 HTTP 健康就手动把槽位标为可用；修复后受控重启本项目服务。
- 镜像下载受服务器代理影响：不要为此修改共享主机的全局配置。可用 `scripts/import_image.py` 配合官方 Crane 按摘要下载 Docker archive 再导入；这是可选运维工具。
- 原始生成吞吐来自 Worker 日志的 `model_output_batch`；界面与冒烟脚本统计的是源收帧/浏览器接收吞吐。冷启动、首个中继帧、浏览器首帧应分开报告。
- GPU 性能必须按真实配置实测；Mock 通过不能替代真实单路与两路验收。

上游 [Scope](https://github.com/daydreamlive/scope) 与 [LongLive](https://github.com/NVlabs/LongLive) 的代码和模型仍遵循各自许可；本项目不分发权重。

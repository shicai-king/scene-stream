# LongLive Rooms

面向课程演示的共享 AI 视频直播间。左侧选择房间，观众共享同一条持续生成的视频；每条提示词显示为弹幕，模型优先接收最新的未投递提示词。默认两路，规模由配置决定。

本项目提供网页、房间管理、视频分发和 Scope 适配器。模型推理由 [Scope](https://github.com/daydreamlive/scope) 中的 LongLive 完成。一个房间占用一个生成槽位，增加观众不会增加模型实例。

## 验证状态

已在两张 A800 80GB 上完成真实双路验证：384×224、BF16，每路服务端视频接收约 **21 FPS**。共享观看、提示词改变画面、房间隔离、停播复用和单 Worker 故障恢复均已验证。完整配置、测量方法和限制见[验收记录](results/validation.md)。

## 快速体验：Docker Mock

需要 Docker Engine 和 Compose。无需 GPU；Mock 是带标识的测试画面，用于检查网页、弹幕与资源调度。

```bash
docker compose up --build -d
```

打开 **http://127.0.0.1:8080**。停止：

```bash
docker compose down
```

Mock 使用独立的 Compose 项目名 `longlive-mock`。真实部署默认使用 `longlive-rooms`，两者并行运行时还需要选择不同的入口端口。

## 真实模型部署

需要 Linux、Docker Compose、NVIDIA Container Toolkit 和获准使用的 NVIDIA GPU。已验证的配置是一张 A800 对应一个房间，默认两个房间。权重约 17.3 GB，首次部署还需要下载 Python/CUDA 依赖。

| 方式 | 入口 | 当前验证范围 |
|---|---|---|
| 共享盘环境 + 小型 Docker 镜像 | [完整步骤](docs/shared-disk-runtime.md) | 已验证真实单路、双路和恢复 |
| 完整 Scope Docker 镜像 | [部署说明](deploy/README.md#完整镜像部署) | 配置检查；尚未做该镜像路径的 GPU 验收 |

部署脚本需要显式指定 GPU，默认分辨率为实测的 384×224。生成的 `compose.scope.local.yaml` 与 `configs/workers.local.yaml` 包含当前设备和目录信息，不提交 Git；再次生成需要显式加 `--force`。

服务器入口只绑定回环地址。在自己的电脑执行：

```bash
bash scripts/tunnel.sh YOUR_SSH_ALIAS 8080 8080
```

保持终端打开，访问 http://127.0.0.1:8080 。脚本后两个参数分别是本地和服务器端口。网页、弹幕与视频使用同一个 SSH TCP 隧道。

## 本地开发

需要 Python 3.12、uv、Node.js 20.19+ 或 22。

```bash
cp configs/example.env .env
bash scripts/dev_mock.sh
```

`.env` 由模板复制后自行修改；程序不会生成或提交真实部署凭据。按 Ctrl+C 停止。

```bash
uv sync --frozen
npm ci
uv run pytest -q
npm run build
uv run python scripts/smoke_api.py --rooms 2 --seconds 15
```

冒烟测试需要服务已启动。浏览器测试使用 `uv run playwright install chromium` 安装浏览器后执行 `uv run python scripts/browser_smoke.py`，或使用 `--browser /path/to/chrome` 指定已有浏览器。

## 目录

| 路径 | 内容 |
|---|---|
| `longlive/`、`web/` | Python 服务与 TypeScript 网页 |
| `Dockerfile`、`compose.yaml` | 独立的 Mock / hub 镜像与本地演示 |
| `deploy/` | Scope Worker、小型运行镜像、进程 supervisor |
| `configs/` | 公共配置模板、镜像/源码/权重锁定清单 |
| `api/`、`docs/` | 当前 API、协议、部署和实现说明 |
| `scripts/`、`tests/` | 下载、部署、验证、打包工具与测试 |
| `scripts/ops/` | 可选的网络受限环境运维工具 |
| `results/validation.md` | 实际验收结果 |

旧设计保存在 Git 的 `docs/archive/`，不属于当前实施契约，也不进入干净源码导出包。运行生成的 `models/`、`runtime/`、`cache/`、`logs/`、`artifacts/` 均被 Git 忽略。

## 行为与边界

- 房间拥有生成任务；观众断开只移除自己的连接。
- 每条被接受的提示词成为弹幕；仅保留最新一条未投递指令。“已投递”不等于画面已经符合提示词，场景变化可能保留旧元素。
- Worker 只有在自有进程重建、模型加载和清理验证完成后才可复用；没有可靠重置能力的外部 Worker 会被隔离。
- 画面队列、消息历史和幂等记录有界。当前状态在内存中，重启后重新开始。
- 当前用于私人演示访问，没有公开服务的账号和权限体系。
- [实现规格](docs/implementation_spec.md)、[媒体协议](docs/stream-protocol.md)、[Scope 兼容说明](docs/compatibility.md)记录具体约定。

## GitHub 与许可

源码检查、打包和上传步骤见 [GitHub 准备说明](docs/github.md)。GitHub Actions 配置运行软件测试、前端构建和 Mock Docker 冒烟测试，不使用 GPU，也不自动发布镜像。

**本项目暂未指定许可证。** 第三方代码与模型保留各自许可，详见 [第三方说明](THIRD_PARTY_NOTICES.md)。源码包不包含 Scope 源码、模型权重或私有部署配置。

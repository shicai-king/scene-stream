# Codex 实施入口：多会话交互式视频流服务（可扩展版本）

请**实际创建、运行、测试**一个可配置容量、可替换视频后端的多会话服务。2026-11-24 用户已补充共享直播间与弹幕需求；实施前先读 `docs/requirements-review.md`，本文件下文与最新需求冲突的旧设计必须先修订，不得直接照搬。

当前实际提供的设计材料为：

- `多会话AI视频流服务_可扩展技术实施方案.md`：原始 V3 规格，结合需求修订阅读。
- `多会话AI视频流服务_OpenAPI_v2.yaml`：已提供的原有独立会话契约；尚不包含共享直播间、观众与弹幕广播。
- `docs/requirements-review.md`：最新需求、差异、生命周期修订、验收及当前验证状态。

`AGENTS.md`、`api/openapi.yaml`、`configs/workers.example.yaml`、`configs/example.env` 当前尚未提供或创建，不得当成已存在的依据。共享直播间契约确定后，创建对应实现产物并同步规格、OpenAPI 与测试；保留原始 v2 用于追踪设计变化。下文列出的脚本与命令均为待实现目标，不代表已存在或已通过验证。

## 优先约束：不要写死规模

- **不得在业务逻辑中写死房间数量、模型名称、Worker 列表、GPU 数量、端口或设备编号。** 示例展示 2 个房间，只是测试输入，并不是业务上限。
- 前端用 `Session[]` 动态生成房间卡片，每个卡片独立维护 `RTCPeerConnection`、DataChannel、心跳和 UI 状态。
- 后端根据 `WorkerRegistry` 的健康槽位实时计算容量，`SESSION_ACTIVE_LIMIT` 可选。Worker 首版 `max_sessions=1`，未来支持多槽位必须有隔离与 reset 证明。
- 先实现 `reject + first_available` 策略；可替换策略接口为后续排队、优先级、负载感知预留，不要求首版实现。
- 用 `WorkerAdapter` 封装 Mock/Scope 的操作；模型由 `pipeline_id` 选择，不要使 `SessionManager` 依赖 `longlive` 字面值。
- API 里 `/api/v1/capacity`、分页 `/api/v1/sessions` 必须落实，容量与页面上的可创建状态以真实 registry 为准。

## 分阶段实际实施

1. **契约与能力核验**：检查 Scope 官方固定版本的 API，记录 commit、模型权重来源和必要命令。将未经验证的第三方 stop/reset 行为标记待验证，不准杜撰。
2. **Mock 系统先行**：实现 FastAPI Session Manager、WorkerRegistry、原子分配、aiortc 视频 Mock、动态房间前端、两阶段提示词投递、WebRTC 信令与状态机。`MOCK_WORKER_COUNT=1,2,4` 等值时无需修改代码。
3. **自动化回归**：使用参数化 N 个健康槽位的测试；第 N+1 次创建（默认 reject）返回 `429`，另测幂等键、断线、乱序、重置失败隔离。先通过 Mock，再接真实后端。
4. **Scope 适配器**：运行 LongLive 1.0 (`pipeline_id=longlive`)；按官方 Load / Receive / Parameters 文档验证首帧和 DataChannel，最后按配置添加更多 Worker。MemFlow 仅在适配通过相同契约后启用。
5. **验证与交付**：生成 README、`.env.example`、`workers.example.yaml`、`docs/compatibility.md`，提供脚本启动/停止/测试/导出 JSONL+CSV。记录真实模型使用环境和性能数据，不把 Mock FPS 当作模型性能。

## 强制质量与安全规则

- 不做模型训练、剧情大语言模型、Kubernetes、多管理器状态同步和公网可访问服务；这些是可选扩展，不是 MVP 前置条件。
- 只有在绑定 Worker 的状态确实清空后才能标记槽位 `FREE`；如果 Scope 无可靠 reset，就受控重启 **该 Worker 自有进程**，成功预热后复用。隔离失败 Worker。
- `HTTP 202` 仅表示已接受 Prompt 登记；DataChannel 发送不代表模型采用；画面变化需独立观测。
- 浏览器与 Worker 的 ICE 通信需实际验证；不能用 SDP 交换成功代替收帧成功。
- 不应修改部署环境访问控制，默认服务仅绑定 loopback 或经批准的受控网络；密钥不得入库。
- **逐阶段运行实际命令并报告通过的测试数量、缺失能力和阻塞原因。** 环境无法访问真实模型时，完整交付 Mock 版与可执行真实部署说明，不要虚构成功。

## 最终验收

- `bash scripts/dev_mock.sh` 启动 Mock；`pytest -q`、`bash scripts/smoke_test.sh` 通过。
- `MOCK_WORKER_COUNT=1`、`2`、`4` 等场景可独立设置并运行，动态 UI、动态容量、拒绝和资源回收与配置一致，无硬编码。
- 实时视频连接正确，多个房间的提示词、视频轨道和历史互不混淆。
- `api/openapi.yaml` 与实际服务一致，示例 curl 和 JSON 可复现。
- 真实 Scope 适配器至少有单路端到端测试证据；进一步并发规模以资源与真实测试结果决定。

## 官方核验材料

- https://github.com/daydreamlive/scope/blob/main/docs/server.md
- https://github.com/daydreamlive/scope/blob/main/docs/api/load.md
- https://github.com/daydreamlive/scope/blob/main/docs/api/receive.md
- https://github.com/daydreamlive/scope/blob/main/docs/api/parameters.md
- https://github.com/NVlabs/LongLive/tree/main/LongLive1.0

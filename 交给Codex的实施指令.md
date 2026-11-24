# Codex 实施入口：共享 AI 视频直播间

本项目已按用户确认的课程演示需求进入实现。当前设计入口：

1. `AGENTS.md`：实现、设备授权与验证约束。
2. `docs/implementation_spec.md`：V4 共享直播间语义。
3. `api/openapi.yaml`：从实际 FastAPI 服务导出的 HTTP 契约。
4. `docs/stream-protocol.md`：观众画面、弹幕与心跳协议。
5. `docs/compatibility.md`：固定 Scope 版本、模型与兼容改动。
6. `configs/workers.example.yaml`、`configs/example.env`：可用的配置模板。
7. `results/validation.md`：实际验证状态。

根目录原始 V3 方案和 OpenAPI v2 为历史设计材料；其中“一观众一推理会话”“浏览器直接二次投递提示词”“观众离开即停止生成”等约定已经被 V4 取代。不得按旧接口重新实现独立播放卡片。

## 已确认的用户目标

- 课程演示；本地开发和 Git 版本管理，Docker 部署到用户明确授权的服务器目录。
- 左侧选择直播间，房间内共享一条持续生成视频，所有参与者均可发提示词。
- 所有被接受的提示词显示为弹幕。模型优先采用最新的未投递指令，单个房间只有一个上游发送者。
- 默认两路真实生成，规模可配置。优先实时性，清晰度可让步；必须实测。
- 只需用户电脑访问。网页、视频和弹幕通过一个私有 TCP 入口，支持 SSH 隧道。
- GPU、路径与 SSH 别名以当前对话和忽略的本地部署记录为准；不得使用未授权设备或发布 GitHub。

## 实施与验收

先验证固定版本的真实模型环境和单路流，再完成共享观看及两路并发。无 GPU 的 Mock 使用真实 WebRTC 进行软件管线验证；不能替代真实生成性能。

`uv run pytest -q`、`npm run build`、`bash scripts/smoke_test.sh` 和 `scripts/browser_smoke.py` 分别检查逻辑、构建、接口/媒体与浏览器行为。所有实际通过和未通过项记录到 `results/validation.md`。

Worker 必须完成安全清理、进程恢复与必要的模型就绪验证才能复用。外部无可靠 reset 的实例必须隔离。Scope HTTP DELETE、数据通道发送成功或健康探测均不能单独证明历史清空或画面已采用提示。

Level 1 软件框架、Level 2 真实单路、Level 3 真实多路分别报告。此次用户目标包含真实两路，不能仅交付 Mock 就宣称全部完成。

# 面向多会话的交互式 AI 视频流服务：技术实施规格书

> **2026-11-24 需求修订提示**：用户已明确课程演示采用共享直播间、左侧房间选择、人人可发提示词和弹幕、默认两路真实生成。请先阅读 `docs/requirements-review.md`。下文 V3 中“一浏览器连接对应一个生成会话”“浏览器直接二次投递提示词”“观众失联即关闭生成”等设计不能原样用于新需求。新增的 `多会话AI视频流服务_OpenAPI_v2.yaml` 是原有会话接口基线，共享房间契约尚待修订。

**文档版本**：V3.0（可配置、可扩展、实现导向）  
**项目类型**：计算机网络与 AI 推理服务基础设施实践  
**技术基线**：可插拔视频后端；参考实现 LongLive 1.3B / Daydream Scope，MemFlow 1.3B 为备选  
**状态**：待实施技术方案；本文件不代表系统已经部署或完成性能验证  
**日期**：2026-11-24

> **执行约定**：本文描述拟实现系统的自定义接口、状态机与验收标准，不应被误认为 Scope 原生接口。第三方框架的可用操作必须以实际固定版本的代码和接口文档为准。不能确定时，先运行能力探测和最小验证，不得臆造 SDK 方法或声明实现已成功。

## 0. 摘要与实现边界

建设一个支持**可配置数量的独立文本引导视频生成房间**的原型服务。系统通过资源注册表管理可用 Worker，在首版默认采用一个 Worker 承载一个活动会话的保守隔离策略；应用层不写死房间数量、设备数量、端口数量或具体模型。用户可以在播放期间提交新的画面提示词；服务提供创建、查询、更新、停止、容量限制、连接监测和安全回收。浏览器通过 WebRTC 接收视频，控制服务负责房间与 Worker 的绑定、HTTP 信令代理及资源管理。

**MVP 必须做到**：

1. 在可配置的 Worker 池下按资源动态创建多个独立房间；用至少两个房间进行会话隔离验证，但**不把两个写成业务上限**。
2. 首版每个活动房间独占一个 Worker；实际容量来自健康 Worker 的可用槽位与可选全局上限。容量耗尽时按策略明确拒绝，而非默默无限排队。
3. 实现创建、列表/查询、容量查询、提示词登记、WebRTC offer/ICE、心跳和关闭 API；支持前端动态增删房间。
4. 正常关闭、失联超时、worker 故障及重置失败时，资源状态正确；故障实例不得立即复用。
5. 提供不依赖 GPU 的 WebRTC Mock Worker；Mock 实例数由配置决定，同一套接口测试可覆盖不同池规模并用于真实后端验证。
6. 输出可复现实验脚本、结构化日志与真实性能评测结果，不预先承诺实时 FPS。容量实验采用 N 与 N+1 的通用参数，不内置第三房间这种特殊判断。

**明确不做**：训练/微调模型、从零实现视频扩散推理、自研 WebRTC 协议栈、开放式剧情导演 LLM、多人投票、跨 worker 迁移历史状态、无限规模调度、跨公网部署、正式账号与计费系统。首版也不保证断线后无缝续接旧视频历史。

## 1. 目标、成功标准与关键假设

### 1.1 核心技术问题

在有限且固定的推理实例数下，如何同时维护多个持续生成的视频会话，并确保其**控制消息路由正确、媒体连接可用、状态互相隔离、资源可被安全回收**？如何区分模型生成速度、WebRTC 收帧速度与提示词对画面的真实影响？

### 1.2 非功能要求

- **可替换性**：应用层只依赖 `WorkerAdapter`、`WorkerRegistry`、`AdmissionPolicy`、`MediaTransport` 抽象；后端选择与 Worker 清单均由配置决定。
- **可预测容量**：实际容量由资源注册表中的健康可用槽位推导；首版每个 Worker 一个槽位，业务不依赖固定总数量。默认无排队，容量不足返回 `429 NO_CAPACITY`；保留将来替换准入策略的接口。
- **可观测性**：每个请求、房间、worker 有可关联的 ID；日志为结构化 JSONL。
- **可恢复性**：释放失败进入 `QUARANTINED`；重启管理器时旧活动会话视为失效，并按所有权记录清理其管理的子进程；不要越权杀死共享或外部进程。
- **可复现性**：依赖与第三方仓库固定版本；保留配置快照、实验种子、原始数据和复现命令。
- **安全边界**：默认绑定本机或经授权的私有网络；对外网公开部署不属于 MVP。默认不使用未授权的外部 TURN/STUN。

### 1.3 可验证验收

- **功能性**：在容量允许时至少两个独立会话持续运行并可分别更新提示词；UI 不限制房间数，录屏与日志能证明状态隔离。
- **网络性**：WebRTC ICE/连接成功且浏览器收到有效解码帧；不能只以 HTTP 200 判定成功。
- **容量性**：设可用容量为 N，允许创建 N 个会话且第 N+1 个在默认拒绝策略下收到 `429`；N 从配置和健康槽位推导，原有会话不被抢占。
- **回收性**：`DELETE`、失联和异常路径不会把仍有历史状态的 worker 标成 `FREE`。
- **实测性**：真实后端至少完成单路端到端验证；再选择 2、4 等若干不超过真实容量的并发档位进行扩展测试。无法完成某档位时须报告原因，不得以 Mock 结果代替真实生成性能。

## 2. 技术选择与版本锁定

| 层次 | 方案 | 原因与注意事项 |
|---|---|---|
| 视频生成 | LongLive 1.0 / 1.3B（优先）；MemFlow 1.3B（备选） | 两者均有连续提示词引导的视频生成路线；选用其一，不同时维护两套正式后端。 |
| 运行与媒体 | Daydream Scope，锁定 commit | 官方文档支持 `longlive`、`memflow` 管线、WebRTC、数据通道参数更新；实际接口以所锁定提交为准。 |
| 控制 API | Python 3.11、FastAPI、Pydantic、Uvicorn、HTTPX | 管理会话、转发 HTTP 信令、执行异步资源回收。 |
| 浏览器 | TypeScript + Vite + 原生 RTCPeerConnection | 两个独立视频元素、连接事件、提示词输入、性能时间戳。 |
| Mock | Python、aiortc、PyAV/NumPy | 产生携带 session 标记和帧序号的真实视频 track，验证 SDP/ICE/数据通道。 |
| 测试 | pytest、pytest-asyncio、Playwright（端到端）、小型 Python 实验脚本 | 覆盖状态机、并发、异常、真实连接与指标。 |
| 部署 | 单机多进程作为第一个可运行拓扑 | 一个管理服务 + N 个可注册 Worker；Worker 可由本地子进程、已启动实例或后续远端实例提供，不将 Worker 与设备数量一一绑定。 |

**版本原则**：首次部署时记录 `git rev-parse HEAD`、Python/Node/驱动版本、模型权重版本及文件校验或来源；写入 `configs/lock-report.json`，不使用浮动分支结果作为正式实验条件。

**已知官方接口事实**：Scope 提供 `POST /api/v1/pipeline/load`、`GET /api/v1/pipeline/status`、`POST /api/v1/webrtc/offer`、`PATCH /api/v1/webrtc/offer/{scope_session_id}`，运行中的提示词更新通过名为 `parameters` 的 WebRTC data channel 发送。Scope 文档没有为本项目承诺完整的 worker stop/reset API；必须自行验证并设计兜底策略。参见文末官方资料。

## 3. 系统架构

```text
                  ┌────────────── Browser UI ───────────────┐
                  │ 动态 RoomCard 列表（0..N）              │
                  │ 每房间：Prompt、PeerConnection、Video   │
                  └─────────────┬──────────────┬───────────┘
                        HTTPS/HTTP 控制         │ WebRTC 媒体/DataChannel
                                ▼              │
               ┌────────────────────────────┐  │
               │ Session API / Manager      │  │
               │ SessionStore + Lease       │  │
               │ WorkerRegistry + Allocator │  │
               │ AdmissionPolicy            │  │
               │ Signaling Adapter          │  │
               └──────────┬─────────────────┘  │
                          │ 每房间粘性绑定     │
             ┌────────────┼─────────────────────┘
             ▼            ▼                 ▼
          Worker-1     Worker-2      ... Worker-N
          Scope/Mock   Scope/Mock        Scope/Mock
          独立历史     独立历史          独立历史
```

### 3.1 控制面、媒体面与模型后端边界

- **控制面**：浏览器经项目 HTTP API 管理房间、更新意图、心跳和 SDP/ICE 信令。API 通过 `session_id` 找到绑定 Worker，并路由到对应上游。不可由客户端指定内部 Worker 地址。
- **媒体面**：WebRTC PeerConnection 在浏览器与选定 Worker 间协商视频与 `parameters` DataChannel；媒体可能走直连或中继，**不假定视频经 HTTP 管理器转发**。
- **后端适配**：公开会话 ID 是 `session_id`；Scope 内部 WebRTC ID 只留在 WorkerAdapter 内。将来换 MemFlow、其他推理服务或新的视频输出协议，不能改变应用层会话标识与生命周期语义。
- **无视频 LLM 依赖**：首版前端提交文字提示词直达视频模型；叙事规划、文本扩写和视频理解为可选附加模块，不得作为部署前置条件。

### 3.2 扩展性约束（必须在代码结构中体现）

1. **房间数不写死**：前端使用 `sessions: Session[]` 动态渲染 `RoomCard`；新建按钮只受容量/权限控制。测试展示 2 个窗口只是示例，组件不得固定为 `roomA` / `roomB`。
2. **Worker 池动态配置**：`configs/workers.yaml` 是初始注册表，启动时加载任意数量条目；每个 Worker 有稳定 ID、backend、endpoint、device affinity（可选）、能力与健康状态。支持启动时发现健康度；扩缩 Worker 不应要求改业务逻辑。
3. **容量不是 GPU 数量**：基于 Worker `max_sessions`（首版 Scope/Mock 默认为 1）和健康/预留/占用槽位计算。`SESSION_ACTIVE_LIMIT` 可选，为空时仅受真实可用槽位约束；配置成正整数时作为业务上限。统计字段通过 `/api/v1/capacity` 暴露，返回抽象计数，不泄露内部地址。
4. **调度策略可替换**：首版 `first-available`、`reject`；将来可增加 `least-loaded`、排队、优先级，不更改 HTTP 契约。**不得**为了演示某个 N 特判“第 N+1 间”。
5. **模型可替换**：`backend_kind` 与 `pipeline_id` 在实例配置里设置。接口只描述能力，不绑定 `longlive` 常量。未来 MemFlow、LTX 或其他模型需要适配器/能力声明，不保证它们有同样的实时提示更新语义。
6. **传输可替换**：`MediaTransport` 的 V1 实现是 WebRTC；若未来变成分段视频/HLS，接口层通过 `capabilities` 宣告不同的连接流程，不把 Scope SDP 字段扩散进业务模型。
7. **版本和拓扑明确**：首版仅保证一个 Session Manager 进程下 N 个 Worker 的正确分配；**不等于多个管理器实例的全局一致性**。以后水平扩容需引入共享状态、分布式锁与失败恢复设计。

### 3.3 部署模式

- **Mock 模式**：无需 GPU。`MOCK_WORKER_COUNT` 或 Worker 注册表决定测试实例数量；Mock 输出独立 WebRTC 视频轨道，并支持故障注入。
- **Scope 模式**：根据 `workers.yaml` 管理或接入 N 个独立 Scope 进程，逐个完成模型加载与 readiness；所有端口、设备绑定、模型参数由配置提供。
- **网络边界**：默认只在授权的私有部署环境可达；必须单独验证浏览器与 Worker 之间的 ICE 媒体路径。外部 STUN/TURN 在配置明确允许时才启用。

## 4. 生命周期与并发规则

### 4.1 用户会话状态机

```text
POST /sessions
      │
      ▼
 ALLOCATED ── offer ──► CONNECTING ── 视频首帧可观察 ──► ACTIVE
      │                      │                             │
      └───── 过期/错误 ───────┴──────────── 结束/过期 ──────┘
                                     │
                                     ▼
                                  CLOSING
                                     │
                              清理并验收通过
                                     ▼
                                   CLOSED
                       清理失败 ──► FAILED
```

`ACTIVE` 表示客户端报告媒体已经连接且观察到帧；这是客户端观测状态，服务端同时保留 worker 运行状态。连接失败不应被 `200`、`202` 或 `dataChannel.send()` 掩盖。

### 4.2 Worker 状态机与容量计算

首版 Worker 状态机：`FREE -> RESERVED -> BUSY -> RESETTING -> FREE`；异常进入 `QUARANTINED`。独立 Worker 不代表独立 GPU，同一物理设备可承载多个 Worker（性能与内存需另测），一个 Worker 也可能使用多个计算设备。

- `worker.max_sessions` 是能力声明，**首版 Scope/Mock 强制为 1**，因为进程级重启是确定的会话清理兜底手段。未来只允许经独立会话 stop/reset 与隔离测试合格的适配器申明 `max_sessions > 1`。
- `available_slots = sum(max_sessions - reserved - active)`，仅计入健康且已 ready 的 Worker，负值按异常处理并告警。
- `effective_capacity = min(total_healthy_slots, SESSION_ACTIVE_LIMIT)`（若配置了正整数），否则等于 `total_healthy_slots`。进行分配时在锁内再次校验全局活动数与 worker 剩余槽位，避免并发竞争。
- N 张 GPU 不意味着 N 路实时；并发可运行数需由模型配置、单路 FPS 和实际资源共同验证。容量与实时达标能力必须分别报告。

首版 Session Manager 在 `asyncio.Lock` 内原子完成创建检查、幂等去重、选择健康 Worker 和预留槽位；不得使用多个 Uvicorn worker 进程共享这份进程内状态。Worker 进程重启前确认其所有关联会话已被关闭/清理；隔离失败实例不得分配给新请求。

### 4.3 心跳与清理

初始建议：`HEARTBEAT_INTERVAL_S=5`、`LEASE_TTL_S=20`、`SESSION_CONNECT_TIMEOUT_S=30`、`RESET_TIMEOUT_S=30`，全部可通过环境变量配置，数值仅为开发默认值。

定时扫描到租约过期时，触发 `CLOSING`。客户端 `pagehide` / `beforeunload` 最多做尽力通知，不作为唯一清理依据。清理顺序：停止接纳控制 → 关闭当前连接/停止生成 → 释放内部会话 → 验证状态清空 → 标记 `FREE`；任何失败进入 `QUARANTINED` 并记录原因。

**Scope 回收策略**：首先核验所锁定版本是否存在有文档且验证有效的会话停止/清空能力。如无可靠 reset，则 worker 进程由受控 supervisor 停止并重启，完成 `/health` 和 pipeline readiness 探测后再回到 `FREE`；重启失败保持隔离。不应以仅发送 `reset_cache=true` 证明彻底清除所有会话历史。

### 4.4 提示词更新的双阶段语义

首版采用与 Scope 兼容、最少侵入的双阶段协议：

1. `PUT /api/v1/sessions/{id}/prompt`：管理器检查状态、序号和内容，返回 `202 ACCEPTED`。该动作**仅登记允许发送**的提示词。
2. 浏览器在属于该房间的**已打开的** `parameters` WebRTC data channel 上发送 `{"prompts":[{"text":"...","weight":1.0}]}`。
3. 记录 `accepted_at`、`client_sent_at`，如果没有上游明确 ACK，不得将其记作“模型已采用”；画面变化需要额外人工或标注检验。

为控制复杂度，前端同一房间同一时刻只允许一条待投递的提示词。data channel 未打开时等待至超时并显示未投递；不盲目发送过时提示。提示词更新采用连续 `client_seq`，相同序号同内容重试幂等；同序号不同内容、过期序号均返回 `409 OUT_OF_ORDER`。

首个提示词不经过上述 PUT：由会话创建时存储的 `initial_prompt` 在 Scope offer 请求的 `initialParameters.prompts` 中由网关注入；前端不能覆盖其他房间的初始提示词。

## 5. API 契约（项目自定义 V1）

### 5.1 端点总览

| 方法 | 路径 | 成功 | 关键失败 |
|---|---|---|---|
| `POST` | `/api/v1/sessions` | `201`（幂等重放 `200`） | `400 / 409 / 429 / 503` |
| `GET` | `/api/v1/sessions` | `200` | `400` |
| `GET` | `/api/v1/capacity` | `200` | `503` |
| `GET` | `/api/v1/sessions/{session_id}` | `200` | `404` |
| `PUT` | `/api/v1/sessions/{session_id}/prompt` | `202` | `400 / 409 / 404` |
| `POST` | `/api/v1/sessions/{session_id}/heartbeat` | `200` | `404 / 409` |
| `POST` | `/api/v1/sessions/{session_id}/webrtc/offer` | `200` | `409 / 502 / 504` |
| `PATCH` | `/api/v1/sessions/{session_id}/webrtc/ice` | `204` | `409 / 502` |
| `DELETE` | `/api/v1/sessions/{session_id}` | `202 / 204` | `404` |
| `GET` | `/healthz`、`/readyz` | `200` | `503`（未就绪） |

完整字段、示例与校验以 `api/openapi.yaml` 为准。列表端点支持 `limit`、`cursor` 分页，不能直接把整个全量对象表暴露为无上限 JSON；MVP 在受控本地模式下使用，未来公开部署须增加身份认证与所有者权限。**以下示例中的 SDP 是占位符，不能直接用于连接**。

### 5.2 列表与动态容量

`GET /api/v1/capacity` 返回 `total_slots`、`active_sessions`、`reserved_sessions`、`available_slots`、`effective_limit`、`policy` 等抽象信息。示例：`{"total_slots":4,"active_sessions":2,"reserved_sessions":0,"available_slots":2,"effective_limit":4,"policy":"reject"}`。返回值是瞬时快照，真正分配以创建 API 的原子检查为准。`GET /api/v1/sessions?limit=20` 使用分页返回当前管理器可见的会话概况，不包含内部 Worker 地址。

### 5.3 创建会话

```http
POST /api/v1/sessions HTTP/1.1
Content-Type: application/json
Idempotency-Key: create-forest-001

{"label":"forest-room","initial_prompt":"A fox walks in a snowy forest.","seed":42}
```

```json
{
  "session_id": "sess_9a74",
  "state": "ALLOCATED",
  "lease_seconds": 20,
  "last_accepted_seq": 0,
  "webrtc": {"ice_servers": []}
}
```

- `201` 仅表示已成功预留实例，不代表视频已可播放；会话要在租约内完成协商。
- 同一 `Idempotency-Key` 和同一规范化请求体的重试返回同一会话（`200` 或 `201`，具体以 OpenAPI 契约统一；本计划固定使用 `200` 表示重放，`201` 表示首次）。同键不同内容返回 `409 IDEMPOTENCY_CONFLICT`。
- 没有空闲实例时返回 `429 NO_CAPACITY`，带可选 `Retry-After`，不偷偷无限排队。

### 5.4 更新提示词

```http
PUT /api/v1/sessions/sess_9a74/prompt HTTP/1.1
Content-Type: application/json

{"client_seq":1,"prompt":"The fox stops near a wooden cabin."}
```

```json
{
  "client_seq": 1,
  "status": "ACCEPTED",
  "delivery_required": "WEBRTC_DATA_CHANNEL"
}
```

客户端在 `parameters` data channel 打开后，再发送：

```json
{"prompts":[{"text":"The fox stops near a wooden cabin.","weight":1.0}]}
```

### 5.5 WebRTC offer/ICE 信令

```http
POST /api/v1/sessions/sess_9a74/webrtc/offer HTTP/1.1
Content-Type: application/json

{"type":"offer","sdp":"<browser-generated SDP>"}
```

后端把存储的初始提示词注入 Scope `initialParameters`，将 offer 送给绑定 worker 的原生 `/api/v1/webrtc/offer`。保存 `upstream_scope_session_id` 与本项目 `session_id` 的映射，返回 Scope 的 `{type:"answer",sdp:"..."}` 给浏览器；本项目不要把内部 Scope session ID 暴露给客户端。

```http
PATCH /api/v1/sessions/sess_9a74/webrtc/ice HTTP/1.1
Content-Type: application/json

{"candidates":[{"candidate":"candidate:...","sdpMid":"0","sdpMLineIndex":0}]}
```

转发至该 worker 的 `/api/v1/webrtc/offer/{upstream_scope_session_id}`。在 offer 完成前产生的 ICE candidates 在客户端本地暂存，拿到 answer 后再补送。为简化首版，也允许在测试模式中等待 ICE gathering 完成后一次性发送完整 offer，但**Mock 与真实后端必须一致**。不得伪造 SDP 或基于固定字符串判断媒体成功。

### 5.6 心跳、查询、关闭

```http
POST /api/v1/sessions/sess_9a74/heartbeat HTTP/1.1
Content-Type: application/json

{"client_media_state":"connected","received_frames":264}
```

`DELETE /api/v1/sessions/sess_9a74` 返回 `202 {"state":"CLOSING"}`，仅代表异步回收开始。客户端轮询 `GET /sessions/{id}`，直至 `CLOSED` 或 `FAILED`；重复关闭已经 `CLOSED` 的会话返回 `204`，不会重复释放资源。

### 5.7 统一错误格式

```json
{
  "error": {
    "code": "NO_CAPACITY",
    "message": "No idle video workers.",
    "request_id": "req_7c1e"
  }
}
```

错误码至少覆盖：`INVALID_REQUEST`、`SESSION_NOT_FOUND`、`INVALID_STATE`、`OUT_OF_ORDER`、`IDEMPOTENCY_CONFLICT`、`NO_CAPACITY`、`UPSTREAM_FAILURE`、`UPSTREAM_TIMEOUT`、`WORKER_UNAVAILABLE`。API 超时、上游不可用与资源已满不可混为一类。

## 6. WorkerAdapter 与真实后端对接

### 6.1 适配器接口

下面是**需自行实现的抽象协议**，不是 Scope 已有 SDK：

```python
from typing import Protocol

class WorkerAdapter(Protocol):
    async def capabilities(self) -> dict: ...  # prompt_update、media_protocol、safe_reset、max_sessions
    async def startup(self) -> None: ...
    async def health(self) -> bool: ...
    async def load_pipeline(self, pipeline_id: str, params: dict) -> None: ...
    async def exchange_offer(self, offer: dict, initial_prompt: str) -> tuple[dict, str]: ...
    async def add_ice(self, upstream_session_id: str, candidates: list[dict]) -> None: ...
    async def stop_and_reset(self, upstream_session_id: str | None) -> bool: ...
```

`exchange_offer` 返回 `(answer, upstream_scope_session_id)`。Mock 和 Scope 两种实现遵循该契约；支持的能力由 `capabilities()` 声明，而不是靠模型名称判断。更新提示词在 MVP 中由浏览器 data channel 完成，管理器仅作**本项客户端意图的登记**；若要实现跨客户端不可绕过的强制校验，需要后续引入服务端控制通道或 WebRTC 终止代理，不能将当前接口宣称为安全授权边界。

### 6.2 Scope 适配器启动流程（版本核验后执行）

1. 克隆官方 Scope 仓库、记录 commit，按官方 Quick Start 安装依赖；运行 `uv run daydream-scope --host 127.0.0.1 --port <port> -N`。`<port>` 是部署占位符，由配置或启动脚本填充。
2. 通过 `GET /health` 验证 HTTP 服务；用 `POST /api/v1/pipeline/load` 请求 `{"pipeline_ids":["longlive"]}`，或设置 Scope 支持的 `PIPELINE=longlive` 进行预热。
3. 轮询 `GET /api/v1/pipeline/status` 直至 `status == "loaded"`；`loading` 等待，`error` 报错。若选 MemFlow，把 `pipeline_ids` 改为 `memflow` 并按其文档配置。
4. 检查 `/api/v1/webrtc/ice-servers`、offer 与 ICE 的真实响应字段，特别是 `sessionId` 命名；记录到适配器兼容测试中，避免靠猜测实现。
5. 用官方最小浏览器示例直接连接 Scope，验证首帧与 data channel 的 `prompts` 更新；再接入自定义网关。
6. 测试主动关闭后是否释放生成状态。若缺少可靠原生 reset，则采用受控终止 / 重启该 worker 进程的方案；进程重新预热完成前不得标记 `FREE`。

**注意**：多 Scope 实例的 GPU 与端口隔离取决于运行环境；启动器不得把所有实例无意间装在同一设备而后声称完成“多设备扩容”。Scope 文档的默认端口、公开 STUN 与可选 TURN 配置必须审查，不能默认适用于所有网络。

### 6.3 Mock 适配器实现要求

- 每个 Mock Worker 使用 aiortc 提供真实 WebRTC offer/answer、ICE、`parameters` data channel 与视频 track。
- 视频 track 用不同房间标识、颜色/水印文字、帧序号和单调时间生成，便于检测串流和卡顿。
- 收到 `prompts` 消息后更新当前绘制文本或主题，使“提示已发送”和“画面已变化”可被区分测试。
- 提供可配置 `FIRST_FRAME_DELAY_MS`、`FRAME_JITTER_MS`、`DROP_OUTPUT_AFTER_S`、`FAIL_RESET` 等故障注入参数。
- Mock 的吞吐和帧率只能证明媒体/业务实现正确，不代表生成模型的实际 GPU 性能。

## 7. 浏览器客户端行为（动态数量）

1. 进入页面后获取 `/api/v1/capacity` 与部署能力信息；根据会话列表动态渲染 0..N 个 `RoomCard`，无固定 A/B 元素。
2. 用户每次点击“新建”时调用 `POST /sessions`，获得独立 `session_id` 与短期租约。资源不足则根据 `429 NO_CAPACITY` 友好提示，不影响已有房间。
3. 每个 RoomCard 独立维护 `RTCPeerConnection`、`parameters` data channel、视频元素、心跳定时与事件记录。不得复用另一个房间的 peer、upstream session ID 或 prompt 序号。
4. 创建有序 `parameters` DataChannel；添加 `recvonly` 视频 transceiver；生成 SDP offer，经本项目接口交换 answer。收到 answer 后正确转发缓存的 ICE candidates；`getStats()` 和 `requestVideoFrameCallback` 用于收帧、解码测量。
5. 发送新 prompt 时，先登记业务意图，再在**该房间已打开的** data channel 上发送。若没有服务端明确 ACK，只记录客户端已发送，不宣称后端已应用。控制面无法阻止绕过该登记直接发送 data channel 的客户端；仅限受控原型，强鉴权另做。
6. 关闭窗口卡片时仅关闭对应 PeerConnection，尽力发送 `DELETE`；最终清理由服务端租约超时兜底。刷新页面后不承诺恢复视频历史。
7. UI 依据 `/api/v1/capacity` 展示健康可用槽位、活动数和是否允许创建；容量信息是提示，服务端创建请求仍做原子检查。
8. 视频和指令按纯文本安全渲染，受控配置 API Origin，禁止客户端直接指定任意 Worker URL。

## 8. 推荐仓库结构与配置

```text
video-session-service/
├── README.md
├── AGENTS.md                      # Codex 交付约束
├── docs/implementation_spec.md
├── docs/compatibility.md         # 已锁定 Scope / 模型版本与能力探测记录
├── api/openapi.yaml
├── configs/example.env
├── configs/workers.example.yaml   # 可新增任意数量 Worker 项
├── services/session_api/
│   ├── main.py
│   ├── schemas.py
│   ├── state.py                    # 状态机
│   ├── registry.py                 # WorkerRegistry
│   ├── scheduler.py                # AdmissionPolicy / Allocator
│   ├── manager.py
│   └── adapters/{base,mock,scope}.py
├── services/mock_worker/          # aiortc WebRTC 测试后端
├── web/                            # Vite + TS，RoomCard 动态列表
├── scripts/{dev_mock,start_scope_workers,smoke_test,test_scenarios,export_results}.sh
├── tests/{test_capacity,test_state_machine,test_signaling,test_e2e}.py
└── results/README.md
```

### 8.1 环境变量：无个人环境/设备硬编码

```dotenv
BACKEND_KIND=mock
SESSION_API_HOST=127.0.0.1
SESSION_API_PORT=8080
WORKER_CONFIG_PATH=configs/workers.yaml
MOCK_WORKER_COUNT=2               # 示例测试规模，不是系统房间上限
SESSION_ACTIVE_LIMIT=             # 留空=不设置业务上限，仅受健康 Worker 槽位约束
ADMISSION_POLICY=reject            # 未来可扩展 queue；MVP 只实现 reject
SCHEDULER_POLICY=first_available   # 策略类可替换
HEARTBEAT_INTERVAL_S=5
LEASE_TTL_S=20
SESSION_CONNECT_TIMEOUT_S=30
RESET_TIMEOUT_S=30
LOG_FORMAT=jsonl
CORS_ALLOWED_ORIGINS=http://localhost:5173
RTC_ICE_SERVERS_JSON=[]
SCOPE_PIPELINE=longlive
```

`SESSION_ACTIVE_LIMIT` 为空必须按 `None` 解析，不可错误地当作 0。示例中 `MOCK_WORKER_COUNT=2` 仅用于快速演示；改为 1、3、4 或其他可承载值时，服务逻辑与前端无需改代码。`MOCK_WORKER_COUNT` 在 Mock 自动生成 Worker 列表时有效；`WORKER_CONFIG_PATH` 在显式 Worker 清单部署时优先。

### 8.2 Worker 注册表示例

以下 YAML 只是**单条示例记录**，项目应支持数组包含任意数量的不同实例；设备和地址由部署工具填写。`max_sessions=1` 是首版适配器的隔离能力限制，不是所有模型的永久限制。

```yaml
schema_version: 1
workers:
  - id: video-worker-01
    backend: scope
    endpoint: http://127.0.0.1:8101
    pipeline_id: longlive
    max_sessions: 1
    launch_mode: managed  # managed / external
    device_affinity: null # 由部署环境决定，不写死设备编号
    tags: {pool: default}
```

### 8.3 配置/扩容行为约定

- 新增 Worker：在注册表添加一条具有唯一 ID 的配置，重启管理服务或未来使用显式注册接口；管理器做健康检查并重新计算容量。不许在代码中添加新的 `if room_count == 2` 分支。
- 删除 Worker：先进入 `DRAINING` 状态，停止新分配；等待会话结束或按明示策略清理后移除。首版可通过配置变更 + 受控重启实现，不宣称在线热扩缩容。
- 切换模型：设置 `pipeline_id` / `backend`，验证适配器支持的能力，更新兼容记录；不能假定不同模型具有相同分辨率、提示更新或 reset 行为。
- 增加吞吐：优先扩展 Worker 池和测量实际可用能力；若未来一个 Worker 支持多个并发会话，必须验证隔离和 reset 安全后提升 `max_sessions`。
- 缓存、模型文件、设备绑定、端口、外部 ICE 服务器及密钥均由部署配置管理；真实 `.env` 不提交仓库。

## 9. 实施顺序（Codex 按此执行）

### 阶段 A：冻结契约与可配置本地骨架

- 建立仓库结构、OpenAPI 模型与配置加载；生成 `README.md`、运行脚本与测试命令。
- 先实现状态机及原子 worker 池，并通过容量/重复创建/关闭单元测试。
- 同步实现 Mock WebRTC worker，提供真实帧与 data channel；让浏览器收到第一帧。
- **完成门槛**：`BACKEND_KIND=mock` 下无需 GPU，一条命令启动并动态创建多个独立房间；相同测试在 `MOCK_WORKER_COUNT=1,2,4`（按测试环境资源可调整）下运行。

### 阶段 B：完整业务生命周期

- 接入 offer/answer、Trickle ICE、prompt 两阶段更新、心跳和异步关闭。
- 添加并发创建、断连、过载、重置失败测试；将不可恢复 worker 置入隔离态。
- **完成门槛**：所有 Mock 集成测试稳定通过，日志可按 `session_id` 关联。

### 阶段 C：真实模型适配

- 按 Scope 文档固定版本和模型，验证单 worker 的模型加载、视频输出、动态提示词。
- 将适配器接入 API，完成一个真实会话的创建与回收。
- 按配置增加 Worker，至少进行两路独立运行试验；再选择适合硬件的更高档位验证扩展，失败则记录真实限制。
- **完成门槛**：真实单路端到端流可见；至少两路并发（资源允许时）无状态串用；实际达到的最大档位来自实测。

### 阶段 D：实验与交付

- 用固定提示词和时序完成实验；保留原始 JSONL、配置与结果表。
- 生成图表、自动化测试报告、演示说明；核验无硬编码环境秘密。
- **完成门槛**：可由文档中的命令在相同条件复现功能验证，性能结论与实际测量相一致。

**Codex 执行约束**：每一阶段先实际运行测试，再进入下一阶段；发现第三方不提供某个 API 时先查看源码/官方文档并在适配层实现替代，禁止伪造成功响应。无 GPU 时先完成 Mock 模式，不应把模型无法访问当成阻塞所有进展的理由。

## 10. 运行与部署指导（需要 Codex 产出并验证的命令）

### 10.1 Mock 模式

预期 README 提供以下可直接复制的入口；若实现使用不同工具，需同步更新命令、脚本和 CI：

```bash
cp configs/example.env .env
# 按配置启动 Mock Workers、Session API 和网页服务（通过脚本管理进程）
bash scripts/dev_mock.sh
# 另一个终端执行自动化检查
bash scripts/smoke_test.sh
pytest -q
```

脚本负责打印服务监听地址、PID 或关闭方法。`smoke_test.sh` 读取或查询可用容量 N，验证：服务健康、创建/查询/列出、容量查询、N 次创建成功、第 N+1 次在 reject 策略下满载拒绝、多个房间分别收帧、关闭后回收。小规模 CI 可显式设置 `MOCK_WORKER_COUNT=2`。

### 10.2 真实 Scope 模式（示意，实际由固定版本生成可执行脚本）

```bash
# 首先按 Scope 官方说明安装；以下命令在 Scope 仓库目录执行
uv run download_models --pipeline longlive
uv run daydream-scope --host 127.0.0.1 --port 8101 -N
# 如配置了其他 Worker，启动器应依 workers.yaml 逐条启动/接入，不在脚本中硬编码第二个端口
# 启动前验证两实例实际设备分配和各自 ready 状态
```

Scope 加载检查示例（单 worker）：

```bash
curl -fsS http://127.0.0.1:8101/health
curl -fsS -X POST http://127.0.0.1:8101/api/v1/pipeline/load \
  -H 'Content-Type: application/json' \
  -d '{"pipeline_ids":["longlive"]}'
curl -fsS http://127.0.0.1:8101/api/v1/pipeline/status
```

注意：`pipeline/load` 异步，最后一个命令需要由启动器轮询至 `loaded`；如使用 `PIPELINE=longlive` 自动预热则不要与手动加载竞争。`start_scope_workers.sh` 必须有超时、错误退出、日志和进程回收策略；本文不能替代对设备驱动、模型下载权限和网络策略的现场检查。

## 11. 观测与实验方法

### 11.1 统一日志字段

每条 JSONL 至少含：`timestamp_utc`、`monotonic_ms`（同一进程内计时）、`event`、`request_id`、`session_id`、`worker_id`、`backend_kind`、`state_before`、`state_after`、`error_code`。浏览器另存 `client_session_id`、`ice_state`、`peer_state`、`first_decoded_frame_ms`、`frames_received` 与 prompt 时间点。

跨不同机器**不可直接相减单调时钟**；端到端指标以同一浏览器时钟计量。真实模型内部采样需独立标明采集位置。

### 11.2 必须区分的指标

| 指标 | 定义 | 常见误读 |
|---|---|---|
| HTTP 控制 RTT | 客户端发送 API 请求至收到响应 | 不代表视频就绪 |
| 首视频帧延迟 | 从选定的 `create`/`connect` 起点到客户端成功解码/展示首个有效帧 | 收到 SDP answer 不等于首帧 |
| 控制消息投递耗时 | HTTP 接纳到客户端 data channel `send` 结束 | 不代表 worker 采用新指令 |
| 提示生效延迟 | 用户提交新指令到画面首次符合指令 | 需要人工标注或可信画面标记 |
| 生成帧率 | 后端生成并完成解码/编码的新帧吞吐 | 不应把播放器复制帧算进来 |
| 接收帧率 | WebRTC 客户端实际收到/解码的新帧 | 不等于模型吞吐 |
| 回收时延 | 关闭触发到 worker 健康可复用 | `DELETE 202` 不代表释放完成 |
| 拒绝率 | 被拒绝会话创建数 / 全部创建尝试数 | 必须同时报告请求总量 |

### 11.3 实验矩阵（参数化 N，而非固定两间）

| ID | 操作/故障 | 判断与证据 |
|---|---|---|
| E01 | 单房间运行并更新提示 | 完整媒体链路，画面变化与信令分开记录 |
| E02 | 至少 2 个房间同时运行且互相更新 | 内容、client_seq、会话状态与历史不串用；N 可配置 |
| E03 | 配置容量为 N，创建 N 个后尝试 N+1 个 | 默认策略返回 `429 NO_CAPACITY`，已运行会话不被抢占 |
| E04 | 同一幂等键重复创建及冲突内容 | 重试不占额外槽位；冲突 `409` |
| E05 | 重复/过时 prompt 序号 | 同序号同内容幂等，旧序号或冲突 `409`（管理层登记语义） |
| E06 | 主动关闭会话后再次创建 | 只有 reset/进程重启验证后才复用 |
| E07 | 模拟浏览器失联或心跳停发 | 租约超时触发回收；其他房间继续运行 |
| E08 | 让 Worker stop/reset 失败 | `QUARANTINED` 不进入可用池；容量自动下降 |
| E09 | ICE 失败，HTTP 正常而视频未收到 | UI 和日志清晰区别控制面与媒体面状态 |
| E10 | 改变 `MOCK_WORKER_COUNT` 为 1、2、4 | 不修改应用代码、UI 或接口契约，行为与容量同步变化 |
| E11 | 在可用资源内对真实后端测并发档位 1、2、4… | 逐路首帧延迟、收帧率、失败率；固定配置并记录拓扑 |
| E12 | 增加/移除 Worker 或切换 `backend_kind` | 已部署配置可重现，优雅退出/受控重启后不遗留旧状态 |

真实实验使用相同分辨率、提示词集合、任务时长及预热条件。每组尽量至少三次独立运行，保存原始数据、失败样本、汇总统计和版本快照。Mock 延迟/帧率只用于验证软件管线，不冒充真实模型推理性能。实验选择的 N 仅代表该次条件下容量，不承诺系统永久上限。

## 12. 验收清单

- [ ] Mock 模式无需 GPU，可调整 `MOCK_WORKER_COUNT`，网页动态增删任意不超出容量的房间，且至少两个同时收到独立视频。
- [ ] 未写死直播间总数、设备数量、worker ID、Scope 私有 session ID 或端口；业务上限可选，动态容量接口与实际分配一致。
- [ ] Worker 注册表支持多条配置与健康检查；拒绝策略在 N+1 请求上正确生效，原有房间不受影响。
- [ ] Prompt 更新只作用于对应会话，HTTP 202 / data channel 发送与视频实际变化的语义分别记录。
- [ ] 会话的创建、查询/列出、容量、信令、心跳、结束接口与 OpenAPI 一致。
- [ ] 创建竞争不会导致同一槽位被重复分配；幂等重试不会重复占用资源。
- [ ] 失联、上游失败、终止与 reset 失败均能进入正确状态；隔离 Worker 不会错误复用。
- [ ] 真实 Scope 至少完成一条端到端视频；更多会话作为配置驱动的并发实验，而非预设“两个即上限”。
- [ ] 日志能关联房间、Worker、客户端媒体事件；不使用 Mock 的帧率替代真实模型速度。
- [ ] README 含环境安装、配置、启动与停止、排错、测试及授权边界；没有硬编码敏感信息。

## 13. 已知风险、降级与授权边界

1. **模型/Scope 版本不兼容**：先固定版本并做单路 smoke test；备选 `memflow` 仅在验证同一 adapter 合约后启用。
2. **缺少可靠的 stop/reset**：使用进程重启确保历史清空，牺牲回收速度；失败时 worker 必须隔离。
3. **HTTP 可达但 WebRTC 失败**：检查 ICE 候选与网络策略；同一可信网络内先验证直连，必要时采用经批准的 STUN/TURN 配置。
4. **真实吞吐不足**：降低分辨率或测试时长并说明条件；不得承诺达到直播平台的帧率，也不将模型速度问题伪装成网络服务故障。
5. **进程和会话状态不一致**：单管理进程，启动时检查遗留子进程；不在首版引入分布式状态一致性。
6. **第三方服务与资产风险**：核验模型权重、代码许可证、媒体内容授权和运行时外部连接；禁止上传私有数据或私自暴露服务。

## 14. 参考资料与核对清单

- [1] Daydream Scope — 官方仓库：https://github.com/daydreamlive/scope
- [2] Scope Server API（健康探测、pipeline、WebRTC）：https://github.com/daydreamlive/scope/blob/main/docs/server.md
- [3] Scope Pipeline Load（请求体与状态查询）：https://github.com/daydreamlive/scope/blob/main/docs/api/load.md
- [4] Scope Runtime Parameters（`parameters` data channel、prompt 格式）：https://github.com/daydreamlive/scope/blob/main/docs/api/parameters.md
- [5] Scope Receive Video（浏览器 WebRTC 示例）：https://github.com/daydreamlive/scope/blob/main/docs/api/receive.md
- [6] LongLive 1.0 官方实现：https://github.com/NVlabs/LongLive/tree/main/LongLive1.0
- [7] MemFlow 官方实现：https://github.com/KlingAIResearch/MemFlow
- [8] MDN WebRTC 信令说明：https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API/Signaling_and_video_calling

**外部资料核对日期：2026-11-24。** 实现时以实际锁定版本的源码及接口响应为最终依据。本文以公开文档、既有方案及项目设计原则编写，不包含任何已完成部署的宣称。

# 资料已交、session/AT 超时：同一邮箱补 token

## 目标

Job 8 这类失败：资料页已提交，OpenAI 侧账号多半已建，随后主动打开 `https://chatgpt.com/` 读 `/api/auth/session` 超时，任务标 failed、邮箱标 failed。现成任务「重试」会开**完整新注册并换邮箱**，把已建号废掉。

要做的是：识别「号可能已建、只缺 AT」，用**同一邮箱**补登录拿 token 并入库，不再领新邮箱。点「补 token」在**原任务内**继续，不新建任务。

## 不做

- 不改 Docker / UFW / Tailscale / 邮箱池 pickup。
- 不把「补 token」做成再走一遍 Cloak/Roxy 注册页。
- 不把个人号 cookie（如 `shunnketu@gmail.com`）写入账号表。
- 不在本方案里修出口 / Cloudflare 对协议栈的拦截（补 token 走已有协议查活，不复用那次 `Page.goto`）。任务成败不用来判定代理是否有问题。
- 不自动对历史失败任务发起真实登录；Job 8 等存量只改按钮语义，仍需人点。
- 不改 Codex 补跑、换邮箱完整注册的子任务模型。
- 批准前不写测试、不改代码。T01–T04 已于 2026-09-17 按当时正文实施；T05–T06 须再批准后才改。

## 现场依据

- Job 8 日志：`注册日志/cc31e7f5-225f-4743-8a29-ced12a68ca0c.log`。邮箱 `cirque82vestal@icloud.com`。登录/OTP/资料过了；`_fetch_chatgpt_session` 15s 未跳转后 `_safe_get("https://chatgpt.com/")`，35s `domcontentloaded` 超时。错误：`等待 /api/auth/session accessToken 超时`。账号表无该邮箱。邮箱池 `failed`。
- Job 8 界面无「补 token」：`get_retry_info(8)` → `retryable=False`，`retry_reason=后续重试任务 #9 已成功`。Job 9 是旧「重试」换邮箱完整注册（`leis-lupus85@icloud.com`，`job_type=registration`，success）。启发式本可命中 Job 8，被「任意后续成功子任务」短路。
- Cloak：`core/cloakbrowser_registration.py` 在 `_complete_profile_page` 成功后置 `create_acknowledged=True`，然后才读 session；失败时 `release_email(..., status="failed" if create_acknowledged else "available")`，**不写账号表**。
- 现成重试：`get_retry_info` / `retry_job`（`core/registration_service.py`）。无 `account_id` 且未命中补 token → `retry_action=registration`（换邮箱完整注册）。有 AT → 只补 Codex。T02 落地的 `session_recover` 会 `create_retry_job` 建新行（Job 12 即此）。
- UI 确认文案：`创建新的完整注册任务`（`webui/templates/index.html`）；`session_recover` 已改为「用同一邮箱补 accessToken，不换邮箱」，但仍会新建任务号。
- 查活已能无 AT：`check_account_liveness` 无本地 AT 时走 CSRF → Signin → 邮箱 OTP → callback → session（`core/account_liveness.py`）。入口是账号表行，Job 8 没有这行，界面查活点不了。
- `insert_account` 的 `access_token` 可为 `""`；WebUI 已有 `has_access_token`。
- Job 12 补 token 失败：协议预检对 `chatgpt.com` 403 后会话熔断 900s，再 curl (28) 30s 0 bytes。同一代理上 Job 11 Cloak 曾打开登录页。任务成败不代表代理故障。

## 选定方案

**失败时若已确认资料提交（`create_acknowledged`），先落一条无 AT 账号；「补 token」在原任务内用同一邮箱查活。**

依据：查活链路已存在。缺的是账号行、按钮不被换邮箱成功子任务挡住、以及点按钮时复用原 `job id` / 日志。

### 判定「已建号、缺 AT」

**新失败（注册进程内，权威）：** 各浏览器注册入口已有的 `create_acknowledged`。失败返回增加 `account_created: bool`（即该标志）。`_run_one_job` 见其为真且无 `account_id` 时，插入无 AT 账号，把 `job.account_id` / `job.email` 写上，邮箱保持 `failed`（已占用，不回池）。

**存量失败（无标志，启发式，仅分类重试，不自动跑）：** 满足下面任一即可：

1. 任务 `failed` / `stopped`，有邮箱，无账号行（或账号行 AT 为空）；错误含 `等待 /api/auth/session accessToken 超时`；邮箱池该地址当前为 `failed`（Cloak/Roxy 仅在 `create_acknowledged` 时标 failed）。池状态为 `available` 且日志没有拿到 AT，视为资料未交，仍走完整注册。
2. 任务日志出现 `已拿到 accessToken`：号已建、只是没入库（含手动停止后邮箱被收回 `available`）。点「补 token」在原任务内跑，落无 AT 账号，邮箱改回 `failed`，不新建任务、不换邮箱。

Job 8 走第 1 条。Job 12（`hotbeds-names-5e@icloud.com`，停在拿到 AT 后的流量统计）走第 2 条。启发式不准时：补 token 若 OTP 后仍进资料页，查活已有「疑似不是完整已注册账号」失败，不领新邮箱。

### 按钮：换邮箱成功子任务不得挡住缺 AT 的原任务

`get_successful_retry_for_job` 按 `root_job_id` 找任意 success 子任务。Job 9 换了邮箱，不能表示 Job 8 的 `cirque82vestal@icloud.com` 已补到 AT。

**规则：** 命中「已建缺 AT」时，忽略「后续换邮箱完整注册成功」对 `retryable` 的屏蔽，Job 8 仍出「补 token」。同一邮箱已有 AT（原任务已 success，或账号行已有 token）则不出该按钮。Codex / 换邮箱注册的屏蔽逻辑不在本方案改。

### 重试三分

- 无账号，且不是「已建缺 AT」→ `retry_action=registration`，按钮「重试」：现成，新完整注册、换邮箱、**仍建子任务**。
- 已建缺 AT（新失败落库，或存量启发式）→ `retry_action=session_recover`，按钮「补 token」：**原任务内**同一邮箱查活拿 AT，写入已有/新建账号行，**不新建 job 行**。
- 有 AT，Codex 未成功 → `retry_action=codex`，按钮「补跑 Codex」：现成，不变，**仍可建子任务**。

`session_recover` 成功后再按现成规则决定能否补 Codex（有 AT 且 Codex 未成功才出现）。

### 执行（补 token）

- 不新建 `session_recover` 任务行。`retry_job` 在 `action=session_recover` 时复用原 `id`、`log_file`、邮箱；必要时先插无 AT 账号并写回原任务。
- 原任务 `job_type` 保持注册当时的值（存量仍是 `registration`）。`retry_action=session_recover` 只给 API/UI 分类。
- 原任务改为 `running`，日志追加，worker 仍调 `check_account_liveness`（无 AT 分支）。代理沿用查活现成 `resolve_plan_check_route`，不复用那次已超时的 Cloak 页。任务成败不用于判定代理。
- 成功：写 AT，**原任务** `success`，邮箱保持已用。
- 失败：账号行保留、AT 仍空，**原任务**回到 `failed`，可再点「补 token」；**禁止**回退成换邮箱注册。
- 查活判定废号：账号 `deactivated`，按钮按现成废号逻辑禁用。
- 原任务已 `running` / `stopping` 时拒绝再点；失败后可再点。不自动跑。
- 已存在的历史子任务（Job 9、Job 12）不删、不改邮箱。

### 未来任务要不要同任务内自动补

不做同任务**自动**查活。失败先落无 AT 账号，等人点「补 token」。点了之后在原任务内跑，不是自动、也不是新建任务。

### 接线

- `core/cloakbrowser_registration.py`、`core/roxy_registration.py`、`core/browser_use_registration.py`：失败 JSON 增加 `account_created`（T02 已做）。
- `core/registration_service.py`：`_run_one_job` 落无 AT 账号（T02 已做）；`get_retry_info` 在缺 AT 时不被换邮箱成功子任务挡住（T05）；`retry_job` 的 `session_recover` 复用原任务，不再 `create_retry_job`（T06）。
- `core/db.py`：`insert_account` 允许空 AT（已允许）。`create_retry_job` 可继续服务 Codex / 完整注册；补 token 不再走它。
- `webui/templates/index.html`（及 legacy）：`session_recover` 文案为补 token、不换邮箱、不暗示新建任务号。
- 测试：分类、落库、存量启发式、Job 8 有换邮箱成功子任务仍出补 token、`retry_job` 不新增 job id。不跑真实 ChatGPT。

## 未知项

**查活出口能否打通 ChatGPT（Job 8 当时是 VN 代理 `100.102.89.105:55223`）。**

- 检查：实现后对 Job 8 点「补 token」，看原任务日志是否拿到 AT。
- 成功：账号有 AT，原任务 success。
- 失败：保留无 AT 账号，原任务 failed，可再试；不改为完整注册。出口/Cloudflare 问题不在本方案范围，也不据此判定代理。

## 计划

不写工期。明确批准本文件后才实施对应 TASK；「继续」不算批准。每 TASK 验收后独立 commit。已完成的 T01–T04 不重做。T02 曾把补 token 做成新建子任务，由 T06 替换。

### 进度

| TASK | 状态 |
|---|---|
| T01 失败分类与重试契约测试 | ✅ 已验收 |
| T02 注册失败落无 AT 账号 + session_recover | ✅ 已验收（子任务模型；T06 替换执行方式） |
| T03 UI 文案 | ✅ 已验收 |
| T04 存量启发式（含 Job 8 按钮语义） | ✅ 已验收（仍被成功子任务短路，见 T05） |
| T05 缺 AT 不被换邮箱成功子任务挡住 | ✅ 已验收 |
| T06 补 token 在原任务内继续 | ✅ 已验收 |

### T01 失败分类与重试契约测试

- **方案来源：** 重试三分；存量启发式三条。
- **目标：** 先用测试钉住：无账号普通失败 → registration；`account_created` 或存量启发式 → session_recover；有 AT → 仍 Codex；session_recover 失败不得变 registration。
- **改：** `tests/test_registration_session_recover.py`（新）。不改生产代码（RED）。
- **交付物：** 失败测试文件。
- **验收：** 针对未实现分类的用例 RED；不访问外网。证据：`13e2ba5` 提交后 4 个分类用例 FAIL（`codex`/`registration` ≠ `session_recover`）。

### T02 注册失败落无 AT 账号 + session_recover

- **方案来源：** `account_created` 落库；`retry_action=session_recover` 走查活。
- **目标：** Cloak/Roxy/Browser Use 失败返回 `account_created`；`_run_one_job` 插入空 AT 账号；`retry_job` 创建 `session_recover` 子任务并调用查活。
- **改：** `core/cloakbrowser_registration.py`、`core/roxy_registration.py`、`core/browser_use_registration.py`、`core/registration_service.py`、`core/db.py`（仅 job_type）。
- **交付物：** 上述实现；T01 转 GREEN。
- **验收：** 单测 GREEN；不跑真实注册。查活调用可用 stub。证据：`tests.test_registration_session_recover` 10 passed。
- **后续：** 新建子任务由 T06 改为原任务内执行。

### T03 UI 文案

- **方案来源：** 按钮/确认不得再写「创建新的完整注册任务」。
- **改：** `webui/templates/index.html`；若 legacy 仍渲染重试按钮则同步 `index_legacy.html`。
- **交付物：** `retry_action=session_recover` 时文案为补 token、不换邮箱。
- **验收：** 模板字符串断言或只读 grep：`session_recover` 分支无「完整注册」。证据：`SessionRecoverUiCopyTests` 通过。

### T04 存量启发式

- **方案来源：** 无 `account_created` 的历史任务（Job 8）。
- **目标：** `get_retry_info` 用邮箱池 `failed` + 超时文案分类；点补 token 时先插无 AT 账号再查活。
- **改：** `core/registration_service.py`（及 T01 覆盖存量用例）。
- **交付物：** Job 8 这类记录按钮变为「补 token」。
- **验收：** 单测模拟 job+email_pool；不自动对 Job 8 发真实 OTP。证据：`test_stock_timeout_with_failed_pool_email_retries_session_recover`、`test_stock_retry_inserts_placeholder_account_then_recovers` 通过。
- **后续：** 有换邮箱成功子任务时按钮仍被挡，见 T05。

### T05 缺 AT 不被换邮箱成功子任务挡住

- **方案来源：** Job 8 现场 `retryable=False` / `后续重试任务 #9 已成功`；Job 9 邮箱不是 Job 8。
- **目标：** 命中 session_recover 的任务，即使同链有换邮箱的 `registration` success 子任务，仍 `retryable=True`、`retry_action=session_recover`。
- **改：** `core/registration_service.py` 的 `get_retry_info`；测试覆盖「父任务缺 AT + 子任务换邮箱成功」。
- **交付物：** Job 8 出「补 token」按钮。
- **验收：** 单测构造 job 8 形态（超时文案、池 `failed`、无 AT）+ 不同邮箱 success 子任务 → 仍 session_recover。不访问外网、不对 Job 8 发 OTP。证据：`test_stock_timeout_not_blocked_by_other_email_registration_success`；现场 `get_retry_info(8)` → `retryable=True` / `session_recover`。提交 `2419f12`。

### T06 补 token 在原任务内继续

- **方案来源：** 「仅仅是重新获取 token 希望在原任务内继续重试而不是新建一个任务」。
- **目标：** `retry_job(..., session_recover)` 不调用 `create_retry_job`；复用原 id / 日志；成功/失败都写回原任务。
- **改：** `core/registration_service.py` 的 `retry_job` / `_run_session_recover_job`；UI 确认/toast 不写「已创建重试任务 #N」；测试断言 job 列表条数不增加。
- **交付物：** 点 Job 8「补 token」后仍是任务 #8，日志追加在原文件。
- **验收：** 单测 stub 查活；`retry_job` 返回的 `job.id` 等于源 id；`created` 不为新行。Codex / 完整注册仍可建子任务。不跑真实 ChatGPT。证据：`tests.test_registration_session_recover` 11 passed。

## 授权与人工

- T01–T04：当时正文已批准并落地。
- T05–T06：改完本文后须再明确批准才写测试/代码。
- Job 8 真实补 token：T05–T06 之后你点按钮（会向该 icloud 发 OTP，在任务 #8 日志里追加）。
- 网络/Docker：不涉及。

## 开发者评分

- **对象：** 本文件方案+计划（含 T05–T06）。
- **初评：** 44。跨注册失败、账号表、重试、查活、UI；查活本身已存在。风险在「超时≠已建号」误分类，以及空 AT 账号被旧逻辑当成可补 Codex。
- **复评：** 36。契约收到 `account_created` 与邮箱池 `failed`；Codex / 换邮箱子任务与补 token 原任务内执行拆开；存量不自动跑。剩余是查活出口现场未知，以及历史子任务（Job 9/12）仍留在链上只作记录。

## 改动方向（已落实到正文）

1. 用 `create_acknowledged` / 邮箱 `failed`，不用单靠错误字符串。
2. 复用查活，不重开 Cloak 注册。
3. 有 AT 才走 Codex。
4. 同任务自动查活不做；人点「补 token」在原任务内跑。
5. 存量只改按钮，不自动登录。
6. 换邮箱成功的子任务不屏蔽原邮箱的「补 token」。
7. 任务成败不用于判定代理。

## 交接

T01–T06 已落地。Job 8 应显示「补 token」；点了会在任务 #8 日志追加，不新建任务。真实 OTP 仍须你点按钮。

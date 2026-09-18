# Cloak 内核版本：后台可配置

## 目标

在 WebUI 配置页「CloakBrowser」分组用**下拉框**钉死 Cloak Chromium 内核。选项为可用完整版本号，外加一项 `latest (当前最新号)`。保存后下次 Cloak 启动生效。现在 Pro 未钉版本会跟 `download/latest` 走，现场已从 146 → 150 → 151。

## 不做

- 不改入口、UFW、Tailscale、compose、端口。
- 不改代理池、注册驱动切换、Roxy OS 指纹。
- 不接 `CLOAKBROWSER_BINARY_PATH`（本地自编译 Chromium）。
- 不提供手填任意版本号（只要下拉；已保存但不在清单里的值仍保留为当前选项，避免被冲掉）。
- 不把 `CLOAKBROWSER_VERSION` 当本项目配置名（那是 cloakbrowser 包自己的环境变量）。
- 不在保存时远程校验/预下载；钉到未缓存版本时，由 cloakbrowser 首次启动自行下载。

## 相对上一稿的改动

上一稿是文本框填完整号，并写明「不拉版本清单、不做下拉」。按你的要求改为：

- `CLOAK_BROWSER_VERSION` 在后台是下拉，不是输入框。
- 选项 = 探测到的可用内核 + 第一项 `latest (版本号)`。
- 增加只读接口拉清单；打开配置页时拉一次。
- `CLOAK_RELEASE_CHANNEL` 仍保留（空/`stable`/`preview`），只影响选了 latest 时跟哪条通道；已选具体版本号时以版本为准。

## 现场依据

- 容器 `cloakbrowser==0.5.10`。`launch` / `launch_persistent_context` 已有 `browser_version`、`release_channel`。
- 包常量 `CHROMIUM_VERSION=146.0.7680.177.5`（免费捆绑）。现场 Pro：`151.0.7922.108.6`，路径 `/root/.cloakbrowser/chromium-151.0.7922.108.6-pro/chrome`。
- 钉版本正则：`^[0-9]+(?:\.[0-9]+){3,4}$`。只接受完整数字版本；`151` 非法。
- Pro latest：`GET https://cloakbrowser.dev/api/download/version` → `{"version":"151.0.7922.108.6"}`。preview 同接口 `?channel=preview` → `152.0.7977.82.1`。
- Pro 历史包：`GET https://cloakbrowser.dev/api/download/{version}`（要 License）。GitHub 上 `chromium-v*-pro` 标签只有校验和，没有平台包，不能当下载源，但标签号可当「曾发布过的 Pro 版本」。
- 免费历史包：GitHub `CloakHQ/cloakbrowser` releases，`chromium-v*` 且带当前平台资产（本机 `linux-arm64` → `cloakbrowser-linux-arm64.tar.gz`）。只看标签、不看资产会把没有 linux-arm64 包的号（现场：`146.0.7680.177.5`）标成「免费」可选，启动 404。免费 License 会丢掉版本钉、强制 latest。
- 本仓库 `build_cloak_driver` 未传 version/channel。配置页普通字段只有 text/number/textarea/bool，下拉要走现成 `config-ep-select`（与注册驱动相同）。
- Cloak 启动点两处，都走 `build_cloak_driver`：注册、Codex OAuth。

## 选定方案

**配置项仍是字符串；后台用下拉选。空字符串 = latest。非空 = 完整版本号，原样传给 cloakbrowser。选 latest 时启动必须把探测到的最新完整号传给 Cloak，不能留空让库回落到包内捆绑核（现场 linux-arm64 捆绑 `146.0.7680.177.3`）。**

来源：cloakbrowser 0.5.10 的 `launch(..., browser_version=, release_channel=)`；GitHub Releases + Pro version API 作选项来源；WebUI 已有 `config-ep-select`。

### 配置项

- `CLOAK_BROWSER_VERSION` 默认 `""`。空 = latest（后台保存仍为空）。非空必须是完整号。
- `CLOAK_RELEASE_CHANNEL` 默认 `""`。空或 `stable` = 稳定通道；`preview` = 预览。只在 latest 时有意义。后台用两项下拉：`stable`、`preview`（空按 stable 显示，保存仍允许空）。

WebUI：CloakBrowser 分组，放在 `CLOAK_LICENSE_KEY` 后面。保存走现成 `.env` 覆盖。

### 下拉选项

打开配置页时请求 `GET /api/cloak/chromium-versions`，失败不挡配置页。

清单合并去重后，**每个 Chromium 大版本只保留一项**（该大版本完整号最高的一条，例如 151 只留 `151.0.7922.108.6`，不列 `.4/.3/.2`）。再按版本号降序。

来源仍是：

1. Pro latest（有 License 时请求 version API；无 License 则跳过）。
2. GitHub releases：`tag_name` 形如 `chromium-v*`，去掉前缀和可选 `-pro` 后缀，得到完整号。**免费标签必须带当前平台资产** `cloakbrowser-<platform>.tar.gz`（本机 `linux-arm64`）才进下拉；没有该包的号不列。Pro 标签（`-pro`）本身没有平台包，不能当免费下载源；有 License 时只作 Pro 可选号。
3. 本机已缓存目录名（`~/.cloakbrowser/chromium-<ver>` / `chromium-<ver>-pro`）。
4. 包内捆绑号（`CHROMIUM_VERSION`）同样：当前平台下不到就不列。
5. 当前已保存的 `CLOAK_BROWSER_VERSION`（若不在清单里，仍插进去，避免下拉把旧钉弄丢）。**不可用的已保存钉标「不可用」**，不当正常可选项。

有 License 时：免费号不要标成可跑；Pro 走对方下载接口，不走这个 GitHub 免费 404 路径。无 License 时：只列当前平台有免费包或已缓存免费核的号。

第一项固定：

- value = `""`
- 文案 = `latest (151.0.7922.108.6)`，括号内是当时探测到的**最新内核号**（Pro version API；失败则用清单里已知最高完整号，含 GitHub `-pro` 标签）。**不要**用「当前能跑的免费核」或包内捆绑 146 冒充 latest。完全探测不到号才只写 `latest`。

其余项：

- value = 完整版本号
- 文案 = 版本号；能区分时加 `Pro` / `免费` 标记（GitHub `-pro` 标签或本地 `-pro` 目录算 Pro）。当前平台没有对应包、或有 License 却只是免费号的已保存钉：文案加 `不可用`。

不把 preview latest 单独叫 latest。preview 号若出现在 GitHub/缓存里，作为普通版本可选；选 latest 再把通道设为 preview，才跟 preview 最新走。

配置页控件：复用 `config-ep-select`，不要原生 `<select>`。清单返回前先画「加载中…」；失败则只保留 `latest` + 当前已保存值。

### 启动接线

`build_cloak_driver`：

- 两项都 strip。非空版本号原样传入。
- 空版本（latest）：用清单探测到的最新完整号作为 `browser_version` 传入，不要省略该参数。探测失败再省略，让 cloakbrowser 自己处理。
- 通道：非空才传 `release_channel`。
- 启动日志带上实际传入的 version / channel（latest 记探测到的号，探测失败记 `latest`；通道空记 `stable`）。`CloakOpenResult.raw` 同步记下。

不写 `os.environ["CLOAKBROWSER_VERSION"]`。

### 文案（帮助）

- 内核版本：选 `latest (x.y.z)` 跟随当前最新（启动传入该号，不回落到捆绑 146）；选具体号则钉死，下次启动按该号下载/复用缓存。
- 发布通道：仅 latest 时生效。`preview` 才走预览通道。

## 交付物

- `config/cloakbrowser.py`：两项默认空，纳入 `apply_env_overrides`。
- `webui/config_editor.py`：CloakBrowser 分组两个字段。
- `webui/app.py`：`GET /api/cloak/chromium-versions`。
- `core/cloakbrowser_versions.py`（或同等模块）：拼清单，可 mock。
- `webui/templates/index.html`：Cloak 内核 / 通道下拉。
- `core/cloakbrowser_driver.py`：启动传参 + 日志。
- `README.md`：Cloak 配置示例补这两项。
- `tests/test_cloakbrowser_version.py`：空值不传、有值传入、清单合并/latest 文案、当前值不在清单时保留。

## 阶段 / TASK

批准后才改代码。每 TASK 验收后单独 commit。

### T01 配置项 + 版本清单接口

方案来源：本方案「配置项」「下拉选项」。

交付物：`config/cloakbrowser.py`、`webui/config_editor.py`、清单模块、`GET /api/cloak/chromium-versions`。

验收：接口 JSON 含 `latest`、`versions`（每项 `value`/`label`）；第一项 value 为空、label 含 `latest (` 和探测到的号；GitHub/Pro 失败时仍 200，versions 至少有 latest；已保存但不在远程清单的版本仍出现。GitHub 免费标签没有当前平台 `cloakbrowser-*.tar.gz` 的不进下拉；有 License 时免费号不标可跑，已保存不可用钉标「不可用」。不启动浏览器、不改入口。

### T02 配置页下拉

方案来源：本方案「下拉选项」。

交付物：`webui/templates/index.html`。

验收：CloakBrowser 分组「Cloak内核版本」是 `config-ep-select`，选项来自 T01 接口；选 latest 保存后 `.env` 该项为空；选完整号保存后 `.env` 为该号；通道为 stable/preview 下拉。不改其它分组。

### T03 启动传参

方案来源：本方案「启动接线」。

交付物：`core/cloakbrowser_driver.py`。

验收：mock launch：空配置传入探测到的最新号（如 `151.0.7922.108.6`）；探测失败才不含 `browser_version`；填了完整号则 kwargs 相等；`preview` 传入 `release_channel="preview"`。注册与 Codex OAuth 都只经 `build_cloak_driver`。

### T04 说明 + 测试

方案来源：本方案交付物。

交付物：`README.md` Cloak 段、`tests/test_cloakbrowser_version.py`。

验收：`uv run --with pytest pytest tests/test_cloakbrowser_version.py tests/test_config_defaults.py -q` 通过。不跑真实下载、不改容器网络。

## 验收依据（整功能）

1. 后台内核是下拉：`latest (当前号)` + 可用完整版本。
2. 选 latest 保存为空，启动传入探测到的最新完整号，不回落到捆绑 146。
3. 选具体号后启动传入该号。
4. 清单失败时配置页仍能保存 latest 或已有钉。
5. 入口/端口/代理池不变。

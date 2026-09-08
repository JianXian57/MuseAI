# MuseAI

MuseAI 是一个面向本地工作流的 AI 助手。

项目目前主要基于 ZCode 运行，GUI 尚未进行适配。

MuseAI 的核心目标不是让 AI 直接承担所有工作，而是把不同类型的职责放到最合适的层：

- **Main Agent**：理解用户意图、进行普通判断、选择并编排能力、组织最终交互。
- **Sub-Agent**：仅用于复杂、独立、值得单独委托的认知任务。
- **Tool / Program**：负责确定性、机械化执行。
- **Service / Common**：负责 Tool 下方可复用的确定性实现。
- **Query**：通用、只读、快速的信息访问层，用于高频检索、筛选、聚合和直接关系查询。
- **Skill**：保存可复用的方法、流程与交互规范。
- **Template**：保存稳定的人类可读输出骨架。
- **Data**：保存运行时状态、用户记录、日志和缓存。
- **CLI**：负责把命令行参数适配为公共 Tool 调用。
- **`muse.py`**：统一根 CLI、路由与生命周期日志入口。

核心原则：

> **人负责目标，AI 负责不确定性，程序负责确定性。**

进一步可以概括为：

> **能写死的，写成程序。能教会的，写成 Skill。Main 能轻松想明白的，让 Main 想。只有值得独立委托的智能工作，才做成 Sub-Agent。**

职责边界：

> **CLI 负责怎么调用，Tool 负责对外承诺，Service 负责真正实现，Query 负责高效读取，Main 负责选择与编排。**

---

## 设计原则

MuseAI 当前遵循以下原则：

1. 确定性业务逻辑优先放入 **Service / Tool / Program**。
2. **Tool** 负责稳定公共能力和 Tool Result，**Service** 负责内部实现，**CLI** 只做参数适配。
3. 高频只读信息访问可进入 **Query**，但 Query 永远不拥有写入权。
4. 固定、可复用的方法、流程和交互规范放入 **Skill**。
5. 简单的不确定性由 **Main Agent** 直接处理。
6. 只有任务复杂、独立，或确实需要上下文隔离时，才使用 **Sub-Agent**。
7. 用户数据、日志、密钥和运行状态与项目源码分离。
8. 公共 Tool 使用统一结构化 JSON，避免 Main 重复解析大量文本。
9. Main 正常运行时不直接调用内部 Service，也不绕过 Tool 修改业务 Data。
10. 项目结构应便于后续接入 GUI、本地模型、远程服务和自动化任务。
11. 运行环境不能在普通请求中被 Main 静默修改；依赖应通过 `requirements.txt` 明确声明。
12. Git 写操作属于开发行为，不能作为普通 MuseAI 运行流程的隐式步骤。

---

## 当前目录结构

```text
MuseAI/
│
├─ AGENTS.md
│
├─ .zcode/
│  ├─ agents/
│  │  ├─ analyst.md
│  │  ├─ reviewer.md
│  │  └─ visual.md
│  │
│  └─ skills/
│     ├─ reporter/
│     │  └─ SKILL.md
│     ├─ task-management/
│     │  └─ SKILL.md
│     ├─ daily-report/
│     │  └─ SKILL.md
│     └─ custom-function/
│        └─ SKILL.md
│
├─ tools/
│  ├─ common/
│  │  ├─ __init__.py
│  │  ├─ result.py
│  │  └─ time_service.py
│  │
│  ├─ log_ops/
│  │  ├─ log_tool.py
│  │  └─ log_cli.py
│  │
│  ├─ time_ops/
│  │  ├─ time_tool.py
│  │  └─ time_cli.py
│  │
│  ├─ task_ops/
│  │  ├─ __init__.py
│  │  ├─ task_service.py
│  │  ├─ task_read_service.py
│  │  ├─ daily_service.py
│  │  ├─ long_service.py
│  │  ├─ standing_service.py
│  │  ├─ daily_maintenance_service.py
│  │  ├─ task_errors.py
│  │  ├─ task_tool.py
│  │  └─ task_cli.py
│  │
│  ├─ report_ops/
│  │  ├─ __init__.py
│  │  ├─ daily_report_service.py
│  │  ├─ report_tool.py
│  │  └─ report_cli.py
│  │
│  ├─ init_ops/
│  │  ├─ __init__.py
│  │  ├─ daily_init_service.py
│  │  ├─ init_tool.py
│  │  └─ init_cli.py
│  │
│  ├─ query_ops/
│  │  ├─ __init__.py
│  │  ├─ task_query_service.py
│  │  ├─ query_errors.py
│  │  ├─ query_tool.py
│  │  └─ query_cli.py
│  │
│  ├─ function_ops/
│  │  ├─ __init__.py
│  │  ├─ custom_function_service.py
│  │  ├─ function_errors.py
│  │  ├─ function_tool.py
│  │  └─ function_cli.py
│  │
│  └─ balance.py
│
├─ config/
│  ├─ user.yaml
│  └─ manifest.yaml
│
├─ func/
│  ├─ .gitkeep
│  └─ example-function/
│     ├─ README.md
│     ├─ config/
│     │  └─ function.yaml
│     ├─ data/
│     │  └─ .gitkeep
│     └─ script/
│        └─ main.py
│
├─ data/
│  ├─ tasks/
│  │  ├─ daily-task/
│  │  ├─ long-task/
│  │  └─ standing-task/
│  ├─ logs/
│  ├─ state/
│  └─ cache/
│
├─ character/
│
├─ templates/
│  └─ daily-report.md
│
├─ .test/
│  ├─ Function-SmokeTest.py
│  └─ ...
│
├─ muse.py
├─ .env
├─ .gitignore
├─ README.md
└─ requirements.txt
```

`func/example-function/` 是 Custom Function 的官方参考包。其他 `func/<function-id>/` 默认属于用户自己的 Function Package，不应被 MuseAI 自动发现或擅自修改。

---

## 组件说明

### `AGENTS.md`

仓库根目录的 `AGENTS.md` 定义 MuseAI Main Agent 的长期控制规则。

Main 主要负责：

- 理解自然语言意图；
- 判断当前请求属于运行、开发还是讨论；
- 选择 Tool、Query、Skill 或 Sub-Agent；
- 编排有依赖关系的操作；
- 解释 Tool Result；
- 完成少量普通推理；
- 组织最终用户回复。

Main 不应重复实现已经属于 Tool / Query 的确定性逻辑。

---

### `.zcode/agents/`

存放真正需要独立认知上下文的 Sub-Agent。

Sub-Agent 不应因为“某个业务模块存在”就自动创建。只有当任务：

- 复杂；
- 独立；
- 值得形成完整委托；
- 需要上下文隔离、专业模型或第二意见；

时才使用。

当前典型角色包括：

- `analyst.md`
- `reviewer.md`
- `visual.md`

---

### `.zcode/skills/`

Skill 的含义是：

> **告诉当前 Agent“这一类工作应该怎么做”。**

Skill 不是独立执行者，也不直接拥有业务 Data。

当前主要 Skill：

- `reporter/SKILL.md`：最终报告和表现层规则。
- `task-management/SKILL.md`：Daily / Long / Standing Task 的管理方法。
- `daily-report/SKILL.md`：Daily Report 的解释和呈现方法。
- `custom-function/SKILL.md`：Custom Function 的安装、注册、运行和管理交互方法。

---

## 公共 Tool Result

MuseAI 公共 Tool 统一返回：

```json
{
  "ok": true,
  "operation": "time.current",
  "data": {},
  "warnings": [],
  "error": null
}
```

失败：

```json
{
  "ok": false,
  "operation": "...",
  "data": {},
  "warnings": [],
  "error": {
    "code": "...",
    "message": "...",
    "details": null
  }
}
```

约定：

- Tool 函数返回 `dict`，不直接打印；
- `muse.py` 最终只输出一个 JSON；
- Tool 成功退出码为 `0`；
- Tool 失败退出码为 `1`；
- argparse 参数错误退出码为 `2`；
- `muse.py` 负责配置了自动日志的公共操作的 `START / SUCCESS / FAILED` 生命周期日志。

---

## `muse.py`

`muse.py` 是 MuseAI 的统一公共 CLI。

示例：

```powershell
python muse.py time current

python muse.py task maintenance check
python muse.py task maintenance apply

python muse.py init daily
python muse.py report daily

python muse.py query task overview
python muse.py query task daily --status pending

python muse.py function list
python muse.py function get example-function
python muse.py function run example-function
```

Main 的普通运行流程应优先通过根 CLI，而不是直接调用内部 Service。

---

# 已实现能力

## Time

Time Tool 使用 `config/user.yaml` 中的 IANA 时区作为权威时区。

当前时间：

```powershell
python muse.py time current
```

项目运行依赖中应明确声明 `tzdata`，普通运行期间不允许 Main 静默安装。

---

## Log

生命周期日志按月写入：

```text
data/logs/YYYYMM.log
```

格式：

```text
YYYY-MM-DD｜HH:mm:ss｜PURPOSE｜OPERATION｜STATUS DESCRIPTION
```

`muse.py` 是公共 Tool 生命周期日志的唯一拥有者。

日志不是：

- 对话历史；
- 开发日志；
- Git 历史；
- Agent 思考记录。

---

## Task

Task 数据以 JSON 为权威来源，分为：

```text
data/tasks/
├─ daily-task/
├─ long-task/
└─ standing-task/
```

Task 公共能力统一通过：

```powershell
python muse.py task ...
```

### Daily

Daily Task 支持：

- 当日任务；
- carryover；
- Standing 生成 occurrence；
- 删除 provenance tombstone；
- 跨日维护。

### Long

Long Task 支持：

- active / archived；
- stage；
- deadline；
- timeline；
- done / reopen；
- archive 与 completion 分离。

### Standing

Standing Task 支持：

- daily；
- weekly；
- monthly；
- yearly；
- enabled；
- occurrence 生成；
- `last_generated_date`；
- 与 Long Task 关联。

---

## Daily Maintenance

Daily Maintenance 负责：

> **Daily Task 跨日状态维护：处理上一个有效 Daily 的 pending carryover，以及当日 Standing occurrence 的生成与恢复。**

公共接口：

```powershell
python muse.py task maintenance check
python muse.py task maintenance apply
```

支持显式日期：

```powershell
python muse.py task maintenance check --date YYYY-MM-DD
python muse.py task maintenance apply --date YYYY-MM-DD
```

`check` 只读，`apply` 幂等、可恢复。

---

## Daily Init

Daily Init 是每日任务状态的统一初始化入口：

```powershell
python muse.py init daily
```

内部复用 Maintenance：

```text
init daily
→ maintenance check
→ no action: no-op
→ actions: maintenance apply
```

当前 ZCode 使用 `UserPromptSubmit` Hook 调用：

```powershell
python muse.py --purpose DailyInitHook init daily
```

Hook 只决定**什么时候调用**，Task 业务逻辑仍由 MuseAI Tool 拥有。

---

## Daily Report

Daily Report 使用只读 Snapshot：

```powershell
python muse.py report daily
python muse.py report daily --date YYYY-MM-DD
```

普通当前日报流程：

```text
Daily Init
→ Daily Report
→ Main 根据 Skill 渲染
```

历史或未来日期不会因为“要生成报告”而被自动初始化。

---

# Query

Query 是 MuseAI 的：

> **通用只读快速检索层 / Read-only information access layer**

用于：

- 高频读取；
- 筛选；
- 聚合；
- 确定性派生事实；
- 直接关系查询。

Query 永远不：

- 修改业务 Data；
- 自动执行 Init；
- 自动执行 Maintenance；
- 静默刷新状态；
- 代替 Mutation Tool。

当前 Task Query：

```powershell
python muse.py query task daily
python muse.py query task long
python muse.py query task standing
python muse.py query task related
python muse.py query task overview
```

路由原则：

```text
用户意图
↓
信息获取型？
├─ yes → suitable Query?
│        ├─ yes → Query → sufficient? answer : Domain Tool
│        └─ no → Domain Tool
└─ mutation/action → Domain Tool
```

Main 正常运行时不直接调用内部 Service。

Query V1 已完成实现、回归和 CLI 验收。

---

# Custom Function

Custom Function 的定位是：

> **将用户提供的、相对成熟的脚本或程序封装进 MuseAI，负责统一注册、调用和执行状态上报。**

它不是脚本修复器，也不是自动插件发现系统。

当前公共接口：

```powershell
python muse.py function list
python muse.py function get <function-id>
python muse.py function run <function-id>

python muse.py function register <function-id> --name "..." --description "..."
python muse.py function update <function-id> --name "..." --description "..."
python muse.py function unregister <function-id>
python muse.py function enable <function-id>
python muse.py function disable <function-id>
```

## Registry

Custom Function 注册表：

```text
config/manifest.yaml
```

结构：

```yaml
schema_version: "1.0"

functions:
  example-function:
    name: Example Function
    description: Reference Custom Function package for MuseAI users.
    enabled: true
```

Manifest 是 MuseAI 对 Function 注册状态的唯一事实来源。

保存：

- Function ID；
- name；
- description；
- enabled。

不保存运行命令、argv、cwd 或 timeout。

### 核心规则

> **没有注册，就是没有。**

即：

```text
func/foo/ 存在
≠
MuseAI 已注册 foo
```

MuseAI 不扫描 `func/` 自动发现 Function，也不从目录名、README、脚本或注释猜测 Function 的语义信息。

安装 / 注册信息必须由用户明确提供给 Main：

- Function ID；
- Name；
- Description。

---

## Function Package

用户 Function Package：

```text
func/<function-id>/
├─ config/
│  └─ function.yaml
├─ data/
└─ script/
```

其中：

- `config/function.yaml`：仅描述“怎么运行”；
- `script/`：用户实现；
- `data/`：Function 自己的业务 / 运行数据。

示例：

```yaml
schema_version: "1.0"

process:
  command: python
  args:
    - script/main.py
  cwd: .
  timeout_seconds: null
```

`enabled` 不属于 `function.yaml`，它属于 `config/manifest.yaml`。

相对 `cwd` 从 Function root 解析。

`args` 作为 argv 原样传递：

```python
subprocess(..., shell=False)
```

MuseAI 不猜参数中的哪些字符串是路径，也不自动识别脚本类型。

---

## Example Function

官方参考：

```text
func/example-function/
```

用户可以参考或复制该目录实现自己的 Function。

`example-function` 同时作为仓库中可运行的参考 Custom Function。

用户自己的 `func/<id>/` 默认由 `.gitignore` 忽略；官方 `example-function` 被精确放行并随仓库交付。

---

## Function 管理语义

### register

```text
用户自行放置 Package
↓
用户明确提供 ID / Name / Description
↓
function.register
↓
验证目标 Package / config
↓
写入 manifest
```

Register：

- 不创建用户 Package；
- 不扫描其他 Function；
- 不猜语义信息；
- 注册前验证显式目标；
- 默认 `enabled=true`。

### update

只更新：

- name；
- description。

不修改用户 `function.yaml`、script 或 data。

### enable / disable

只修改：

```text
config/manifest.yaml
```

操作幂等：

```text
状态真正改变 → changed=true
已经是目标状态 → changed=false
```

### unregister

只解除注册：

```text
remove manifest entry
```

绝不删除：

```text
func/<function-id>/
```

当前 MuseAI 没有自动删除用户 Function Package 的流程。

---

## Function Runtime

执行结果：

```text
exit_code = 0
→ function.run ok=true

exit_code != 0
→ FUNCTION_PROCESS_FAILED
```

保留并上报：

- exit_code；
- stdout；
- stderr；
- stdout_truncated；
- stderr_truncated。

stdout / stderr 持续排空，但每个流只保留有限前缀，避免无限内存增长。

Function Runtime 不自动：

- 诊断业务错误；
- 修复脚本；
- 重试；
- 安装依赖；
- 修改用户环境；
- 修改 Function implementation。

### Windows 生命周期规则

Windows 下，MuseAI 必须先建立对 Function 进程树的可靠 Job Object 所有权，然后才允许用户代码执行。

原则：

> **无法建立可靠的 Windows 进程树所有权，就拒绝启动 Function。**

因此 Job 创建或绑定失败时：

```text
保持 suspended
→ 清理进程
→ FUNCTION_START_FAILED
```

不会退化成“已经运行但无法保证清理”的状态。

Timeout、`KeyboardInterrupt` 和异常退出都必须先完成进程树清理，再返回或继续传播异常。

---

## Custom Function Skill

Main 的安装 / 注册 / 管理交互规则位于：

```text
.zcode/skills/custom-function/SKILL.md
```

用户询问如何安装或添加 Custom Function 时，Main 应：

1. 引导用户参考 `func/example-function/`；
2. 由用户自行准备和放置 Function Package；
3. 从用户明确获取 ID / Name / Description；
4. 不扫描 `func/`；
5. 不自动猜测 Function 用途；
6. 使用公共 Function Tool 完成注册和管理。

---

## Custom Function V2 状态

Custom Function 当前已完成：

```text
V1 Runtime             PASS
V2 Registry            PASS
Example Function       PASS
Custom Function Skill  PASS
Windows lifecycle      PASS
Smoke / regression     PASS
Code review            PASS WITH NOTES
Real CLI acceptance    PASS
Lifecycle logging      PASS
```

真实 CLI 验收覆盖：

- list / get / run；
- register / duplicate register；
- update；
- enable / disable 及幂等；
- disabled run；
- unregister；
- unregister 后 Package 保留；
- unregister 后不可运行；
- `function.yaml` 不被管理操作修改；
- root lifecycle logging。

Custom Function V2 可以视为当前正式完成。

---

# 配置与数据

## `config/`

当前核心配置：

```text
config/
├─ user.yaml
└─ manifest.yaml
```

原则：

```text
.env       → Secrets
config/    → Settings
data/      → State
templates/ → Structure
```

`user.yaml` 是用户配置，不应提交真实私人内容。

`manifest.yaml` 是 MuseAI 管理的 Custom Function Registry。

---

## `data/`

`data/` 保存运行时状态。

默认不作为项目源码提交，包括：

- Tasks；
- Logs；
- State；
- Cache；
- 其他用户业务数据。

空目录可通过 `.gitkeep` 保留结构。

---

## `templates/`

Template 只用于稳定的人类可读结构。

目前 Daily Report 使用：

```text
templates/daily-report.md
```

旧的 Custom Function 配置模板已移除；Function 的参考规范现在由：

```text
func/example-function/
```

直接提供。

---

# Git 与隐私

MuseAI 将源码与用户数据分离。

当前原则：

- `/data/**` 默认忽略；
- `/config/user.yaml` 忽略；
- `.env` 忽略；
- `/func/**` 默认忽略；
- `func/example-function/**` 精确放行；
- Git 写操作需要用户明确授权。

普通运行不能自动：

- `git add`；
- commit；
- push；
- tag；
- reset；
- rebase。

项目 release version 与业务 `schema_version` 相互独立。

---

# 架构判断原则

新增能力时：

```text
能机械化？
    ↓ 是
Tool / Program

主要是高频只读检索？
    ↓ 是
Query

不能完全机械化
    ↓
是否只是固定、可复用的方法或规范？
    ↓ 是
Skill

仍然需要 AI 判断
    ↓
Main 能否轻松完成？
    ↓ 是
Main

任务是否复杂、独立，值得单独委托？
    ↓ 是
Sub-Agent
```

判断 Sub-Agent 时优先考虑：

- 复杂性；
- 独立性；
- 上下文隔离收益；
- 专业化收益；
- 委托成本。

重复并不自动意味着需要 Sub-Agent；重复的确定性工作通常更应该进入 Program。

---

# 当前开发状态

已完成：

1. Time / Log 基础能力；
2. Task 基础管理；
3. Cross-day Daily Maintenance；
4. Daily Report；
5. Daily Init；
6. ZCode Daily Init Hook；
7. Query / Task Query V1；
8. Custom Function V1；
9. Custom Function V2。

当前后续方向：

1. Weekly Report；
2. Character；
3. API Price Tracker；
4. 第一个真正有独立认知价值的 Sub-Agent；
5. GUI。

未实现的规划能力不能因为出现在 README、目录或 Roadmap 中，就被 Main 当作已经存在。

---

# 项目愿景

MuseAI 的目标不是让 AI 亲自完成所有步骤，而是让 AI 成为一个能够理解用户目标、调度可靠程序、使用专业方法，并在必要时调用专业智能体的本地助手。

理想状态：

```text
User
  ↓
Main Agent
  ├─ Tool / Program
  ├─ Query
  ├─ Skill
  ├─ Sub-Agent
  └─ Data
  ↓
Result
```

最终用户只需要表达目标。

其余确定性流程由程序可靠执行，需要智能判断的部分再交给 AI。

> **让程序继续机械，让 AI 处理无法机械化的问题。**

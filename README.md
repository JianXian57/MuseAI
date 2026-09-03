# MuseAI

MuseAI 是一个面向本地工作流的个人 AI 助手项目。

项目目标不是让 AI 直接承担所有工作，而是将系统拆分为清晰的职责层：

- **Main Agent**：理解用户意图、进行必要判断、选择并调用能力。
- **Tool / Program**：负责可机械化、可确定执行的工作。
- **Skill**：保存可复用的方法、流程与输出规范。
- **Sub-Agent**：仅用于复杂、独立、需要专业认知或上下文隔离的智能任务。
- **Template**：保存稳定的输出骨架和文件结构。
- **Data**：保存用户运行时数据、状态、日志与历史记录。

核心原则：

> **人负责目标，AI 负责不确定性，程序负责确定性。**

---

## 设计原则

MuseAI 遵循以下原则：

1. 能由普通程序稳定实现的工作，优先实现为 **Tool / Program**。
2. 需要复用固定方法、规范或流程时，优先实现为 **Skill**。
3. 简单的非机械化判断由 **Main Agent** 直接完成。
4. 只有当任务具有较高复杂度、独立性，或需要上下文隔离时，才考虑 **Sub-Agent**。
5. 用户数据、日志、密钥和运行状态与项目代码分离。
6. Tool 输出应尽量结构化，优先使用 JSON，减少 AI 对原始日志和大文件的重复解析。
7. Main Agent 不应直接承担已经由 Tool 或其他专门组件负责的确定性工作。
8. 项目结构应便于后续接入 GUI、本地模型、远程服务器与自动化任务。

---

## 推荐目录结构

```text
MuseAI/
│
├─ .zcode/
│  ├─ AGENTS.md
│  │
│  ├─ agents/
│  │  ├─ analyst.md
│  │  ├─ reviewer.md
│  │  └─ visual.md
│  │
│  └─ skills/
│     ├─ reporter/
│     │  └─ SKILL.md
│     └─ daily-report/
│        └─ SKILL.md
│
├─ tools/
│  ├─ muse.py
│  ├─ task.py
│  ├─ time_tool.py
│  ├─ log.py
│  ├─ git_tool.py
│  ├─ balance.py
│  ├─ api_price.py
│  └─ custom_function.py
│
├─ config/
│  ├─ user.example.yaml
│  ├─ custom-functions.yaml
│  └─ api-providers.yaml
│
├─ data/
│  ├─ tasks/
│  │  ├─ daily/
│  │  ├─ long/
│  │  └─ standing/
│  │
│  ├─ logs/
│  ├─ api-price/
│  ├─ state/
│  └─ cache/
│
├─ character/
│  ├─ default.md
│  ├─ muelsyse.md
│  └─ ...
│
├─ templates/
│  ├─ daily-task.md
│  ├─ long-task.md
│  ├─ daily-report.md
│  └─ character-form.md
│
├─ tests/
│
├─ .env.example
├─ .gitignore
├─ README.md
└─ requirements.txt
```

> `agents/` 中的文件不要求在项目初始化阶段全部存在。  
> Sub-Agent 应按实际需求创建，不应因为存在一个功能模块就自动创建一个 Agent。

---

## 目录说明

### `.zcode/`

ZCode 相关的 AI 控制层。

#### `.zcode/AGENTS.md`

MuseAI 的 Main Agent 定义。

Main Agent 主要负责：

- 理解用户请求；
- 判断是否需要调用 Tool、Skill 或 Sub-Agent；
- 管理执行顺序；
- 收集结构化结果；
- 处理无法机械化的少量判断；
- 组织最终回复。

Main Agent 不应重复实现已经交由 Tool 负责的机械逻辑。

#### `.zcode/agents/`

存放真正需要独立认知上下文的 Sub-Agent。

推荐仅在以下情况创建：

- 任务复杂且需要多阶段推理；
- 能形成完整、独立的认知工作包；
- 需要独立审查或第二意见；
- 需要使用不同模型；
- 需要隔离大量上下文，避免 Main Agent 负担过重。

可能的示例：

- `analyst.md`：复杂历史数据或项目分析；
- `reviewer.md`：独立审查与第二意见；
- `visual.md`：视觉设计、图片生成决策或视觉理解。

---

### `.zcode/skills/`

存放可复用的方法、规范和流程。

Skill 的含义是：

> **告诉当前 Agent“这种工作应该怎么做”。**

Skill 不是独立的执行者，也不是新的智能体。

示例：

#### `reporter/SKILL.md`

负责：

- 最终回复组织方式；
- 人格应用规则；
- Emoji 使用规则；
- 技术内容保护；
- 错误与警告的展示方式。

#### `daily-report/SKILL.md`

负责：

- 每日汇报应收集哪些信息；
- Tool 调用顺序；
- 输出结构；
- 缺失信息处理方式。

---

### `tools/`

MuseAI 的确定性执行层。

凡是能够稳定机械化实现的工作，都应优先放入这里。

例如：

- 文件检查；
- Markdown 创建与修改；
- 日期与时区计算；
- 日志追加；
- Git 操作；
- API 请求；
- 价格抓取；
- 历史数据统计；
- 自定义功能执行。

#### `muse.py`

推荐作为统一 CLI 入口。

例如：

```powershell
python tools\muse.py time current
python tools\muse.py task daily-list --date 2026-09-03
python tools\muse.py task add-daily --date 2026-09-03 --text "测试服务器"
python tools\muse.py api-price latest
python tools\muse.py api-price update
```

推荐所有 Tool 输出统一 JSON：

```json
{
  "ok": true,
  "operation": "task.daily_list",
  "data": {},
  "warnings": [],
  "error": null
}
```

这样可以降低 Main Agent 的解析成本与 Token 消耗。

---

### `config/`

存放项目配置。

推荐保存：

- 非敏感业务配置；
- 自定义功能注册表；
- API 数据源定义；
- 示例用户配置。

#### `user.example.yaml`

可提交到 Git 的用户配置模板。

真实用户配置建议另建：

```text
config/user.yaml
```

并加入 `.gitignore`。

#### `custom-functions.yaml`

未来用于注册 MuseAI 的自定义功能。

#### `api-providers.yaml`

未来可用于保存 API 厂商、官方价格来源、模型信息或解析配置。

---

### `data/`

保存 MuseAI 的运行时数据。

**默认不提交到 Git。**

可能包含：

- 每日任务；
- 长期任务；
- 常驻任务；
- 项目日志；
- API 价格历史；
- 当前状态；
- 缓存；
- 用户相关数据。

建议将 `data/` 视为：

> **用户状态层，而不是项目源码的一部分。**

如需保留目录结构，可在空目录中加入 `.gitkeep`。

---

### `character/`

保存人格定义。

例如：

- `default.md`
- `muelsyse.md`

人格文件只负责表现层内容，例如：

- 性格；
- 语气；
- 称呼；
- Emoji 偏好；
- 互动风格；
- 特征表达方式。

人格文件不应获得：

- Tool 执行权限；
- 项目管理权限；
- 文件写入权限；
- 系统架构控制权。

当前激活人格属于用户状态，后续建议保存在：

```text
data/state/
```

而不是写死在项目代码中。

---

### `templates/`

保存稳定的文件骨架与输出格式。

Template 的作用是：

> **定义“生成结果应该长什么样”。**

例如：

- `daily-task.md`：每日任务文件骨架；
- `long-task.md`：长期任务文件骨架；
- `daily-report.md`：每日汇报结构；
- `character-form.md`：人格文件模板。

Template 不负责执行逻辑。

可以这样理解：

- Tool：负责做；
- Skill：负责说明怎么做；
- Template：负责定义结果长什么样；
- Data：保存做完后的结果。

---

### `tests/`

存放 Tool 与核心逻辑的自动化测试。

随着项目逐步机械化，这个目录会越来越重要。

推荐优先测试：

- 文件写入是否安全；
- Task CRUD；
- 日期处理；
- Standing Task 触发逻辑；
- API 价格解析；
- 历史数据更新；
- Tool JSON 输出协议。

---

## `.env`

`.env` 用于保存本地运行时秘密，例如：

```env
DEEPSEEK_API_KEY=
ZHIPU_API_KEY=
GITHUB_TOKEN=
```

真实 `.env` 不应提交到 Git。

仓库中仅保留：

```text
.env.example
```

作为所需环境变量的说明。

推荐原则：

```text
.env       → Secrets
config/    → Settings
data/      → State
templates/ → Structure
```

---

## Git 与隐私

MuseAI 应从项目创建之初就将源码与用户数据分离。

建议 `.gitignore` 至少包含：

```gitignore
# Private/runtime data
/data/**

# Keep directory placeholders
!/data/**/.gitkeep

# User-specific config
/config/user.yaml
/config/local.yaml
/config/*.local.yaml

# Secrets
.env
.env.*
!.env.example

# Logs and runtime output
*.log
/cache/
/tmp/
/temp/
/output/
/outputs/
/generated/

# Python
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.venv/
venv/
env/

# IDE / OS
.vscode/
.idea/
.DS_Store
Thumbs.db
desktop.ini

# ZCode runtime state if present
.zcode/cache/
.zcode/state/
.zcode/logs/
```

项目仓库应主要保存：

- Agent / Skill 定义；
- Tool 源码；
- Templates；
- 非敏感配置模板；
- Character 定义；
- Tests；
- 文档。

不应保存：

- 用户任务；
- 私人日志；
- API Key；
- Token；
- 本地状态；
- 缓存；
- 个人账号信息。

---

## 初始 Git 建议

首次创建仓库时建议：

```powershell
git init
git add .
git status
```

在第一次 Commit 前，务必检查 staged 文件中是否出现：

```text
data/
.env
config/user.yaml
私人日志
API Key
Token
真实用户记录
```

确认无误后再提交：

```powershell
git commit -m "Initial MuseAI architecture"
```

---

## 架构判断原则

以后新增能力时，可以按以下顺序判断：

```text
能机械化？
    ↓ 是
Tool / Program

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

任务是否复杂、独立，或需要上下文隔离？
    ↓ 是
Sub-Agent
```

其中：

- **复杂性**：最重要；
- **独立性**：决定是否值得拆出；
- **重复性**：决定是否值得长期维护为专门组件；
- **上下文负担**：可作为拆分 Sub-Agent 的重要理由。

---

## 当前开发方向

MuseAI 当前处于架构重构阶段。

推荐开发顺序：

1. 建立目录与 Main Agent；
2. 定义统一 Tool JSON 协议；
3. 实现 `time` 与 `log` Tool；
4. 实现统一 `task` Tool；
5. 建立 Reporter Skill；
6. 重构 Daily Report；
7. 建立 Custom Function Runtime；
8. 实现 API Price Tracker；
9. 再逐步迁移 Git、Balance 等功能；
10. 最后根据实际需求决定是否增加 Sub-Agent、GUI、本地模型与图片生成。

---

## 项目愿景

MuseAI 的目标不是让 AI 亲自完成所有步骤，而是让 AI 成为一个能够理解用户目标、调度可靠程序、使用专业方法并在必要时调用专业智能体的本地助手。

理想状态：

```text
User
  ↓
Main Agent
  ├─ Tool
  ├─ Skill
  ├─ Sub-Agent
  └─ Data
  ↓
Result
```

最终用户只需要表达目标。

其余确定性流程由程序可靠执行，需要智能判断的部分再交给 AI。

> **让程序继续机械，让 AI 处理无法机械化的问题。**

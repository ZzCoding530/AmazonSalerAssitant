# Amazon AdGenie 项目文档（强制约束 + 开发说明）

> 版本：v3（约束）/ v1.0（开发说明）
> 适用项目：亚马逊广告精灵（Amazon AdGenie）
> 核心原则：**代码交付标准不降，运行数据来源可选。** 数据可以造，但每一条代码路径必须是生产级的真实实现。

本文件由两部分组成：

- **第一部分：强制约束（Anti-Degradation Rules）** —— 红线清单，用于验收时挑错。
- **第二部分：开发说明文档** —— 实现蓝图，用于开发时对照。

建议保存为项目根目录的 `CLAUDE.md`（Cursor 用户可另存 `.cursorrules`）。冲突时以第一部分为准。

---

# 第一部分：强制约束（Anti-Degradation Rules）

> 本文件优先级高于任何对话中的临时指令。
> 若某条规则与实现成本冲突，必须停下来报告冲突并等待决策，禁止自行降级。

## 0. 元规则（最高优先级）

- **禁止静默降级**：任何"先做简化版""后续再补""这里先 mock"的想法，必须先声明【降级申请】+ 原因 + 影响面，等我确认后才可执行。未经确认的降级视为任务失败。
- **禁止省略式完成**：不允许用 `# 此处省略`、`pass  # TODO`、`raise NotImplementedError`、`...` 作为交付内容。
- **完成定义（DoD）**：一个任务只有同时满足 ①代码可运行 ②有对应测试 ③通过验证清单 ④无未声明的降级，才算完成。缺一项即为未完成。
- **每轮交付必须附《完成度报告》**，包含四栏：已实现 / 降级项（含原因）/ 未实现项（含阻塞原因）/ 下一步。
- **黄金检验标准**：把配置项 `data_source` 从 `seed` 改为 `live`，代码是否需要修改？如果需要修改，说明你降级了。

## 1. 架构红线

- 编排层必须使用 **LangGraph** 构建事件驱动 DAG，禁止退化为顺序调用、轮询、或"一个大 Agent 包揽所有事"。
- 四类 Agent（评论洞察 / 广告评分 / 竞品分析 / 策略生成）必须独立成节点，按**数据版本依赖**（用户画像 vₙ + 评分报告 vₘ + 知识库快照 sₖ）触发；无增量输入时该节点不得被唤醒，禁止轮询。
- 单 Agent 故障只影响其下游分支，不得导致整个 DAG 崩溃。
- **写判分离不可妥协**：StrategyWriter 与 Judge 必须使用不同厂商模型（写：Qwen/DeepSeek；判：GLM），Judge 侧 temperature 固定为 0。禁止用同一个模型同时承担写与判。
- **双轨分工边界**：评论去重、关键词命中、卖点对齐集合运算、评分汇总必须由代码实现；模型只负责语义归因、rubric 打分、策略生成。即使"让模型做更简单"，仍必须走代码管道。

## 2. 采集层与数据层（爬虫逻辑必须真实实现，数据来源可选）

### 2.1 采集层是完整交付物，不是可选模块

- **Scrapy 引擎**必须实现：
  - Spider（含多页面类型解析）
  - Item Pipeline（清洗、过滤、入库）
  - 增量去重（同一 Listing 仅处理新增评论）
  - 限流（DOWNLOAD_DELAY / AUTOTHROTTLE）
  - 重试与指数退避
  - 代理池轮换中间件
  - 反封禁策略（UA 轮换、Cookie 管理、请求指纹去重）
- **Playwright 引擎**必须实现：
  - 浏览器上下文管理与复用
  - 显式等待策略（禁止裸 sleep）
  - 动态元素定位与容错
  - 截图留证
  - 异常恢复与上下文重建
- **双引擎必须通过统一抽象接口**（如 `BaseCrawler`）调度，由配置或反爬强度探测选择引擎。禁止只实现其一后删掉另一接口。
- **允许**在演示/自测时不实际请求亚马逊站点，但**禁止因此删减或简化上述任何采集逻辑**。判断标准：把数据源换成真实 URL 后，代码应无需修改即可运行。

### 2.2 数据层

- **允许**使用自造数据 / 种子数据 / 合成数据作为下游输入，但必须通过**与生产同构的数据访问层**进入系统，禁止在业务代码里内联硬编码数据字典。
- **禁止**用"数据是造的"作为简化实现的理由。数据源可以是造的，但读取、清洗、去重、过滤、入库的代码路径必须真实完整。
- 存储分工固定：MySQL（原始+业务数据）/ Redis（缓存）/ Milvus（素材向量）。禁止把向量塞进 MySQL、禁止用内存 dict 代替 Redis。
- 画像数据**只允许**使用 verified purchase 评论；水军/未购评论的过滤逻辑必须实现并有测试覆盖。

## 3. 核心机制红线（本项目差异化价值，禁止简化）

- **证据锚定与编号白名单**：每条用户关注点必须携带「评论编号 + 原文引用」；白名单校验必须实现，白名单外引用（含编造编号）必须拒收并触发重提，禁止"打个警告继续用"；分析输入按批次冻结，结论可回溯对账。
- **双标尺评分**：需求对齐度（代码集合运算）与转化说服力（模型 rubric 逐项）必须独立计算再合成，禁止合并成单一总分；评分明细到每条卖点 / 每条 bullet，每条扣分必须输出依据位置。
- **构造式评分校准**：主扰动（埋入已知缺陷）与安慰剂（无缺陷优质文案）两套考卷必须都实现，检出率与误判率必须分开报告，并经置换检验给出 p 值；禁止只报一个"准确率"；校准结果回灌 rubric 并版本化。
- **时效感知混合检索**：必须"元数据粗筛（类目/价格带/评分段/榜单排名）→ BGE-M3 向量召回 → Cross-Encoder 精排"三段式；排序融合语义相关度 × 时效衰减权重 × 销量置信度；禁止跳过粗筛直接全库向量检索；过期素材自动降权归档。
- **知识库自更新闭环**：增量入库 + 过时素材检测，同一竞品卖点变化时更新条目而非重复堆积，历史版本保留可回溯。
- **冻结 manifest 可审计协议**：每次评分必须固化 rubric 版本、模型、温度、证据快照指纹，保证可回放、改版前后历史严格可比。禁止只存最终分数。

## 4. 工程规范

- 技术栈固定：Python + Flask（服务层）/ Go + gRPC（调度层）/ Vue（前端）。禁止替换技术栈或"先用 FastAPI 代替 Flask"。
- 所有外部依赖（模型 API、代理池、MQ、存储）必须通过接口抽象注入，便于测试时替换；但**生产实现必须真实存在**，不得只有 mock 实现。
- 每个 Agent 节点必须有：输入 schema 校验、输出 schema 校验、失败重试策略、超时与降级路径（降级路径也需显式声明）。
- 测试要求：核心机制（证据白名单、双标尺、校准、去重、过滤）必须有单元测试；DAG 编排必须有集成测试；爬虫解析与容错逻辑必须有离线测试。禁止"代码写完没测就交付"。
- 配置外置：模型名、密钥、限流参数、阈值全部走配置文件/环境变量，禁止硬编码。

## 5. 禁止行为清单

| 禁止 | 说明 |
|---|---|
| 用伪代码/注释代替实现 | 视为未完成 |
| 只写 happy path | 异常分支必须处理 |
| 硬编码密钥/模型名/阈值 | 走配置 |
| 跳过测试直接说"已完成" | 违反 DoD |
| 自行删减"看起来不重要"的模块 | 必须申请 |
| 以"数据是造的"为由简化代码路径 | 违反第 2 节 |
| 以"不联网"为由删减爬虫逻辑 | 违反第 2.1 节 |
| 用示例数据跑通就宣布成功 | 需走完整链路验证 |
| 把双标尺合并成单一总分 | 违反第 3 节 |
| 白名单校验只打日志不拒收 | 违反第 3 节 |

## 6. 数据与测试的分工规范

### 6.1 三层数据来源，各管各的

| 层级 | 数据来源 | 要求 |
|---|---|---|
| 采集层（爬虫） | 真实代码 + 可选真实请求 | 逻辑必须完整，用本地 HTML 快照/离线 fixture 驱动测试 |
| 业务层（Agent 链路） | 自造数据 | 必须走真实数据访问层，禁止内联 |
| 机制验证层 | 构造的边界数据 | 必须能触发拦截逻辑 |

### 6.2 爬虫的测试方式（不联网也要测）

- 用**本地保存的 HTML 快照 / fixture 文件**驱动 Spider 解析逻辑测试，验证字段提取、分页处理、变体合并、去重、Pipeline 是否正确。
- 用 mock 网络层（如 `responses` / `pytest-mock`）测试重试、限流、代理轮换、异常恢复分支。
- 禁止因为"不联网"就跳过爬虫测试——解析逻辑和容错逻辑是爬虫的核心价值，必须有测试覆盖。

### 6.3 合成数据必须覆盖边界场景

合成数据必须放在独立目录（如 `data/seed/`），通过 `DataFactory` / fixture 统一生成，禁止散落在测试代码里。必须覆盖以下边界场景，而非只造"顺利路径"：

- 含水军 / 未购评论 → 验证过滤逻辑
- 含重复评论 → 验证增量去重
- 含与广告卖点矛盾的评论 → 验证需求对齐度扣分
- 含编造编号的模型输出 → 验证白名单拒收
- 含过期竞品素材 → 验证时效衰减与归档
- 含缺失字段 / 异常结构的页面 → 验证爬虫容错

**断言必须针对"机制是否正确拦截"，而非"流程是否跑通"。** 数据生成脚本本身也属于交付物，需固定随机种子、可复现。

## 7. 交付流程

按以下六阶段推进，每阶段交付后需人工验收通过才进入下一阶段：

1. **DAG 骨架**：LangGraph 编排 + 版本依赖触发 + 写判分离
2. **采集层**：双引擎 + 代理池 + 限流 + 增量去重 + 离线测试
3. **证据锚定**：编号白名单 + 拒收重提 + 批次冻结
4. **双标尺评分**：代码集合运算 + rubric 逐项 + 扣分溯源
5. **校准与检索**：主扰动/安慰剂考卷 + 混合检索三段式 + 时效衰减
6. **闭环与审计**：知识库自更新 + 冻结 manifest + 可回放

每阶段交付物必须包含：代码、测试、《完成度报告》、该阶段对应的边界测试用例执行结果。

---

# 第二部分：开发说明文档

> 阅读顺序：先读第一部分第 0/2/3/5 节，再读本文档。冲突时以第一部分为准。

## 一、项目定位

**一句话**：基于亚马逊真实用户画像与竞品素材库，为广告文案生成「证据可回溯、评分可校准」的优化策略系统。

**核心差异点**（这三点决定项目价值，任何取舍不得损害）：

1. **证据锚定** —— 每条结论可回溯到具体评论原文，模型无法编造。
2. **双标尺评分** —— 需求对齐度（代码算）与转化说服力（模型评）分离，避免单一总分的模糊性。
3. **构造式校准** —— 用已知缺陷考卷验证 Judge 是否真的能识别问题，而非自证"我们很准"。

**非目标**（明确不做，避免范围蔓延）：

- 不做广告自动投放（只出策略，不接管账户）
- 不做多平台（本期仅亚马逊）
- 不做实时竞价建议
- 不追求"覆盖全类目"，先跑通 1-2 个类目的完整闭环

## 二、技术栈总览

| 层次 | 技术 | 说明 |
|---|---|---|
| 编排层 | LangGraph | 事件驱动 DAG，版本依赖触发 |
| 服务层 | Python + Flask | 业务 API、Agent 节点实现 |
| 调度层 | Go + gRPC | 任务调度、限流、重试 |
| 采集层 | Scrapy + Playwright | 双引擎，统一抽象接口 |
| 模型层 | Qwen/DeepSeek（写）+ GLM（判） | 写判分离，Judge 温度=0 |
| 存储 | MySQL / Redis / Milvus | 原始业务 / 缓存 / 向量 |
| 检索 | BGE-M3 + Cross-Encoder | 三段式混合检索 |
| 前端 | Vue | 报告展示、策略对比 |

## 三、系统架构

### 3.1 数据流全景

```
[采集层]                [数据层]              [编排层 LangGraph]
Scrapy ─┐
        ├─→ 原始评论表 ─→ 清洗过滤 ─→ 用户画像 vₙ ─┐
Playwright ┘   (verified only)     (增量去重)      │
                                                  ├─→ 评论洞察 Agent ─┐
[竞品采集] ─→ 素材库 ─→ 混合检索 ─→ 知识库快照 sₖ ─┤                   │
                                                  ├─→ 竞品分析 Agent ─┤
[广告文案] ─→ 待评文案 ───────────────────────────┤                   │
                                                  ├─→ 广告评分 Agent ─┤
                                                  │                   │
                                                  └─→ 策略生成 Agent ←┘
                                                         ↓
                                              冻结 manifest + 报告
```

### 3.2 触发机制（关键）

**禁止轮询。** 每个 Agent 节点订阅"数据版本"而非"时间"：

| Agent | 触发条件 |
|---|---|
| 评论洞察 | 画像版本 vₙ 更新（有新评论入库） |
| 广告评分 | 待评文案变更 或 rubric 版本升级 |
| 竞品分析 | 知识库快照 sₖ 更新 |
| 策略生成 | 评分报告 vₘ + 洞察结论 同时就绪 |

无增量输入时节点不唤醒。单节点失败只阻断其下游分支。

## 四、模块开发说明

### 4.1 采集层

#### 目录结构

```
crawler/
├── base.py              # BaseCrawler 抽象接口
├── scrapy_engine.py     # Scrapy 引擎实现
├── playwright_engine.py # Playwright 引擎实现
├── engine_selector.py   # 引擎选择策略（配置/反爬探测）
├── spiders/
│   ├── review_spider.py
│   └── competitor_spider.py
├── pipelines.py         # 清洗、过滤、去重、入库
├── middlewares.py       # 代理池、UA 轮换、限流、重试
└── fixtures/            # 离线测试用 HTML 快照
```

#### 必须实现的接口

```python
class BaseCrawler(ABC):
    @abstractmethod
    async def crawl(self, target: CrawlTarget) -> CrawlResult: ...

    @abstractmethod
    async def health_check(self) -> bool: ...

    @abstractmethod
    def supports(self, target_type: TargetType) -> bool: ...
```

#### 关键实现要点

**增量去重**：以 `listing_id + review_id` 为唯一键，入库前查 Redis 布隆过滤器，命中则跳过。禁止全量重跑。

**verified 过滤**：在 Pipeline 阶段过滤，不在 Spider 阶段。判定依据：评论页 `Verified Purchase` 标识字段。被过滤的记录仍需落库（标记 `filtered_reason`），便于审计。

**反封禁策略链**（按顺序降级）：1. UA 轮换 → 2. 代理池轮换 → 3. 请求间隔指数退避 → 4. 切换 Playwright 引擎 → 5. 熔断并告警

**离线测试要求**：
- 每个 Spider 必须有对应的 `fixtures/*.html` 快照
- 测试必须覆盖：正常解析、分页、变体合并、缺失字段、异常结构
- 用 `responses` / `pytest-mock` 测试重试、限流、代理轮换分支
- **不联网也必须跑通全部爬虫测试**

### 4.2 数据层

#### 核心表设计（简化）

```sql
-- 原始评论
reviews_raw (
  review_id, listing_id, asin, reviewer_id,
  rating, title, content, is_verified,
  filtered_reason,      -- 过滤原因（未购/水军/重复）
  raw_html_ref,         -- 原始快照引用
  crawled_at
)

-- 用户画像（版本化）
user_profile_versions (
  version_id, listing_id,
  concerns_json,        -- 关注点列表（含证据引用）
  evidence_manifest,    -- 证据快照指纹
  prev_version_id,
  created_at
)

-- 评分报告（冻结 manifest）
score_reports (
  report_id, listing_id, copy_version,
  rubric_version, model_name, temperature,
  alignment_score,      -- 需求对齐度（代码算）
  persuasion_score,     -- 转化说服力（模型评）
  detail_json,          -- 逐条卖点扣分依据
  evidence_snapshot,    -- 证据指纹
  created_at
)
```

#### 存储分工红线

| 数据 | 存储 | 禁止 |
|---|---|---|
| 原始评论、业务实体 | MySQL | 存向量 |
| 去重布隆、限流计数、会话 | Redis | 用内存 dict 替代 |
| 竞品素材向量 | Milvus | 存进 MySQL |

### 4.3 编排层（LangGraph）

#### 节点定义规范

每个节点必须实现四件套：

```python
class AgentNode:
    def validate_input(self, state: GraphState) -> None: ...
    def validate_output(self, result: Any) -> None: ...
    async def execute(self, state: GraphState) -> Any: ...
    async def on_failure(self, state: GraphState, err: Exception) -> str:
        """返回降级策略名，必须显式声明"""
```

#### 写判分离实现

```python
# 策略生成（写）
writer = LLMClient(model="qwen-max", temperature=0.7)

# 评分（判）—— 温度必须为 0
judge = LLMClient(model="glm-4-plus", temperature=0)

# 禁止：同一个 client 同时用于写和判
```

#### 版本依赖触发

```python
# 伪代码：节点订阅数据版本
graph.add_edge(
    source="review_insight",
    target="strategy_gen",
    condition=lambda s: s.profile_version != s.last_used_profile_version
)
```

### 4.4 核心机制实现

#### 机制一：证据锚定与白名单

```python
def validate_evidence(claims: list[Claim], whitelist: set[str]) -> ValidationResult:
    """
    白名单外引用必须拒收，触发重提，禁止仅打日志。
    """
    violations = [c for c in claims if c.review_id not in whitelist]
    if violations:
        return ValidationResult(
            passed=False,
            violations=violations,
            action="REJECT_AND_REPROMPT"   # 不是 WARN
        )
    return ValidationResult(passed=True)
```

**重提机制**：最多重试 2 次，仍失败则标记该结论为"证据不足"并剔除，不得保留无证据结论。

#### 机制二：双标尺评分

```python
# 需求对齐度：代码集合运算，不调模型
alignment = compute_alignment(
    copy_keywords=set(extract_keywords(ad_copy)),
    concern_keywords=set(profile.concern_keywords)
)

# 转化说服力：模型 rubric 逐项打分
persuasion = judge.score_rubric(
    rubric=PERSUASION_RUBRIC,   # 版本化
    copy=ad_copy,
    evidence=profile.evidences
)

# 独立存储，禁止合并成单一总分
report.alignment_score = alignment
report.persuasion_score = persuasion
```

**扣分必须溯源**：每条扣分项携带 `{"item": "...", "reason": "...", "evidence_ref": "R-123"}`。

#### 机制三：构造式校准

```python
def run_calibration():
    # 主扰动：埋入已知缺陷
    perturbed = inject_defects(base_copy, defect_type="missing_key_concern")
    # 安慰剂：无缺陷优质文案
    placebo = high_quality_copy

    detected = judge.detect(perturbed)      # 应检出
    false_alarm = judge.detect(placebo)     # 不应误报

    report = {
        "detection_rate": detected / total_perturbed,
        "false_alarm_rate": false_alarm / total_placebo,
        "p_value": permutation_test(detected, false_alarm)
    }
    # 禁止只报一个"准确率"
    return report
```

#### 机制四：混合检索三段式

```python
def hybrid_search(query: str, filters: dict) -> list[Material]:
    # 第一段：元数据粗筛（缩小候选集）
    candidates = milvus.filter(
        category=filters["category"],
        price_band=filters["price_band"],
        rating_range=filters["rating_range"]
    )
    # 第二段：BGE-M3 向量召回
    recalled = bge_m3.search(query, candidates, top_k=50)
    # 第三段：Cross-Encoder 精排 + 时效衰减
    ranked = cross_encoder.rerank(
        query, recalled,
        weights={
            "semantic": 0.6,
            "recency_decay": 0.25,
            "sales_confidence": 0.15
        }
    )
    return ranked
```

**禁止**：跳过第一段直接全库向量检索。

#### 机制五：冻结 manifest

每次评分必须落库：`rubric_version + model_name + temperature + evidence_snapshot_hash`。回放接口：给定 `report_id`，必须能还原当时的完整输入与输出。

## 五、开发阶段规划

| 阶段 | 内容 | 验收要点 |
|---|---|---|
| **S1 骨架** | LangGraph DAG + 版本触发 + 写判分离 | 空跑 DAG，验证触发逻辑与故障隔离 |
| **S2 采集** | 双引擎 + 代理池 + 限流 + 增量去重 | 离线 fixture 测试全绿，不联网可跑通 |
| **S3 证据** | 编号白名单 + 拒收重提 + 批次冻结 | 构造编造编号数据，验证被拒收 |
| **S4 评分** | 双标尺 + 扣分溯源 | 构造矛盾卖点数据，验证对齐度扣分 |
| **S5 校准检索** | 主扰动/安慰剂 + 三段式检索 + 时效衰减 | 输出检出率/误判率/p 值 |
| **S6 闭环** | 知识库自更新 + manifest 回放 | 修改历史素材，验证版本可回溯 |

**每阶段交付物**：代码 + 测试 + 《完成度报告》+ 边界测试用例执行结果。**验收通过才进入下一阶段。**

## 六、测试策略

### 6.1 三层测试

| 层级 | 数据来源 | 覆盖目标 |
|---|---|---|
| 采集层 | 本地 HTML 快照 + mock 网络 | 解析、去重、容错、限流 |
| 业务层 | 合成数据（走真实数据访问层） | Agent 链路端到端 |
| 机制验证层 | 构造边界数据 | 拦截逻辑是否生效 |

### 6.2 必须覆盖的边界数据

- 水军/未购评论 → 断言被过滤且落库带原因
- 重复评论 → 断言增量去重生效
- 与卖点矛盾的评论 → 断言对齐度扣分且溯源正确
- 编造编号的模型输出 → 断言被拒收并重提
- 过期竞品素材 → 断言降权归档
- 缺失字段的页面 → 断言爬虫容错不崩溃

**断言原则**：验证"机制是否正确拦截"，而非"流程是否跑通"。

## 七、配置规范

```yaml
# config.yaml（示例，密钥走环境变量）
data_source: seed          # seed | live  ← 切换此项代码无需修改

crawler:
  engine: auto             # scrapy | playwright | auto
  rate_limit: 2
  proxy_pool: ${PROXY_POOL_URL}
  retry_max: 3

llm:
  writer:
    model: qwen-max
    temperature: 0.7
  judge:
    model: glm-4-plus
    temperature: 0         # 禁止修改

retrieval:
  coarse_filter: true      # 禁止设为 false
  top_k: 50
```

## 八、常见问题与应对

| 情况 | 正确做法 | 禁止做法 |
|---|---|---|
| "亚马逊反爬太强，先跳过爬虫" | 用 fixture 驱动测试，代码逻辑照写 | 删掉爬虫模块 |
| "数据是造的，简化一下" | 数据可造，代码路径照写 | 内联数据字典 |
| "两个分数合并更简洁" | 保持独立存储 | 合并成总分 |
| "白名单先打日志观察" | 直接拒收重提 | 打日志放行 |
| "先跑通再说，测试后补" | 测试与代码同交付 | 跳过测试 |
| "这个模块不重要，先不做" | 提交【降级申请】等确认 | 自行删减 |

## 九、交付检查清单

每次交付前自查：

- [ ] 无 `pass  # TODO` / `NotImplementedError` / `# 此处省略`
- [ ] 无内联硬编码数据
- [ ] 无硬编码密钥/模型名/阈值
- [ ] 异常分支已处理，非只有 happy path
- [ ] 核心机制有单元测试，DAG 有集成测试
- [ ] 爬虫有离线 fixture 测试
- [ ] 切换 `data_source` 为 `live` 无需改代码
- [ ] 《完成度报告》四栏已填写
- [ ] 无未声明的降级项

---

## 附：两份文档的分工

- **第一部分（强制约束）** —— 红线清单，用于**验收时挑错**
- **第二部分（开发说明）** —— 实现蓝图，用于**开发时对照**

建议把第二部分第五节（阶段规划）与第九节（检查清单）单独摘出来，作为每轮交付的对照表。

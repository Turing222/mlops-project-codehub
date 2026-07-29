# Pull Request 描述模板

本文定义 Dewflow PR 描述的推荐结构。目标是让 reviewer 快速理解**范围、风险、验证与部署**，而不是复述每个 commit。

配套工具：

- 本地草稿：`make pr-report` → 生成 `logs/pr/` 下的 fact-first checklist（git 状态 + 验证项勾选）
- 提交前验证：[dev-test-flow.md](dev-test-flow.md)、[ci-test-matrix.md](ci-test-matrix.md)
- 大型评审归档（可选）：[../assessments/](../assessments/) — 仅时点快照，**不是每个 PR 的必写项**

---

## 1. 选哪种模板

| 规模 | 适用场景 | 建议长度 |
| --- | --- | --- |
| **小 PR** | 单特性、单 bugfix、文档/脚本小改；通常 &lt;20 文件、无 breaking change | 半屏～1 屏 |
| **大 PR** | 跨模块重构、新子系统、CI/部署体系变更、含迁移或 breaking change | 1～3 屏，分主题小节 |

**默认用小 PR 模板。** 只有 reviewer 需要「地图」才升到大 PR 模板。

---

## 2. 小 PR 模板（日常默认）

复制到 GitHub PR 描述，删掉不适用的章节。

```markdown
## Summary
- （1～2 句：做了什么、为什么）

## Changes
- ...
- ...

## User-visible / product（可选）
- 用户能感知的变化：新页面、新 API、交互/文案/主题等
- 能力边界：例如「仅 README 初筛，非全仓库审计」

## Test plan
- [ ] `make flow-fast`（或更窄的 targeted 命令）
- [ ] `make qa-public-content`
- [ ] （按需）`make security-scan-fast`

## Public content
- [ ] 文档、日志、截图、模板和示例不含真实 secret、生产标识符或未脱敏用户数据

## Deploy / migration
- None
  <!-- 或：`uv run alembic upgrade head`、新 env `FOO=...`、需重建镜像 -->

## Breaking changes
- None
```

### 小 PR 写作要点

- **Summary** 写「用户/运维能感知的结果」，不要堆文件名。
- 有**新产品能力**（新 API + 新页面、新用户旅程）时，用 **User-visible / product** 或在大 PR 里单独一小节写清路径与范围边界，不要只写 CI/基础设施。
- **Test plan** 写**实际跑过的**命令或 CI check 名；没跑过的不要勾选。
- **Public content** 按 [公开内容安全规范](../standards/public-content-safety.md) 检查自动规则无法判断的上下文。
- 没有迁移 / 新 env / 镜像变更时，**Deploy** 和 **Breaking** 写 `None`，不要省略章节（方便 reviewer 扫一眼）。

---

## 3. 大 PR 模板（重构 / 体系变更）

适用于架构升级、前端 v1 首版、CI 门禁大改等。可保留 V2 Backend 那类结构的读者习惯。

```markdown
## 概述
（1 段：本 PR 的目标；可选：commits 数、文件规模、时间跨度）

## 核心变更
### 1. （主题 A）
- ...

### 2. （主题 B）
- ...

### N. 产品能力（若有新功能）
- 用户路径：（从哪进入、完成什么）
- 范围边界：（例如只读 README、不审计全仓代码）
- 依赖：（可选 `GITHUB_TOKEN`、Worker、LLM 等）

## 数据库迁移
- None
  <!-- 或：迁移列表 + 合并后 `uv run alembic upgrade head` -->

## 验证结果
- [ ] （本地或 CI：列 check 名 / `make` 目标 + 结果）
- [ ] `make qa-public-content`

## Public content
- [ ] 文档、日志、截图、模板和示例已经脱敏

## Breaking Changes
- None
  <!-- 或：逐条 + 迁移/配置指引 -->

## 部署注意事项
- None
  <!-- 或：env、镜像 target、外部依赖 -->

## Reviewers 关注点
- ...
```

### 大 PR 写作要点

- **按主题分块**，不要按 commit 或目录字母序罗列。
- **基础设施与产品能力分开写**：CI、部署、安全扫描是一类；新页面、多语言、新 API 垂直功能另起小节，避免 reviewer 误以为「只是工程改动」。
- **验证结果**优先写 GitHub required checks 与关键 `make flow-*`，少贴大段日志。
- **Breaking / Deploy** 单独成节，合并的人最常回看这两块。
- 体量数字（commits、±行数）**可选**；超过 ~30 commits 时有助于设预期。

---

## 4. 与 `make pr-report` 的分工

| 产物 | 位置 | 受众 | 是否入库 |
| --- | --- | --- | --- |
| PR 描述（本文模板） | GitHub PR body | Reviewer、合并者、未来的你 | 随 PR 保留 |
| `make pr-report` | `logs/pr/*.md` |  mainly 自己开 PR 前核对 | 否（`logs/` 已 ignore） |
| `docs/assessments/*.md` | 仓库文档 | 团队存档、评审结论 | 是 |

流程建议：

1. 开发完成 → 跑 [dev-test-flow.md](dev-test-flow.md) 里对应层级的 `make` 目标
2. `make pr-report` 生成本地 checklist（可选）
3. 按本文选小/大模板写 PR 描述
4. 仅当需要留**时点评审快照**时，再写 `assessments/` 文档

---

## 5. 反模式（避免）

- 把 PR 描述写成完整设计文档（设计应在 `docs/` 或 work-item）
- 未跑的测试在 Test plan 里打勾
- 小改动套大 PR 模板，篇幅压倒实质信息
- 大改动只用一行 Summary，让 reviewer 自己翻 100+ commits
- 有新功能却只写「Makefile / workflow 调整」，未说明用户可见变化

# Debug Report Template

Use this template for the read-only investigation report before approval.
Keep the three sections and the approval footer; omit unsupported hypotheses
instead of inventing evidence.

## Debug 侦查报告

### 1. 现场还原

- **故障点**: `文件路径:行号`，或“尚未定位到具体文件”
- **失败层级**: Endpoint / Service / Repository / Worker / Config / Integration / Frontend Component / Frontend Query / Frontend Stream / Frontend Build / Unknown
- **现象**: 简述报错、异常行为或失败命令
- **已检查证据**:
  - `日志 / trace / 文件 / 命令输出`
- **Project skill 约束**:
  - `列出相关约束`
  - 如果没有发现：`未发现可用的 project skill 约束`

### 2. 根因假设

- **假设 A（高/中/低概率）**: 具体假设
  - **依据**: 证据
  - **如何确认**: 下一步只读检查或测试
  - **如何证伪**: 反例或排除条件
- **假设 B（高/中/低概率）**: 具体假设
  - **依据**: 证据
  - **如何确认**: 下一步只读检查或测试
  - **如何证伪**: 反例或排除条件

### 3. 修复与验证方案

- **推荐方案**: 采用假设 A / B / C
- **计划修改**:
  - `文件路径`
  - 具体修改点
- **架构合规性**:
  - 为什么不违反 backend 的 Endpoint / Service / Repository / Worker 分层，或 frontend 的 pages / features / api / streams 分层
- **风险点**:
  - 可能影响的路径或副作用
- **验证方式**:

  ```bash
  # 按故障栈选择，例如：
  make qa-test-unit    # backend
  make frontend-test   # frontend
  ```

---

**等待执行指令**

我目前只完成了只读排查，没有修改任何文件。

请确认上述方向。如果合理，请回复“继续”、“LGTM”、“可以修改”，或指定采用哪个假设。收到明确批准后，我再开始修改代码。

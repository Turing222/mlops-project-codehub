# 公开内容安全规范

Dewflow 仓库是公开仓库。代码、文档、测试、模板、示例、`work-items/` 和 Git
历史都属于公开内容，不能依赖目录名获得 secret 扫描豁免。

## 1. 基本原则

1. 数据库密码、API token、私钥、session、cookie 和长期凭据不得提交。
2. AWS、Cloudflare、生产数据库等真实资源标识符使用占位符。
3. 架构和操作流程可以公开，但生产地址、账号、租户、资源拓扑和未修复漏洞细节需要脱敏。
4. CI、测试和文档示例只能使用确定性的假值，且必须通过自动检查。
5. 凭据一旦进入公开 Git 历史即视为泄漏；删除文件或后续提交不能替代轮换。

## 2. 占位符约定

| 内容 | 推荐写法 |
| --- | --- |
| AWS account | `<AWS_ACCOUNT_ID>` |
| EC2 instance | `<EC2_INSTANCE_ID>` |
| VPC / subnet / security group | `<VPC_ID>` / `<SUBNET_ID>` / `<SECURITY_GROUP_ID>` |
| RDS endpoint | `<RDS_ENDPOINT>` |
| Cloudflare Tunnel | `<TUNNEL_ID>` |
| API hostname | `api.example.com` |
| 文档 IPv4 | RFC 5737 地址，例如 `192.0.2.10` |
| secret / token | `<SECRET>` / `<API_TOKEN>`，不要模拟真实 provider 格式 |

变量名、命令结构和配置字段可以保留；真实值应放在 GitHub Secrets、repository
variables、SSM Parameter Store 或部署主机的 `secrets/<env>/`。

## 3. 必须人工检查的内容

自动规则不能可靠判断所有上下文。提交前还要检查：

- 日志是否包含 header、query string、cookie、用户输入、邮箱、手机号或内部 ID；
- 截图是否包含账号、域名、浏览器地址栏、云控制台资源 ID、通知或 EXIF metadata；
- runbook 是否暴露生产域名、IP、账号 ID、Tunnel ID、VPC 拓扑或接收人信息；
- assessment 和 `work-items/` 是否复制了真实 incident、命令输出或第三方响应；
- 未修复漏洞是否包含可以直接利用的路径、payload 或生产目标信息。

不能确认是否可公开时，先保留结构并替换值；高风险漏洞细节等修复完成后再公开。

## 4. 自动门禁

本地快速检查：

```bash
make qa-public-content
```

它执行：

- 项目特有部署标识符检查；
- Gitleaks 配置与 `.gitleaksignore` 精确度检查。

PR 上的 `Public content safety` 还会：

- 生成 synthetic secret，验证 `docs/` 没有被排除；
- 使用 Gitleaks 扫描完整 Git 历史。

该 check 必须是 `main` branch protection 的 required check。GitHub Secret
Scanning push protection 继续作为 push 前的外部防线。

## 5. 误报处理

发现误报时按以下顺序处理：

1. 优先把示例改成明确占位符。
2. 必须保留的测试固件使用不会被误认为真实 provider token 的结构。
3. 历史冻结内容只能在确认是假值后，加入 commit-scoped
   `.gitleaksignore` fingerprint。
4. 新增 Gitleaks allowlist 时必须同时限定 `targetRules`、精确 `paths` 和
   value regex/stopword，并使用 `condition = "AND"`。

禁止放行整个 `docs/`、`tests/`、`work-items/`、`evals/`、`perf/`、模板或示例目录。
不得为了让 CI 变绿而放行无法确认来源的值。

## 6. 真实泄漏响应

如果发现可能真实的凭据或资源标识符：

1. 停止复制该值，不把它粘贴到 PR、Issue、聊天或日志。
2. 立即在对应 provider 轮换或撤销凭据。
3. 用占位符替换仓库内容，并执行完整历史扫描。
4. 单独评估是否需要历史重写；公开仓库中的历史重写不能使已泄漏凭据重新安全。
5. 记录影响范围和轮换完成状态，但不记录 secret 原文。

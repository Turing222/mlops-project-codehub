# 前端 CI/CD 评估

> 日期：2026-06-14
> 范围：`frontend/apps/admin` 的 CI 覆盖与 Cloudflare Pages 交付模型
> 性质：时点评估，包含 §8/§9 的后续落地记录
> 证据基线：分支 `feat/frontend-v1`、workflow、`Makefile` frontend targets 与相关 platform 文档
> 状态：冻结；现行交付约定以 `docs/platform/` 和 `.github/workflows/` 为准

## 1. 拓扑概览

- **仓库形态**：monorepo。前端是 pnpm workspace，唯一应用 `frontend/apps/admin`（React 19 / Vite 7 / TS）。
- **CI（GitHub Actions）**：5 个 workflow，前端覆盖分散在其中 3 个。
- **CD（部署）**：**不在仓库 CI 内**。前端走 **Cloudflare Pages + GitHub 集成**，Pages Dashboard 配置是 source of truth（`docs/platform/deploy-ec2.md:69`）。push 到 production branch 时 Pages **立即**构建发布。
- **版本钉住**：Node 由 `frontend/.nvmrc`（22）决定，pnpm 由 `frontend/package.json` 的 `packageManager`（`pnpm@10.28.2`，corepack）决定；CI 与 Pages 构建读同一来源，避免漂移（`docs/platform/deploy-ec2.md:80`）。
- **fallback 入口**：`frontend/apps/admin/Dockerfile` + `nginx.conf` 仅用于本地演练、镜像验证、Pages 回滚 fallback（`frontend-fallback` profile），不再是公网默认入口。

## 2. 前端在各 Workflow 中的覆盖矩阵

| Workflow | 触发 | 前端相关 job / 步骤 | 说明 |
| --- | --- | --- | --- |
| `static-ci.yml` | push `main`/`master` + **所有 PR** | `frontend-static`：lint → typecheck → unit test → build → **bundle-check** | 前端静态门禁主力；无 paths 过滤 |
| `pr-gate-ci.yml` | `pull_request`（非 draft）+ dispatch | `pr-gate` 末段：**frontend-e2e-mock**（Playwright，装 Chromium） | 仅 PR 跑；**push main 不跑** |
| `security-ci.yml` | push + 指定 paths PR + 周一 cron | `frontend-dependencies`：`pnpm audit`（prod=high / dev=critical，registry 钉死）；`frontend-image`：构建 fallback 镜像 + trivy 扫描 | 依赖与镜像漏洞 |
| `deploy-validate-ci.yml` | `deploy/**` 等 paths PR | compose `--profile frontend-fallback config -q` 校验 + 构建 frontend image | 仅校验 fallback 资产，不测 SPA |
| `smoke-ci.yml` | Docker/compose paths | Docker 全栈冒烟（后端为主） | **前端 SPA 不在其中** |

**结论**：真正约束前端代码质量的是 `static-ci`（全 PR）+ `pr-gate` 的 e2e-mock（仅 PR）。安全扫描由 `security-ci` 兜底。**没有任何 workflow 对真实后端跑前端 e2e 冒烟**。

## 3. 逐项检查点评估

### 3.1 Lint / Typecheck（`frontend-lint` / `frontend-typecheck`）
- `eslint .` + `tsc -b --pretty false`。标准静态门禁，覆盖全 PR。**OK**。

### 3.2 单元测试（`frontend-test` = `vitest run`）
- 在全 PR 跑。`vitest.config.ts` 单线程/单 fork、jsdom、30s 超时。
- **缺口**：未配置 `coverage`，**没有覆盖率门禁**。测试是否充分完全靠人审，回归保护强度不可度量。

### 3.3 构建（`frontend-build`）
- `tsc -b && vite build && node scripts/generate-pages-headers.mjs`。
- 构建附带生成 `dist/_headers`（CSP report-only），并依赖 `VITE_API_BASE_URL`；缺失时 Pages 构建会失败以避免静默漏启 CSP（`frontend-delivery...md:88-89`）。**设计良好**。
- **注意**：CI 的 build 步骤**不注入 `VITE_API_BASE_URL`**，走同源 fallback 分支。即 CI 构建的产物与 Pages 生产构建（带真实 API origin、真实 `report-uri`）**不是同一形态**——`dist/_headers` 占位符校验路径在 CI 未被真正演练。

### 3.4 Bundle 体积（`frontend-bundle-check`）
- 对 `dist/assets/*.{js,css}` 做 gzip 求和，与 `bundle-baseline.json`（当前 469212 B ≈ 458 KiB）比较，容差 **±10%**。
- 脚本有防呆：baseline 非法/产物为空会 fail（`check-bundle-size.mjs:31,67`）。**OK**。
- **缺口**：这是**相对**门禁而非绝对预算。baseline 提交在仓库，每次 `--update` 刷新即抬高基线 → 体积可被"温水煮青蛙"式逐步放大，单次 +10% 不报警。

### 3.5 e2e-mock（Playwright，`pr-gate-ci.yml`）
- 仅 `pull_request`（非 draft）跑，装 `--with-deps chromium`，MSW mock 后端。
- `playwright.config.ts`：CI 下 `retries: 2`、`workers: 1`、reporter `github`。
- **缺口 a**：**push 到 main 不跑 e2e-mock**（pr-gate 不监听 push）。绕过 PR 直推 main 时这层保护缺席。
- **缺口 b**：`retries: 2` 会掩盖 flaky；CI 无 trace/report artifact 上传（仅 `trace: on-first-retry` 本地留存，未 upload-artifact），失败排查证据不落盘。

### 3.6 e2e-smoke（真实后端）
- `test:e2e:smoke` 存在（`make frontend-e2e-smoke`，需 `E2E_SMOKE_USER/PASS`），但**不在任何 workflow 中**，仅手动。
- **缺口**：前端对真实 API 契约的回归只能靠人记得手动跑，CI 无强制。

### 3.7 依赖安全（`security-ci.yml` → `frontend-dependencies`）
- `pnpm audit` prod=high / dev=critical，registry 钉死到 npmjs（镜像源常缺 audit endpoint）。周一 cron + 相关 paths PR。**思路清晰**。
- **缺口**：仅 advisory audit，无 SBOM / 许可证扫描；阈值（dev 仅 critical）对开发链漏洞较宽松。

### 3.8 镜像安全（`frontend-image`）
- 构建 fallback 镜像 + trivy（HIGH/CRITICAL、`ignore-unfixed`、`exit-code 1`）。覆盖了**其它 workflow 都不构建的回滚镜像**。**好**。

### 3.9 部署资产校验（`deploy-validate-ci.yml`）
- 仅 `docker compose ... config -q` 与镜像构建，校验 `frontend-fallback` profile 可解析。**不验证 Pages 产物 / SPA 行为**。

### 3.10 供应链与 runner 卫生（横向）
- 所有 `uses:` **全部 pin 到 commit SHA**（actions/checkout、setup-node、pnpm/action-setup、trivy 等）。**优秀**。
- `permissions: contents: read` 最小化；`concurrency` + `cancel-in-progress`（PR 上）合理省算力。**优秀**。
- 依赖更新：`dependabot.yml` 覆盖 npm(`/frontend`)、frontend Dockerfile docker、github-actions，周更。**OK**。

## 4. CD / 部署模型评估

### 4.1 部署机制
- Cloudflare Pages GitHub 集成：push 到 production branch **立即并行**构建发布，**与 GitHub CI 解耦**——**CI 失败不会阻止 Pages 发布**（`docs/platform/deploy-ec2.md:84`）。
- 每个 PR 自动生成 Preview 部署（Pages 默认行为，`VITE_API_BASE_URL` Preview 缺失时 `CF_PAGES=1` 构建会 fail）。

### 4.2 部署 gate 完全依赖 branch protection（核心风险）
- 因为 Pages 不看 CI 结果，gate 必须前移到**合并时**：`main` 的 branch protection 需 Require status checks，required 至少含 `Backend static`、`Frontend static`、`PR gate`（`docs/platform/deploy-ec2.md:86-88`）。
- **风险**：该规则配置在 GitHub Settings，**不在仓库内、CI 无法自验**。一旦没配/被改：
  - 任何直推 `main` 的代码在 CI 出结果前就已发布到生产 Pages（`docs/platform/deploy-ec2.md:90`）。
  - 直推 main 还会**绕过 `pr-gate` 的 e2e-mock**（pr-gate 不监听 push），未经 e2e 的产物可直接上线。
- 仓库中无任何机制（如 ruleset-as-code / 校验脚本）证明保护规则现存且正确。

### 4.3 部署后验证（`verify-pages`）
- `make verify-pages` 脚本化检查 CORS、CSP report-only header、telemetry/CSP report origin 守卫（`docs/platform/deploy-ec2.md:94-98`）。
- **缺口**：是**手动**部署后检查，**未接入任何自动化 post-deploy 流程**。Pages 发布后没有自动冒烟，回归只在有人手动跑时才被发现。

### 4.4 回滚
- 首选 Cloudflare Dashboard 回退上一条成功 deployment；Pages 故障时才启用 `frontend-fallback` 容器镜像（`docs/platform/deploy-ec2.md:336`）。
- 回滚是**手动 Dashboard 操作**，无脚本化/演练入口；fallback 镜像 tag（`DOCKER_IMAGE_NAME_FRONTEND`）需手工维护。

### 4.5 CI 与 Pages 构建的一致性
- 版本（Node/pnpm）两边同源，**好**。
- 但 CI build **不带 `VITE_API_BASE_URL`**，与 Pages 生产 build 的产物形态不同（见 3.3）；生产专属的 `dist/_headers` 真值与占位符校验在 CI 未演练。

## 5. 做得好的地方

1. Action 全部 SHA pin + 最小 `permissions` + 合理 `concurrency`，供应链与算力卫生到位。
2. Node/pnpm 版本单一来源（`.nvmrc` + `packageManager` + corepack），CI 与 Pages 不漂移。
3. 安全分层清晰：依赖 audit（registry 钉死）+ 镜像 trivy + 覆盖到他处不构建的 fallback 镜像 + 周一 cron + dependabot。
4. bundle-check 有防呆（非法 baseline / 空产物即 fail），不会静默放行。
5. 构建强制 `VITE_API_BASE_URL`、CSP report-only 产物化并校验占位符，杜绝生产静默漏启。
6. 部署职责边界（Pages vs API origin）有专文说明，避免拿已删除的 legacy nginx 当生产入口。

## 6. 风险与差距（按优先级）

| # | 严重度 | 问题 | 证据 | 状态 |
| --- | --- | --- | --- | --- |
| R1 | **高** | 部署 gate 仅靠 GitHub branch protection 人工配置，仓库无法自验；缺失即"CI 未过先上线" | `deploy-ec2.md:84-90` | workflow 已落地(§8.1)，待补 PAT secret |
| R2 | **高** | 无对真实后端的前端 e2e 冒烟门禁（`e2e-smoke` 仅手动）；API 契约回归无自动捕获 | `package.json:16`、各 workflow | workflow 已落地(§8.2)，待补凭据 secret |
| R3 | 中 | 无 Pages 发布后的自动 post-deploy 冒烟；`verify-pages` 纯手动 | `deploy-ec2.md:94-98` | 已自动化 `verify-pages`(§8.3/§9.4)；线上 e2e 待 fixture 改造 |
| R4 | 中 | 直推 `main` 绕过 `pr-gate`（e2e-mock 不在 push 触发） | `pr-gate-ci.yml:3-6` | 缓解：R2 workflow 加了 `push:[main]` |
| R5 | 中 | 前端单测无 coverage 门禁，回归保护强度不可度量 | `vitest.config.ts` | 已可度量 + 正式门禁（§9.1）；floor 阈值在 CI 阻断 |
| R6 | 低 | bundle-check 是相对 baseline（±10%），可被多次刷新逐步放大 | `check-bundle-size.mjs:75` | 已加绝对硬上限(§9.3) |
| R7 | 低 | e2e-mock `retries:2` 掩盖 flaky，且 trace/report 未 upload-artifact，失败证据不落盘 | `playwright.config.ts:7` | 部分：R2 smoke 上传 report；mock e2e 仍未传 |
| R8 | 低 | CI build 与 Pages 生产 build 产物形态不同（无 `VITE_API_BASE_URL`），生产 `_headers` 真值未在 CI 演练 | 见 3.3 / 3.5 | 已演练(§9.2) |

## 7. 建议（按性价比）

1. **R1 → 把部署 gate 显式化**：在仓库内放 GitHub ruleset-as-code 或一条校验 required checks 是否启用的定时 job，让"保护规则存在"可被审计；并在 README/deploy 文档置顶该前提。
2. **R2 + R3 → 加一条 Pages 发布后的自动冒烟**：用 Pages "deployment success" webhook / `deployment_status` 触发 workflow，对生产/Preview URL 跑 `verify-pages` + 一组只读 `e2e-smoke`（凭据走 GitHub Secrets）。把人工检查变成自动门禁。
3. **R4 → 给 `pr-gate` 或单独 job 加 `push: [main]` 触发**（或在 branch protection 里禁止直推 main），消除绕过路径。
4. **R5 → 开启 vitest `coverage`** 并设一个起步阈值（哪怕先 lines 60% 防退化），纳入 `frontend-static`。
5. **R7 → e2e 失败时 `upload-artifact` 上传 `playwright-report/` 与 trace**；视情况把 `retries` 降到 1 以暴露 flaky。
6. **R8 → 在 `frontend-static` 增加一次带 `VITE_API_BASE_URL` 的生产形态 build**，并断言 `dist/_headers` 含真实 `report-uri`、无占位符。
7. **R6（可选）→ bundle-check 增设一个绝对硬上限**作为第二道闸，防 baseline 漂移。

---

## 8. R1 / R2 落地实现

> 以下两个 workflow **已落地**到 `.github/workflows/`：`guard-branch-protection.yml`、`frontend-e2e-smoke-ci.yml`。Action 均沿用仓库现有的 commit SHA pin，保持供应链卫生一致。
> 仍需在仓库设置侧补两类 secret 才能真正生效（见各自「前置依赖」），首次运行请观察实际结果。

> **关于 "proxy 口径" 的更正**：早期草稿曾把 vite proxy strip `/api` 当成 smoke 没进 CI 的"集成障碍"。落地核查后确认**这是误判，proxy 无需修改**。后端真实 ASGI 路由是 `/v1/...`（`backend/config/web_settings.py`：`API_ROOT_PATH="/api"` + `API_V1_STR="/v1"`，`backend/main.py` 以 `root_path="/api"` 起 + router `prefix="/v1"`）。因此：
> - dev：`/api/v1/x` → vite strip `/api` → 后端命中 `/v1/x`；
> - compose/生产：`/api/v1/x` → 后端 `root_path=/api` 再剥一层 → 命中 `/v1/x`。
>
> 两条链路都收敛到 `/v1` 路由，当前 proxy 是**正确**的；改它反而会引入风险。smoke 没进 CI 的真实原因只是**从没有人把"真实后端 + seed"接进 workflow**，与 proxy 无关。

### 8.1 R1 — 让"部署 gate 存在"可被审计

**思路**：因为 Cloudflare Pages 不看 CI 结果，唯一的部署闸是 GitHub branch protection 的 required checks（`Backend static` / `Frontend static` / `PR gate`）。该配置在仓库外、无法 review。用一个定时 + 手动的 workflow 通过 GitHub API **回读** `main` 的 required checks，缺失即 fail，把"闸还在不在"变成可观测信号。

**前置依赖**：
- 默认 `GITHUB_TOKEN` **无权**读取 branch protection（需 admin 级）。要建一个 fine-grained PAT，仅授 `Administration: Read`，存为 secret `BRANCH_PROTECTION_READ_TOKEN`。
- 若用的是 **rulesets** 而非 classic protection，把 `gh api` 换成 `repos/{repo}/rulesets`（见末尾注释）。

```yaml
# .github/workflows/guard-branch-protection.yml
name: Guard Branch Protection

on:
  schedule:
    - cron: "0 8 * * 1" # 周一 08:00 UTC
  workflow_dispatch:

permissions:
  contents: read

jobs:
  verify-required-checks:
    name: Verify main required checks
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - name: Assert required status checks on main
        env:
          GH_TOKEN: ${{ secrets.BRANCH_PROTECTION_READ_TOKEN }}
          REPO: ${{ github.repository }}
        run: |
          set -euo pipefail

          # 期望的 required checks —— 与 docs/platform/deploy-ec2.md 的部署 gate 清单保持同源。
          expected='Backend static
          Frontend static
          PR gate'

          # 读取 classic branch protection 的 required status checks。
          actual="$(gh api "repos/$REPO/branches/main/protection/required_status_checks" \
            --jq '.checks[].context' 2>/dev/null || true)"

          if [ -z "$actual" ]; then
            echo "::error::main 上没有 required status checks（branch protection 缺失，或 token 无 Administration:Read）。"
            echo "::error::任何直推 main 的代码会在 CI 出结果前就发布到生产 Pages。"
            exit 1
          fi

          echo "当前已配置的 required checks："
          echo "$actual" | sed 's/^/  - /'

          missing=0
          while IFS= read -r ctx; do
            ctx="$(echo "$ctx" | sed 's/^[[:space:]]*//')"
            [ -z "$ctx" ] && continue
            if ! grep -Fxq "$ctx" <<<"$actual"; then
              echo "::error::缺少必需的 required check：$ctx"
              missing=1
            fi
          done <<<"$expected"

          exit "$missing"

# rulesets 变体：把上面的 gh api 调用替换为
#   gh api "repos/$REPO/rulesets" --jq '.[] | select(.target=="branch") | .name'
# 再按需读取单个 ruleset 的 required_status_checks 规则。
```

**收益**：R1 从"靠人记得配"变成每周自动巡检 + 可手动触发；闸被改动会立刻告警（job 红）。

---

### 8.2 R2 — 对真实后端的前端 e2e-smoke 门禁

**smoke 的真实运行模型（已核实）**：`make frontend-e2e-smoke` → Playwright（`E2E_SMOKE=1`，project=smoke）→ 启本地 Vite dev server(5173) → 用 `E2E_SMOKE_USER/PASS` 调 `/api/v1/auth/login`（`fixtures/smoke-auth.ts`）→ 跑 `real-login / real-chat / real-credits`。因此 CI 需要：**真实后端 API + TaskIQ worker**（`real-chat` 的流式 chunk 由 worker 经 Redis 发布）+ **可登录的 smoke 用户**。Fork PR 读不到 repository secrets，workflow 会 skip。

**前置依赖（生效前必须补齐）**：
1. **smoke 凭据 secret**：`scripts/seed/dev_seed.py` 造的 `seed_member` 共用常量 `SEED_PASSWORD = "SeedPass123!"`。在仓库 Settings → Secrets 配 `E2E_SMOKE_USER=seed_member`、`E2E_SMOKE_PASS=SeedPass123!`，并与 seed 脚本保持同步（脚本改密码时同步改 secret）。
2. **路由口径（已核实正确，无需改 proxy）**：vite proxy strip `/api` 后转发到 `:8000`，命中后端真实路由 `/v1/...`（见 §8 顶部更正）。health wait 用 `/api/v1/health_check/live` 与 compose 约定一致。
3. **首跑校验项**：`uv run alembic upgrade head` 与 `make seed-dev` 在 CI 环境（`DATABASE_URL` 注入、`settings.py:131` 优先用它）下的连库行为；`real-chat` 在 `LLM_PROVIDER=mock`/`RAG_EMBED_PROVIDER=mock` 下的流式输出。三者均沿用仓库已验证的 env 口径，但首次运行建议盯一次日志确认。

```yaml
# .github/workflows/frontend-e2e-smoke-ci.yml
name: Frontend E2E Smoke CI

on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
  push:
    branches: [main, master]
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: fe-smoke-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  frontend-e2e-smoke:
    if: ${{ github.event_name != 'pull_request' || github.event.pull_request.draft == false }}
    name: Frontend e2e smoke (real backend)
    runs-on: ubuntu-latest
    timeout-minutes: 25

    services:
      postgres:
        image: pgvector/pgvector:pg17
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: dewflow_test
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U postgres -d dewflow_test"
          --health-interval 10s --health-timeout 5s --health-retries 5
      redis:
        image: redis:7
        ports: ["6379:6379"]
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s --health-timeout 5s --health-retries 5

    env:
      APP_ENV: test
      SECRET_KEY: ci-test-secret-key-with-at-least-32-chars
      DATABASE_URL: postgresql+asyncpg://postgres:postgres@localhost:5432/dewflow_test
      REDIS_URL: redis://localhost:6379/0
      TASKIQ_REDIS_URL: redis://localhost:6379/1
      POSTGRES_SSL_MODE: disable
      # 用 mock provider，避免 smoke 依赖真实 LLM / embedding 配额
      # （与 smoke-ci 的 `make set-llm PROVIDER=mock EMBED_PROVIDER=mock` 等价）。
      LLM_PROVIDER: mock
      RAG_EMBED_PROVIDER: mock

    steps:
      - name: Checkout repository
        uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6

      # ---- 后端：装依赖 → 迁移 → seed → 后台起 API(:8000) ----
      - name: Set up Python
        uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405 # v6
        with:
          python-version: "3.12"

      - name: Install uv
        run: python -m pip install --upgrade pip uv

      - name: Cache Python virtualenv
        uses: actions/cache@0057852bfaa89a56745cba8c7296529d2fc39830 # v4
        with:
          path: .venv
          key: uv-${{ runner.os }}-py312-${{ hashFiles('uv.lock') }}-${{ hashFiles('pyproject.toml') }}
          restore-keys: |
            uv-${{ runner.os }}-py312-

      - name: Sync Python dependencies
        run: uv sync --frozen --dev --all-extras

      - name: Run DB migrations
        run: uv run alembic upgrade head

      - name: Seed smoke user
        run: make seed-dev

      - name: Launch backend API and TaskIQ worker
        run: |
          uv run uvicorn backend.main:app --host 127.0.0.1 --port 8000 \
            > /tmp/api.log 2>&1 &
          uv run taskiq worker backend.infra.task_broker:broker \
            backend.worker.tasks.llm_tasks backend.worker.tasks.knowledge_tasks \
            backend.worker.tasks.repo_analysis_tasks backend.worker.tasks.credit_tasks \
            --workers 1 \
            > /tmp/worker.log 2>&1 &

      - name: Wait for API health
        run: |
          for i in $(seq 1 30); do
            if curl -sf http://127.0.0.1:8000/api/v1/health_check/live; then
              echo "API up"; exit 0
            fi
            sleep 2
          done
          echo "::error::API 未在超时内就绪"; cat /tmp/api.log; exit 1

      - name: Wait for TaskIQ worker
        env:
          TASKIQ_HEALTH_MIN_PROCESSES: "1"
        run: |
          for i in $(seq 1 30); do
            if uv run python -m backend.worker.tasks.healthcheck; then
              echo "TaskIQ worker up"; exit 0
            fi
            sleep 2
          done
          echo "::error::TaskIQ worker 未在超时内就绪"; cat /tmp/worker.log; exit 1

      # ---- 前端：装依赖 → 装 Chromium → 跑 smoke ----
      - name: Set up pnpm
        uses: pnpm/action-setup@b906affcce14559ad1aafd4ab0e942779e9f58b1 # v4
        with:
          package_json_file: frontend/package.json

      - name: Set up Node.js
        uses: actions/setup-node@48b55a011bda9f5d6aeb4c2d9c7362e8dae4041e # v6
        with:
          node-version-file: frontend/.nvmrc
          cache: "pnpm"
          cache-dependency-path: frontend/pnpm-lock.yaml

      - name: Install frontend dependencies
        run: pnpm --dir frontend install --frozen-lockfile

      - name: Install Playwright Chromium
        run: pnpm --dir frontend --filter admin exec playwright install --with-deps chromium

      - name: Run frontend e2e smoke
        env:
          E2E_SMOKE_USER: ${{ secrets.E2E_SMOKE_USER }}
          E2E_SMOKE_PASS: ${{ secrets.E2E_SMOKE_PASS }}
        run: make frontend-e2e-smoke

      - name: Upload Playwright report on failure
        if: failure()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        with:
          name: e2e-smoke-report
          path: |
            frontend/apps/admin/playwright-report/**
            frontend/apps/admin/test-results/**
          if-no-files-found: ignore

      - name: Dump API log on failure
        if: failure()
        run: cat /tmp/api.log || true

      - name: Dump worker log on failure
        if: failure()
        run: cat /tmp/worker.log || true
```

**与现有 workflow 的关系**：
- 结构刻意对齐 `pr-gate-ci.yml`（同样的 Postgres/Redis services 与 env），便于 review 与维护。
- 顺带消化 **R7**：失败时 `upload-artifact` 上传 `playwright-report/` 与 `test-results/`，e2e 失败证据落盘。
- 加了 `push: [main]` 触发，同时缓解 **R4**（直推 main 不再完全无 e2e 覆盖）。

**关于 R2/R3 的 post-deploy 变体**：见 §8.3。`playwright.config.ts` 的 `webServer` 已改为条件式（检测到非 localhost 的 `E2E_BASE_URL` 时跳过本地 dev server），为"线上浏览器 e2e"解锁了一半；但 smoke fixture 目前用相对 `/api/v1/...` 打前端 origin，依赖同源 `/api` 反代。在 split-origin 的 Pages 拓扑下，登录请求需指向独立 API origin —— 这块 fixture 改造留作 R3 的后续项。

### 8.3 R3 — Pages 发布后自动校验（`post-deploy-pages-verify.yml`）

**已落地**。`on: deployment_status`（生产部署成功后）+ `workflow_dispatch`，自动跑 `make verify-pages`（CORS / CSP report-only header / telemetry / CSP report origin 守卫；split-origin 感知的纯 bash+curl 脚本），把原先纯手动的发布后检查自动化。

**前置依赖**：
- 配仓库 Variables `DEPLOY_FRONTEND_BASE_URL`、`DEPLOY_BASE_URL`（手动触发也可用 inputs 传）。
- Cloudflare 的 `deployment_status.environment` 命名（`Production`/`production`）需在首个真实 payload 上确认，必要时调整 `if` 过滤。
- 完整"线上浏览器 e2e"还需上面提到的 smoke fixture API-origin 改造（后续项）。

## 9. 剩余风险收尾（R3 / R5 / R6 / R8 实现）

本轮按评估 §6 依次收尾了 R3、R5、R6、R8。R1/R2 见 §8。

### 9.1 R5 — 前端单测覆盖率可度量
- `frontend/apps/admin/vitest.config.ts` 加 `coverage`（provider v8，reporter text-summary/json-summary/html/lcov，`include: src/**/*.{ts,tsx}` 全量口径）。
- 新增 `test:coverage` 脚本、`make frontend-test-coverage`；`static-ci.yml` 的 `frontend-static` 跑覆盖率并上传 `frontend-coverage` artifact（**正式门禁**，floor 阈值在 `vitest.config.ts`）。
- **实测基线（全量口径）**：Statements 45.17% / Branches 36.72% / Functions 41.46% / Lines 45.97%（197 测试全过）。注意这低于"只算被测文件"的口径（那个口径 ~68%），因为全量口径把未被测模块也计入分母——这才是真实的回归信号。
- **下限（floor）**：statements 40 / branches 30 / functions 35 / lines 40，设在实测下方留余量；非追逐目标，与 `testing.md` 一致。
- **teardown 竞态（已解决）**：v8 插桩曾暴露 React 19 scheduler 经 Node `setImmediate` 在 jsdom 拆环境后触发的 late teardown（`ReferenceError: window is not defined`）；与 `streaming-contract` / `admin-users-contract` 无关（它们不渲染组件）。修复：`src/test/setup.ts` 禁用 RTL 自动 cleanup、在 `act(cleanup)` 内 flush setImmediate；`vitest.config.ts` 设 `RTL_SKIP_AUTO_CLEANUP` 与 `fileParallelism: false`。`static-ci.yml` 已去掉 coverage 步骤的 `continue-on-error`。

### 9.2 R8 — 生产形态构建在 CI 演练
- 新增 `make frontend-build-pages-check`：以 `CF_PAGES=1` + `VITE_API_BASE_URL=https://api.example.com` 构建，断言 `dist/_headers` 含 `Content-Security-Policy-Report-Only` 与真实 `report-uri .../api/v1/csp/reports`、无 `<domain>` 占位符。
- 接入 `static-ci.yml` 的 `frontend-static`（末步运行，因为它会用生产形态产物覆盖 `dist/`）。本地实测通过。

### 9.3 R6 — bundle 体积绝对硬上限
- `check-bundle-size.mjs` 增加 `absoluteMaxGzipBytes` 兜底:独立于（可刷新的）baseline，超过即 fail，且 `--update` 不会改动它——防止反复 `--update` 把预算无限抬高。
- `bundle-baseline.json` 设 `absoluteMaxGzipBytes: 573440`（560 KiB，约当前 458 KiB 的 +22%，在相对 +10% 限值 ~504 KiB 之上做硬顶）。本地实测通过。

### 9.4 R3 — Pages 发布后自动校验
- 见 §8.3：`post-deploy-pages-verify.yml` 已落地（核心自动化），webServer 已条件化；split-origin 线上浏览器 e2e 的 fixture 改造为后续项。

### 9.5 验证
- 4 个 workflow `yaml.safe_load` 通过；`make frontend-typecheck` / `frontend-lint` exit 0（仅 1 条既有 `GoogleCallbackPage.tsx` warning，与本次无关）。
- `make frontend-build-pages-check`、`make frontend-bundle-check` 本地 exit 0；coverage thresholds 通过（实测高于下限）。

### 9.6 已知遗留（独立后续项，非本轮范围）
- split-origin 下 smoke fixture 的 API-origin 改造（阻碍线上浏览器 e2e）。
- R1（branch protection 巡检）/ R2（前端 e2e-smoke）需要在仓库设置侧补 secret / Variables 才真正生效（见 §8.1 / §8.2）。

## Change Summary
**What**: 依次收尾 R5/R8/R6/R3：加前端覆盖率（report-only + floor）、CI 生产形态构建校验、bundle 绝对硬上限、Pages 发布后自动 `verify-pages` workflow，并条件化 Playwright webServer。
**Why**: R5 与 `testing.md` 反对"刷数字"的立场调和为"可度量 + 防回归下限"，且因 v8 插桩暴露的 teardown 竞态先做 report-only；如实记录全量覆盖率基线与遗留后续项。
**Affected**: `vitest.config.ts`、`package.json`、`Makefile`、`scripts/check-bundle-size.mjs`、`bundle-baseline.json`、`e2e/playwright.config.ts`、`.github/workflows/{static-ci,post-deploy-pages-verify}.yml`、`frontend/docs/standards/testing.md`、本评估文档

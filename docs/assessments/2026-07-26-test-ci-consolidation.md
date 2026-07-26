# 测试与 CI 整理(2026-07-26 治理周期后)

> 日期：2026-07-26
> 范围：CI workflow、合并门禁、测试基建、依赖与安全扫描、bot（dependabot / Devin Review）
> 性质：时点整理。基于当日 PR #53–#69 连续落地过程中实际暴露的故障与修复，不是理论审计
> 证据基线：`main` @ 89e8335、`.github/workflows/`、`Makefile`、`pyproject.toml`、`frontend/apps/admin/vitest.config.ts`
> 状态：快照；现行约定以 [ci-test-matrix.md](../workflows/ci-test-matrix.md) 与 workflow 文件为准

## 1. 结论速览

- [ci-test-matrix.md](../workflows/ci-test-matrix.md) §8 路线图中的 **P0(secrets)与 P1(branch protection 五项 required)于本日全部落地**,部署闸门从设计变为现实;P2(smoke 加深)、P3(准生产 CI)未动。
- Security CI 四个扫描 job **首次全绿**(此前 25 次运行 23 红):清掉 pip-audit 7 漏洞 / pnpm audit 4 high / 前端镜像 9 HIGH,并留档 1 条不适用豁免。
- 一天内 17 个 PR 的实操压出 8 类问题,全部修复并沉淀为原则(§3);遗留缺口按优先级列于 §5。
- 两条结构性认知:**required check 不得带路径过滤**;**依赖更新策略(dependabot ignore)不等于安全可见性**(alerts 已开启兜底)。

## 2. 门禁状态:本日前后对照

| 维度 | 之前 | 之后 |
| --- | --- | --- |
| main branch protection | 无(Guard 周检常红) | 5 required checks + `enforce_admins`,直推被拒 |
| `BRANCH_PROTECTION_READ_TOKEN` | 未配置 | 已配置,Guard 转绿 |
| Security CI | 23/25 次失败,无人能修(修复版本在 dependabot 盲区) | 全绿;豁免与推迟均留档 |
| smoke-ci PR 触发 | path 过滤(纯配置 PR 会 BLOCKED 卡死) | 全 PR 无条件运行 |
| PR gate 测试库 | 从未执行迁移(requires_db 集成测试撞空库) | `uv run alembic upgrade head` 前置步骤 |
| dependabot | 14 个散装 PR 积压、配额占满 | groups patch-only + alerts;周常产出 1–3 个分组 PR |
| Open PR 数 | 14 | 0 |

## 3. 本周期暴露的问题与沉淀原则

按发现顺序;每条为「现象 → 根因 → 修复 → 原则」。

1. **required check 因路径过滤永不上报,合并死锁**(smoke-ci;dependabot.yml 纯配置 PR 实测 BLOCKED)。修复:去掉 `pull_request.paths`。原则:**列入 required 的 check 必须在所有 PR 上无条件上报**;单次 ~2 min 的成本换确定性。[2026-07-17 评估](2026-07-17-identity-governance-test-ci-quality.md) §5.3 预警过的触发冲突类问题,本次实锤。
2. **集成测试的环境假设无人兑现**(probe 测试自述"验证 migrated DB",但 pr-gate-ci 无迁移步骤;分支首次过 CI 即撞 `UndefinedTableError`)。修复:`qa-test-ci` 前加 `alembic upgrade head`。原则:**测试文档里的每个环境假设,都要能指出由哪个 CI 步骤兑现**。
3. **同一清单多处维护必漂移**(deploy-validate 的 `TASKIQ_SCHEDULER_MODULES` env 落后 compose/k8s 两个模块)。修复:对齐四模块。原则:清单类配置要么单一来源,要么加一致性校验(required checks 清单的 `scripts/ci/required_status_checks.txt` + Guard 周检就是正例)。
4. **RTL 注册表之外的 React root 逃逸测试生命周期**(antd 静态 message holder 的 rc-motion rAF 步进与 3s auto-dismiss 定时器在 jsdom 销毁后触发,`window is not defined`;Vitest 归因漂移到无辜文件,v8 coverage 才稳定复现)。修复:`test/setup.ts` 对静态 holder 注入 `motion: false` + afterEach `destroy()`。原则:**归因不可信时用二分定位;coverage instrumentation 会改变时序;库自建的 root 要显式治理**。
5. **安全修复落在 dependabot ignore-minor 盲区**(pydantic-ai-slim / pydantic-settings / axios / react-router 的修复版本全是 minor,永远不会有 PR,Security CI 长红一个月)。修复:手动批量升级 + 开启 Dependabot alerts 兜底可见性。原则:**版本更新策略管噪音,alerts 管安全可见性,二者独立配置**。
6. **0.0.x 版本线穿透 patch 分组**(ty 0.0.18→0.0.63 在 semver 里是 patch,带着 257 个类型诊断进入 uv-patch 组打红 Typecheck)。修复:按包名 ignore,类型治理完成后移除。原则:**0.x.y 工具链包的升级风险与 semver 等级无关,按包名单独治理**。
7. **qa-docs 链接校验兜住真实回归**(work-item 归档后 `docs/assessments/` 三处死链,发起者的预检因 `2>/dev/null` 吞掉 rg 报错而假阴性)。原则:**验证命令不许吞 stderr;文档链接校验作为门禁物有所值**。
8. **两类基建抖动模式**(记录以免重复排查):GitHub runner 拉 `registry-1.docker.io` 偶发三连超时 → `gh run rerun <id> --failed` 即愈;dependabot uv updater 单次内部错误 → 周期性运行自愈,详情仅 Dependabot 后台可见。

供应链插曲:Devin Review 在 deps PR 上报"httpx2/httpcore2 typosquat 投毒",经验证为误报(httpx 原作者在 pydantic org 的正牌续作;官方元数据 / 镜像哈希比对 / org 仓库三件套核实)。**验证成本真实存在,但该类发现恰是唯一能逮住真投毒的类型**——bot 定位维持"非阻断线索源"。

## 4. 与 ci-test-matrix.md 分期路线的对照

| 分期 | 内容 | 状态(2026-07-26) |
| --- | --- | --- |
| P0 | `E2E_SMOKE_*` / PAT secrets | ✅ 完成(PAT 经 Settings 手动 + `gh secret set`) |
| P1 | branch protection 五项 required 对齐 | ✅ 完成(经 `gh api` 直配,与 `required_status_checks.txt` 逐字核对) |
| P2 | smoke-ci 加深(seed + smoke pytest 并入) | 未动,建议为下一个 CI 专项 |
| P3 | 准生产 rehearsal CI(weekly) | 未动 |
| P4 | 线上 Playwright / EC2 verify 接入 | 未动 |

矩阵文档中 smoke-ci「PR 按 path」的两处描述已随本文档同步更正。

## 5. 遗留缺口与建议(按优先级)

1. **后端覆盖率门禁休眠**:`pyproject.toml` 配有 `fail_under = 75`,但 `qa-test-ci` / `run_unit.sh` 均未带 `--cov`,门禁从未执行(07-17 评估 §5.2 遗留)。建议随 P2 一并接入,先跑一次实测覆盖率再定 fail_under 的真实值。
2. **前端 coverage floors 余量过宽**:floors 40/30/35/40 vs 实测 59/49/57/60,约 19pp 空间意味着覆盖率跌回 45% 都不报警。按「防回归下限」哲学,建议抬至实测下方 ~5pp(如 54/44/52/55)。
3. **ty 类型债**:0.0.63 报 257 个诊断,当前按包名 ignore。类型治理专项完成后恢复升级(dependabot.yml 注释已留锚点)。
4. **dev 依赖组 32 个漏洞**(langchain→1.3.9、pillow→12.3.0 等):Security CI 该步骤 `continue-on-error` 仅告警。攒一个 dev-deps batch 清理。
5. **`--maxfail=1` 掩盖 CI 失败全景**:pytest addopts 全局首败即停,CI 一轮只见一个失败点,修复迭代成本高。建议 CI profile 放宽(如 `--maxfail=5`),本地保留快停。
6. **库迁移双项**:pydantic-ai `Agent(instrument=...)` → `capabilities=[Instrumentation(...)]`(弃用警告);react-router 7→8(完成后移除 `pnpm.auditConfig.ignoreGhsas` 中 GHSA-qwww-vcr4-c8h2 豁免)。
7. **docker patch-only 的已知代价**:uv 构建镜像 / nginx 的 minor 线被挡(patch 线照常流动,0.10.7→0.10.12 已验证)。季度人工过一遍,或把 ignore 收窄到 `dependency-name: "python"`。
8. **悬空的 workspace 声明**:`pyproject.toml` 的 `tool.uv.workspace.members` 含 `test-debug-agent`,但该目录不在仓库(glob 无匹配故无害)。与「收编 test-debug-agent / tools/sidecar-mcp」的决策一并处理。
9. **运维项**:`BRANCH_PROTECTION_READ_TOKEN` 到期时 Guard 转红,换 PAT 即可。

## 6. 本地环境纪律(与 CI 的已知差异)

- 本地 uv 命令一律 `--frozen` / `--no-sync`:`UV_INDEX_URL`(tuna 镜像)会把 lock 中 pypi.org registry 条目整体重写为镜像 URL(±1100 行噪音)。lock 的规范形态是对 PyPI。
- 本地 `pnpm audit` 不可用(镜像对 audit 端点返回坏 JSON),前端依赖审计以 CI 为准。
- 复现前端测试问题必须带 `--coverage`:v8 instrumentation 改变调度时序,是多个泄漏类问题的显形条件。
- 验证类命令不加 `2>/dev/null`。

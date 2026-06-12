# Deploy 加固待办清单

来源:2026-06 针对 deploy / CI/CD / 可观测性的多维度评审。评审中的"必须修复"级问题与一批机械可验证的建议项已经落地(见 git history),本文只承载**尚未实施**的剩余建议,按优先级分组。

维护约定:完成一项后直接从本文删除该条目,并在 commit message 中引用本文件名;新发现的部署类待办也追加到这里,而不是散落在 PR 描述里。

## P1 — 数据 / 安全实质风险

### 1. 自管 Postgres fallback 缺备份自动化

- 位置:`deploy/docker-compose.local-postgres.yml`、[deploy-ec2.md](deploy-ec2.md) 备份章节
- 问题:生产主路径已切到 RDS / 外部 Postgres,但 selfhost fallback 仍没有任何备份通道;`ec2-down.sh` 的删卷保护已补,但没有备份时仍无法恢复误删或磁盘故障。
- 建议:
  - selfhost override 增加 `pg_dump` 定时备份 sidecar(如 `prodrigestivill/postgres-backup-local`)并推送 S3,或宿主 cron 调 `pg_dump` + `aws s3 cp`;
  - 备份恢复流程写入 [deploy-ec2.md](deploy-ec2.md) 并演练一次。

## P2 — 一致性 / 可维护性

### 2. Makefile `%: @:` 规则静默吞掉拼错的目标

- 位置:`Makefile`(match-anything 规则)
- 问题:`make deploy-ec2-upp` 之类的拼写错误显示成功但什么都不做,部署 runbook 场景的隐形地雷。
- 建议:先确认该规则存在的原因(通常是为了把额外目标当参数的调用形态);若无依赖,改为 `@echo "unknown target: $@" >&2; exit 1`;若有依赖,至少打印 warning。

### 3. k8s 主 overlay 本地可用性缺口

- 位置:`deploy/k8s/`
- 问题与建议(可拆为多个小 PR):
  - `knowledge-files-pvc.yaml` 是 RWO 却被多副本同挂,与扩缩容设计矛盾 → k8s 路径强制 `STORAGE_BACKEND=s3` 绕开,或改 RWX;
  - `configmap.yaml` 把 rerank provider 设为 bifrost 但清单里没有 bifrost → 改为 `""` 或补部署;

### 4. 缺 `knowledge_storage_init`(`STORAGE_BACKEND=local` 场景)

- 位置:`deploy/docker-compose.yml`(对照 `docker-compose.db.yml` 已有实现)
- 问题:切换 `STORAGE_BACKEND=local` 时 uid 1000 对命名卷无写权限,立刻 PermissionError。生产默认 s3,优先级不高。
- 建议:从 db.yml 移植 init 容器,或在文档中明确 deploy 栈不支持 local 存储。

### 5. `deploy_control_env_value` 固有残缺

- 位置:`scripts/lib/common.sh`
- 问题:"显式值必须不等于默认值"的启发式意味着显式传入恰好等于默认值的值,无法覆盖 env 文件里的不同值(如 `make deploy-ec2-up DEPLOY_PULL_IMAGES=false` 对抗文件里的 `true`)。动态默认值与自引用默认值两个触发面已修,机制本身仍在。
- 建议:彻底修复需区分"Makefile 默认导出"与"用户显式传入",可用哨兵值(Makefile 默认导出 `__unset__`,脚本侧识别)或维护显式传参白名单;改动核心机制,需配套回归所有 deploy 目标。

## P3 — 策略 / 卫生

### 6. `CURRENT_UID:-1000` 覆盖镜像内置 10001 用户

- 问题:生产无 bind mount,无需宿主 uid 对齐;1000 与镜像设计的非特权用户不一致。
- 建议:deploy 栈删除 `user:` 覆盖或默认改 10001(注意命名卷属主迁移)。

### 7. Dependabot 不覆盖 compose 中钉版的基础设施镜像

- 问题:docker 生态只看 Dockerfile,pgvector / bifrost 等 compose 钉版镜像的 CVE 无自动更新通道。
- 建议:接入 Renovate(支持 docker-compose manager),或建立季度人工核查清单。

## 已修复项的去向

评审的 10 项"必须修复"与以下建议项已落地,不在本清单中:worker 任务模块补齐、全栈 restart 策略、SSE 断连透传、smoke CI mock 切换、OTLP 路径与语义约定、Loki compactor、ec2-check 函数遮蔽、k8s local-scaling 重构、frontend 跨栈服务名、告警阈值/选择器/annotation、worker healthcheck 与依赖、SYS_PTRACE、bifrost/locust 端口绑定、日志轮转锚点、minio 钉版、nginx 动态解析与 `server_tokens`/`nosniff`、pr-gate 测试去重与 pg17、smoke path filter、deploy 校验 CI(`deploy-validate-ci.yml`)、`wait_for_http_ok` 超时解耦、`compose_deploy down` debug profile、local-prod 前端探测 URL 与取值优先级、`ec2-down.sh` 删卷显式确认、Dockerfile `FORWARDED_ALLOW_IPS` 安全默认值、deploy compose api/worker CMD 收敛、credit scheduler 装配、GitHub Actions SHA pinning、k8s 外部依赖/迁移 Job/镜像 tag runbook 补齐、deploy compose 默认切到 RDS / 外部 Postgres、deploy compose 移除 Locust/debug 压测容器、CloudWatch metric filters / alarms setup 脚本。具体见 git history 中引用本文件的提交。

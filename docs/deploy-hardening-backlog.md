# Deploy 加固待办清单

来源:2026-06 针对 deploy / CI/CD / 可观测性的多维度评审。评审中的"必须修复"级问题与一批机械可验证的建议项已经落地(见 git history),本文只承载**尚未实施**的剩余建议,按优先级分组。

维护约定:完成一项后直接从本文删除该条目,并在 commit message 中引用本文件名;新发现的部署类待办也追加到这里,而不是散落在 PR 描述里。

## P1 — 数据 / 安全实质风险

### 1. 生产数据库零备份,且 `ec2-down.sh` 支持一键连卷删除

- 位置:`deploy/docker-compose.yml`(自管 postgres)、`scripts/deploy/ec2-down.sh`、[deploy-ec2.md](deploy-ec2.md) 备份章节
- 问题:备份文档以 RDS 为前提,实际生产是自管容器 PG,当前没有任何备份通道;`ec2-down.sh` 又支持连数据卷一起删除,误操作即不可逆丢数据。
- 建议:
  - compose 增加 `pg_dump` 定时备份 sidecar(如 `prodrigestivill/postgres-backup-local`)并推送 S3,或宿主 cron 调 `pg_dump` + `aws s3 cp`;
  - `ec2-down.sh` 的删卷分支增加显式确认变量(如 `DEPLOY_CONFIRM_VOLUME_WIPE=yes`),默认拒绝;
  - 备份恢复流程写入 [deploy-ec2.md](deploy-ec2.md) 并演练一次。

### 2. Dockerfile 默认 CMD `--forwarded-allow-ips "*"`,且三处启动命令漂移

- 位置:`Dockerfile`(web 默认 CMD)、`deploy/docker-compose.yml` api `command`、`docker-compose.db.yml`
- 问题:`*` 信任任意来源的代理头,可伪造客户端 IP;web 启动命令在三处各自维护、参数互不一致(deploy 无 proxy-headers、db.yml 有但无 allow-ips、镜像默认全开)。
- 建议:镜像默认 CMD 收敛为生产形态(去掉 `--forwarded-allow-ips "*"`),代理头信任由 compose 按 `edge_net` 子网显式传入;worker 同理——删掉 compose / k8s 的 `command` 覆盖,以镜像默认 CMD 为单一事实源(这也是 worker 任务模块清单三处漂移的根治方案)。

### 3. `credit_tasks` 模块无人加载、仓库无 scheduler 装配

- 位置:`backend/worker/tasks/credit_tasks.py`;`Dockerfile` worker CMD、`deploy/docker-compose.yml`、`deploy/k8s/worker-deployment.yaml`
- 问题:`expire_credits_task` 的文档声称"由外部 Scheduler/Cron 调度器每日调用",但所有 worker 启动命令都不加载该模块,仓库里也没有任何 taskiq scheduler 进程或 cron 资产——赠送额度过期在所有环境都不会执行。
- 建议:先决策调度形态(taskiq scheduler 常驻服务,或宿主 cron / k8s CronJob 入队),再把 `backend.worker.tasks.credit_tasks` 加入 worker 默认 CMD;两步缺一不可,只加模块不会让任务自己跑起来。

## P2 — 一致性 / 可维护性

### 4. GitHub Actions 第三方 action 未做 SHA pinning

- 位置:`.github/workflows/*.yml`
- 问题:所有 actions 按可变 tag 固定;第三方(`pnpm/action-setup`、`trivy-action`)供应链风险最高。
- 建议:至少把第三方 action 钉到 commit SHA 并加 `# vX` 注释(Dependabot 支持 SHA 更新);官方 actions 可保留 tag。

### 5. smoke 失败诊断不完整

- 位置:`.github/workflows/smoke-ci.yml`、`scripts/lib/common.sh` 的日志转储路径
- 问题:pytest 全量日志不上传 artifact(runner 销毁即丢);`env-smoke-logs` 不带 `--profile`,bifrost 容器日志(常见故障源)不在失败转储里。
- 建议:失败分支加 `actions/upload-artifact` 上传 pytest 日志与 compose 日志;日志转储统一走 `compose_smoke` 并附加全部 profile。

### 6. Makefile `%: @:` 规则静默吞掉拼错的目标

- 位置:`Makefile`(match-anything 规则)
- 问题:`make deploy-ec2-upp` 之类的拼写错误显示成功但什么都不做,部署 runbook 场景的隐形地雷。
- 建议:先确认该规则存在的原因(通常是为了把额外目标当参数的调用形态);若无依赖,改为 `@echo "unknown target: $@" >&2; exit 1`;若有依赖,至少打印 warning。

### 7. k8s 主 overlay 本地可用性缺口

- 位置:`deploy/k8s/`
- 问题与建议(可拆为多个小 PR):
  - 主 overlay 引用的 redis / postgres Service 不存在,按 README 顺序部署必不可用 → 补 ExternalName/手工 Service 示例,或在 README 写明前置依赖;
  - `knowledge-files-pvc.yaml` 是 RWO 却被多副本同挂,与扩缩容设计矛盾 → k8s 路径强制 `STORAGE_BACKEND=s3` 绕开,或改 RWX;
  - 迁移 Job 进 kustomize 后无法重复 apply → runbook 写明 `kubectl delete job db-migrator --ignore-not-found` 再 apply;
  - `configmap.yaml` 把 rerank provider 设为 bifrost 但清单里没有 bifrost → 改为 `""` 或补部署;
  - README 镜像构建步骤与 Makefile 不可变 tag 机制脱节,manifest 写死 `2.0.0` 伪版本 → README 改为引用 `make release-image-env` 产出的真实 tag。

### 8. 缺 `knowledge_storage_init`(`STORAGE_BACKEND=local` 场景)

- 位置:`deploy/docker-compose.yml`(对照 `docker-compose.db.yml` 已有实现)
- 问题:切换 `STORAGE_BACKEND=local` 时 uid 1000 对命名卷无写权限,立刻 PermissionError。生产默认 s3,优先级不高。
- 建议:从 db.yml 移植 init 容器,或在文档中明确 deploy 栈不支持 local 存储。

### 9. `REDIS_PORT` 双重用途

- 位置:`docker-compose.db.yml`
- 问题:同一变量既控制宿主端口映射又控制应用连接端口,改端口避让会直接弄断应用。
- 建议:拆成 `REDIS_HOST_PORT`(宿主映射)+ 容器内固定 6379。

### 10. `ec2-check.sh` 变量校验优先级与 compose 插值相反

- 位置:`scripts/deploy/ec2-check.sh`(S3_BUCKET 等)
- 问题:compose 插值是 shell env 优先于 env 文件,ec2-check 反之,Makefile 的环境变量覆盖对预检无效。
- 建议:校验逻辑改用 `deploy_control_env_value`(已修复显式值吞没问题),与运行时取值同序。

### 11. `deploy_control_env_value` 固有残缺

- 位置:`scripts/lib/common.sh`
- 问题:"显式值必须不等于默认值"的启发式意味着显式传入恰好等于默认值的值,无法覆盖 env 文件里的不同值(如 `make deploy-ec2-up DEPLOY_PULL_IMAGES=false` 对抗文件里的 `true`)。动态默认值与自引用默认值两个触发面已修,机制本身仍在。
- 建议:彻底修复需区分"Makefile 默认导出"与"用户显式传入",可用哨兵值(Makefile 默认导出 `__unset__`,脚本侧识别)或维护显式传参白名单;改动核心机制,需配套回归所有 deploy 目标。

## P3 — 策略 / 卫生

### 12. push main 的 `cancel-in-progress` 会跳过中间提交验证

- 位置:三个工作流的 `concurrency` 配置
- 建议:`group` 对 push 事件拼上 `github.run_id`,或 `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`。

### 13. draft PR 跑全量 pr-gate

- 建议:job 加 `if: ${{ !github.event.pull_request.draft }}`(注意保留 `ready_for_review` 触发)。

### 14. 全栈未启用 `no-new-privileges`

- 建议:`deploy/docker-compose.yml` 增加 `x-security` 锚点(`security_opt: ["no-new-privileges:true"]`)逐服务挂载。

### 15. `CURRENT_UID:-1000` 覆盖镜像内置 10001 用户

- 问题:生产无 bind mount,无需宿主 uid 对齐;1000 与镜像设计的非特权用户不一致。
- 建议:deploy 栈删除 `user:` 覆盖或默认改 10001(注意命名卷属主迁移)。

### 16. Dockerfile extras 安装在源码 COPY 之后伤层缓存

- 建议:依赖安装步骤全部前置到源码 COPY 之前。

### 17. Dependabot 不覆盖 compose 中钉版的基础设施镜像

- 问题:docker 生态只看 Dockerfile,pgvector / bifrost 等 compose 钉版镜像的 CVE 无自动更新通道。
- 建议:接入 Renovate(支持 docker-compose manager),或建立季度人工核查清单。

### 18. 本地测试栈(`docker-compose.db.yml`)弱凭据与 0.0.0.0 绑定

- 问题:postgres / redis / grafana / minio 绑 0.0.0.0 且使用弱凭据,grafana 匿名 Admin;smoke 的 db_migrator 注入全部 secret(生产已最小化,反差)。
- 建议:明知是本地栈,仍建议端口默认收敛 127.0.0.1、db_migrator secret 收敛到 `POSTGRES_PASSWORD`,与生产对齐降低心智负担。

## 已修复项的去向

评审的 10 项"必须修复"与以下建议项已落地,不在本清单中:worker 任务模块补齐、全栈 restart 策略、SSE 断连透传、smoke CI mock 切换、OTLP 路径与语义约定、Loki compactor、ec2-check 函数遮蔽、k8s local-scaling 重构、frontend 跨栈服务名、告警阈值/选择器/annotation、worker healthcheck 与依赖、SYS_PTRACE、bifrost/locust 端口绑定、日志轮转锚点、minio 钉版、nginx 动态解析与 `server_tokens`/`nosniff`、pr-gate 测试去重与 pg17、smoke path filter、deploy 校验 CI(`deploy-validate-ci.yml`)、`wait_for_http_ok` 超时解耦、`compose_deploy down` debug profile、local-prod 前端探测 URL 与取值优先级。具体见 git history 中引用本文件的提交。

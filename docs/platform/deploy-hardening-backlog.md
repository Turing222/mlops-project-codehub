# Deploy 加固待办清单

来源:2026-06 针对 deploy / CI/CD / 可观测性的多维度评审。评审中的"必须修复"级问题与一批机械可验证的建议项已经落地(见 git history),本文只承载**尚未实施**的剩余建议,按优先级分组。

当前运维边界:

- 生产数据库主路径是 RDS / 外部 PostgreSQL; compose 内置 PostgreSQL 只作为本地或无 RDS 时的 fallback,不承诺仓库内生产备份自动化。
- EC2 deploy 栈只支持 `STORAGE_BACKEND=s3`; local storage 归 `docker-compose.db.yml` 的本地 / CI smoke 场景。
- `deploy/k8s/` 是实验路径,不属于当前 production acceptance path。

维护约定:完成一项后直接从本文删除该条目,并在 commit message 中引用本文件名;新发现的部署类待办也追加到这里,而不是散落在 PR 描述里。

## 已修复项的去向

评审的 10 项"必须修复"与以下建议项已落地,不在本清单中:worker 任务模块补齐、全栈 restart 策略、SSE 断连透传、smoke CI mock 切换、OTLP 路径与语义约定、Loki compactor、ec2-check 函数遮蔽、k8s local-scaling 重构、frontend 跨栈服务名、告警阈值/选择器/annotation、worker healthcheck 与依赖、SYS_PTRACE、bifrost/locust 端口绑定、日志轮转锚点、minio 钉版、nginx 动态解析与 `server_tokens`/`nosniff`、pr-gate 测试去重与 pg17、smoke path filter、deploy 校验 CI(`deploy-validate-ci.yml`)、`wait_for_http_ok` 超时解耦、`compose_deploy down` debug profile、local-prod 前端探测 URL 与取值优先级、`ec2-down.sh` 删卷显式确认、Dockerfile `FORWARDED_ALLOW_IPS` 安全默认值、deploy compose api/worker CMD 收敛、credit scheduler 装配、GitHub Actions SHA pinning、k8s 外部依赖/迁移 Job/镜像 tag runbook 补齐、deploy compose 默认切到 RDS / 外部 Postgres、deploy compose 移除 Locust/debug 压测容器、CloudWatch metric filters / alarms setup 脚本、selfhost Postgres 备份 sidecar 决策关闭、k8s 主 overlay 移出生产 hardening、EC2 deploy local storage 预检拒绝、Makefile catch-all warning、compose 钉版镜像季度人工核查清单、`deploy_control_env_value` 显式覆盖机制修复、deploy compose 移除 `CURRENT_UID` 覆盖并清理 local storage 卷残留。具体见 git history 中引用本文件的提交。

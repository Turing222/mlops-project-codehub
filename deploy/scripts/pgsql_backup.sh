#!/bin/sh
set -euo pipefail
# ---------------------------------------------------------
# PostgreSQL 自动备份脚本 (2026 生产增强版)
# ---------------------------------------------------------

# 设置保留天数，防止磁盘爆满
KEEP_DAYS=7
BACKUP_DIR="/backup"

echo "🚀 [$(date +'%Y-%m-%d %H:%M:%S')] 备份任务启动..."

# 确保备份目录存在
mkdir -p "${BACKUP_DIR}"

while true; do
    FILENAME="backup_$(date +%Y%m%d_%H%M%S).sql.gz"
    LOCKFILE="${BACKUP_DIR}/.backup.lock"
    
    # 简易锁机制：防止并行执行
    if [ -f "${LOCKFILE}" ]; then
        echo "⚠️ [$(date +'%Y-%m-%d %H:%M:%S')] 检测到锁文件，跳过本次备份"
        sleep 86400
        continue
    fi
    trap 'rm -f "${LOCKFILE}"' EXIT
    touch "${LOCKFILE}"

    # 磁盘空间检查（至少保留 500MB）
    AVAIL_KB=$(df "${BACKUP_DIR}" | awk 'NR==2 {print $4}')
    if [ "${AVAIL_KB}" -lt 512000 ]; then
        echo "❌ [$(date +'%Y-%m-%d %H:%M:%S')] 磁盘空间不足 (${AVAIL_KB}KB)，跳过备份！"
        rm -f "${LOCKFILE}"
        sleep 86400
        continue
    fi

    # 1. 执行备份并直接通过管道压缩 (节省空间)
    # 使用 pipefail 确保 pg_dump 失败时整体失败
    # -h postgres 使用 Docker 网络中的服务名
    if pg_dump -h postgres -U "${POSTGRES_USER}" "${POSTGRES_DB}" | gzip > "${BACKUP_DIR}/${FILENAME}"; then
        FILESIZE=$(du -h "${BACKUP_DIR}/${FILENAME}" | cut -f1)
        echo "✅ [$(date +'%Y-%m-%d %H:%M:%S')] 备份成功: ${FILENAME} (${FILESIZE})"
    else
        echo "❌ [$(date +'%Y-%m-%d %H:%M:%S')] 备份失败！请检查数据库连接。"
        rm -f "${BACKUP_DIR}/${FILENAME}" 2>/dev/null  # 清理不完整的备份文件
    fi

    # 2. 清理超过 KEEP_DAYS 天的旧备份
    echo "🧹 清理 ${KEEP_DAYS} 天前的旧数据..."
    find "${BACKUP_DIR}" -type f -name "backup_*.sql.gz" -mtime +${KEEP_DAYS} -exec rm {} \;

    # 释放锁
    rm -f "${LOCKFILE}"
    trap - EXIT

    # 3. 等待下一次备份 (86400秒 = 24小时)
    echo "💤 进入休眠，24小时后执行下一次任务。"
    sleep 86400
done
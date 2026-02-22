#!/bin/sh
# ---------------------------------------------------------
# PostgreSQL 自动备份脚本 (2026 生产增强版)
# ---------------------------------------------------------

# 设置保留天数，防止磁盘爆满
KEEP_DAYS=7
BACKUP_DIR="/backup"

echo "🚀 [$(date +'%Y-%m-%d %H:%M:%S')] 备份任务启动..."

while true; do
    FILENAME="backup_$(date +%Y%m%d_%H%M%S).sql.gz"
    
    # 1. 执行备份并直接通过管道压缩 (节省空间)
    # -h postgres 使用 Docker 网络中的服务名
    pg_dump -h postgres -U "${POSTGRES_USER}" "${POSTGRES_DB}" | gzip > "${BACKUP_DIR}/${FILENAME}"
    
    if [ $? -eq 0 ]; then
        echo "✅ [$(date +'%Y-%m-%d %H:%M:%S')] 备份成功: ${FILENAME}"
    else
        echo "❌ [$(date +'%Y-%m-%d %H:%M:%S')] 备份失败！请检查数据库连接。"
    fi

    # 2. 清理超过 KEEP_DAYS 天的旧备份
    echo "🧹 清理 ${KEEP_DAYS} 天前的旧数据..."
    find "${BACKUP_DIR}" -type f -name "backup_*.sql.gz" -mtime +${KEEP_DAYS} -exec rm {} \;

    # 3. 等待下一次备份 (86400秒 = 24小时)
    echo "💤 进入休眠，24小时后执行下一次任务。"
    sleep 86400
done
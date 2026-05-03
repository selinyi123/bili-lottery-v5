#!/bin/bash
# B站抽奖系统 v5.1 - 健康检查脚本
# 用法: ./check_health.sh
# 可加入crontab定时执行

PROJECT_DIR="/opt/bili-lottery"
LOG_DIR="${PROJECT_DIR}/logs"
DB_FILE="${PROJECT_DIR}/data/bili_lottery.db"
MAX_LOG_SIZE=$((100 * 1024 * 1024))  # 100MB
MAX_DB_SIZE=$((500 * 1024 * 1024))    # 500MB

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

report=""
add_report() {
    report="${report}$1\n"
}

# 1. 检查服务状态
echo "========== B站抽奖系统健康检查 =========="
echo "检查时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

if systemctl is-active --quiet bili-lottery 2>/dev/null; then
    uptime=$(systemctl show bili-lottery --property=ActiveEnterTimestamp --value 2>/dev/null | cut -d' ' -f2-)
    echo -e "[服务状态] ${GREEN}运行中${NC} (启动时间: ${uptime})"
    add_report "服务: 运行中"
else
    echo -e "[服务状态] ${RED}未运行${NC}"
    add_report "服务: 未运行 ⚠"
    # 尝试自动重启
    echo "正在尝试自动重启..."
    systemctl restart bili-lottery 2>/dev/null
    sleep 3
    if systemctl is-active --quiet bili-lottery 2>/dev/null; then
        echo -e "${GREEN}自动重启成功${NC}"
        add_report "自动重启: 成功"
    else
        echo -e "${RED}自动重启失败，请手动检查${NC}"
        add_report "自动重启: 失败 ❌"
    fi
fi
echo ""

# 2. 检查内存占用
echo "[内存检查]"
if pgrep -f "python3.*main.py" > /dev/null; then
    mem_kb=$(ps -o rss= -p $(pgrep -f "python3.*main.py" | head -1) 2>/dev/null || echo 0)
    mem_mb=$((mem_kb / 1024))
    if [ "$mem_mb" -gt 800 ]; then
        echo -e "  Python进程: ${RED}${mem_mb}MB${NC} (偏高)"
        add_report "内存: ${mem_mb}MB (偏高)"
    elif [ "$mem_mb" -gt 500 ]; then
        echo -e "  Python进程: ${YELLOW}${mem_mb}MB${NC} (注意)"
        add_report "内存: ${mem_mb}MB"
    else
        echo -e "  Python进程: ${GREEN}${mem_mb}MB${NC} (正常)"
        add_report "内存: ${mem_mb}MB (正常)"
    fi
fi

chrome_pids=$(pgrep -c "chrome" 2>/dev/null || echo 0)
echo -e "  Chrome进程数: ${chrome_pids}"
echo ""

# 3. 检查日志文件大小
echo "[日志检查]"
if [ -f "${LOG_DIR}/lottery_system.log" ]; then
    log_size=$(stat -f%z "${LOG_DIR}/lottery_system.log" 2>/dev/null || stat -c%s "${LOG_DIR}/lottery_system.log" 2>/dev/null || echo 0)
    log_mb=$((log_size / 1024 / 1024))
    if [ "$log_size" -gt "$MAX_LOG_SIZE" ]; then
        echo -e "  lottery_system.log: ${RED}${log_mb}MB${NC} (超过100MB)"
        echo "  正在压缩旧日志..."
        gzip -c "${LOG_DIR}/lottery_system.log" > "${LOG_DIR}/lottery_system.log.$(date +%Y%m%d).gz"
        > "${LOG_DIR}/lottery_system.log"
        add_report "日志: 已压缩 (${log_mb}MB)"
    else
        echo -e "  lottery_system.log: ${GREEN}${log_mb}MB${NC}"
    fi
fi
echo ""

# 4. 检查数据库大小
echo "[数据库检查]"
if [ -f "$DB_FILE" ]; then
    db_size=$(stat -f%z "$DB_FILE" 2>/dev/null || stat -c%s "$DB_FILE" 2>/dev/null || echo 0)
    db_mb=$((db_size / 1024 / 1024))
    if [ "$db_size" -gt "$MAX_DB_SIZE" ]; then
        echo -e "  数据库大小: ${RED}${db_mb}MB${NC} (超过500MB)"
        add_report "数据库: ${db_mb}MB (偏大)"
    else
        echo -e "  数据库大小: ${GREEN}${db_mb}MB${NC}"
    fi
    
    # 今日参与统计
    today=$(date +%Y-%m-%d)
    today_count=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM history WHERE timestamp LIKE '${today}%';" 2>/dev/null || echo 0)
    echo -e "  今日参与: ${today_count} 次"
    add_report "今日参与: ${today_count} 次"
    
    # 最近错误统计
    recent_errors=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM operation_log WHERE success = 0 AND timestamp > datetime('now', '-1 hour');" 2>/dev/null || echo 0)
    if [ "$recent_errors" -gt 10 ]; then
        echo -e "  近1小时错误: ${RED}${recent_errors}${NC}"
        add_report "错误: ${recent_errors}/小时 (偏高)"
    else
        echo -e "  近1小时错误: ${GREEN}${recent_errors}${NC}"
    fi
fi
echo ""

# 5. 磁盘空间检查
echo "[磁盘空间]"
avail=$(df -BG "$PROJECT_DIR" | tail -1 | awk '{print $4}' | tr -d 'G')
if [ "$avail" -lt 2 ]; then
    echo -e "  可用空间: ${RED}${avail}GB${NC} (不足2GB)"
    add_report "磁盘: ${avail}GB (不足) ❌"
else
    echo -e "  可用空间: ${GREEN}${avail}GB${NC}"
    add_report "磁盘: ${avail}GB (正常)"
fi
echo ""

# 6. 最近日志摘要
echo "[最近日志摘要]"
if [ -f "${LOG_DIR}/lottery_system.log" ]; then
    echo "--- 最近5条记录 ---"
    tail -5 "${LOG_DIR}/lottery_system.log"
fi
echo ""

echo "========== 检查完成 =========="

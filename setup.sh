#!/bin/bash
# B站抽奖系统 v5.1 - v4.0迁移/初始化脚本
# 用法: chmod +x setup.sh && ./setup.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

OLD_DIR="/root/bili_lottery"      # v4.0默认目录
NEW_DIR="/opt/bili-lottery"       # v5.1标准目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}  v5.1 初始化 / v4.0 迁移工具          ${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""

# ============ 函数定义 ============

backup_v4() {
    echo -e "${YELLOW}[迁移] 发现v4.0旧版本，正在备份...${NC}"
    BACKUP_DIR="/root/bili_lottery_backup_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    
    # 备份数据库
    if [ -f "${OLD_DIR}/data/bili_lottery.db" ]; then
        cp "${OLD_DIR}/data/bili_lottery.db" "$BACKUP_DIR/"
        echo -e "  ${GREEN}已备份数据库${NC}"
    fi
    
    # 备份配置
    if [ -f "${OLD_DIR}/config.json" ]; then
        cp "${OLD_DIR}/config.json" "$BACKUP_DIR/"
        echo -e "  ${GREEN}已备份配置文件${NC}"
    fi
    
    # 备份日志
    if [ -d "${OLD_DIR}/logs" ]; then
        cp -r "${OLD_DIR}/logs" "$BACKUP_DIR/" 2>/dev/null || true
        echo -e "  ${GREEN}已备份日志${NC}"
    fi
    
    # 备份chrome登录状态
    if [ -d "${OLD_DIR}/chrome_profile" ]; then
        cp -r "${OLD_DIR}/chrome_profile" "$BACKUP_DIR/" 2>/dev/null || true
        echo -e "  ${GREEN}已备份Chrome登录状态${NC}"
    fi
    
    echo -e "  ${GREEN}备份完成: ${BACKUP_DIR}${NC}"
    echo ""
}

migrate_v4_to_v5() {
    echo -e "${YELLOW}[迁移] 正在迁移v4.0数据到v5.1...${NC}"
    
    # 1. 迁移数据库
    if [ -f "${OLD_DIR}/data/bili_lottery.db" ]; then
        echo -e "  ${YELLOW}复制数据库...${NC}"
        cp "${OLD_DIR}/data/bili_lottery.db" "${NEW_DIR}/data/"
        echo -e "  ${GREEN}数据库已迁移${NC}"
    fi
    
    # 2. 迁移chrome_profile（登录状态）
    if [ -d "${OLD_DIR}/chrome_profile" ]; then
        echo -e "  ${YELLOW}迁移Chrome登录状态...${NC}"
        rm -rf "${NEW_DIR}/chrome_profile" 2>/dev/null || true
        cp -r "${OLD_DIR}/chrome_profile" "${NEW_DIR}/"
        echo -e "  ${GREEN}登录状态已迁移（你可以继续使用原来的B站账号）${NC}"
    fi
    
    # 3. 提取UP主列表（从main.py或数据库）
    echo -e "  ${YELLOW}检查UP主配置...${NC}"
    # 如果旧版本main.py中有硬编码的UP主，提示用户手动添加
    if grep -q "target_ups\s*=" "${OLD_DIR}/main.py" 2>/dev/null; then
        echo -e "  ${YELLOW}注意: 你旧版本的UP主列表在main.py中硬编码${NC}"
        echo -e "  请手动编辑 ${NEW_DIR}/config.json 的 lottery_hub_ups 字段"
    fi
    
    echo ""
    echo -e "${GREEN}[迁移完成] v4.0数据已成功迁移到v5.1${NC}"
    echo ""
}

cleanup_v4() {
    echo -e "${YELLOW}[清理] 正在清理v4.0旧文件...${NC}"
    
    # 停止可能正在运行的v4.0进程
    if pgrep -f "python3.*main.py" > /dev/null 2>&1; then
        echo -e "  ${YELLOW}停止运行中的v4.0进程...${NC}"
        kill $(pgrep -f "python3.*main.py") 2>/dev/null || true
        sleep 2
        echo -e "  ${GREEN}已停止${NC}"
    fi
    
    # 清理残留的Chrome进程
    pkill -f "chrome --headless" 2>/dev/null || true
    pkill -f "chromedriver" 2>/dev/null || true
    sleep 1
    
    echo -e "  ${GREEN}v4.0进程已清理${NC}"
    echo ""
    echo -e "${YELLOW}旧版本文件保留在 ${OLD_DIR}（不会删除，如需手动删除请运行）:${NC}"
    echo -e "  ${RED}rm -rf ${OLD_DIR}${NC}"
    echo ""
}

# ============ 主流程 ============

if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}错误: 请使用 root 用户运行${NC}"
    exit 1
fi

# 检查是否有v4.0
if [ -d "$OLD_DIR" ]; then
    echo -e "${YELLOW}检测到v4.0旧版本目录: ${OLD_DIR}${NC}"
    read -p "是否迁移v4.0数据到v5.1? [Y/n]: " migrate_choice
    migrate_choice=${migrate_choice:-Y}
    
    if [[ "$migrate_choice" =~ ^[Yy]$ ]]; then
        backup_v4
        
        # 安装v5.1（如果还没安装）
        if [ ! -d "$NEW_DIR" ]; then
            echo -e "${YELLOW}[安装] v5.1尚未安装，正在安装...${NC}"
            cd "$SCRIPT_DIR"
            bash install.sh
        fi
        
        migrate_v4_to_v5
        cleanup_v4
        
        echo -e "${GREEN}=========================================${NC}"
        echo -e "${GREEN}  v4.0 -> v5.1 迁移完成！              ${NC}"
        echo -e "${GREEN}=========================================${NC}"
        echo ""
        echo -e "你现在可以直接启动v5.1:"
        echo -e "  ${BLUE}systemctl start bili-lottery${NC}"
        exit 0
    else
        echo -e "${YELLOW}跳过迁移，继续全新安装v5.1...${NC}"
        echo ""
    fi
fi

# 全新安装流程
echo -e "${YELLOW}[初始化] 开始全新安装v5.1...${NC}"
cd "$SCRIPT_DIR"
bash install.sh

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}  v5.1 初始化完成！                    ${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo -e "${YELLOW}重要提醒 - 接下来的步骤:${NC}"
echo ""
echo "1. 获取B站Cookie（二选一）:"
echo "   方法A - 在本地电脑登录B站，导出cookie上传到服务器"
echo -e "   方法B - 在服务器运行: ${BLUE}cd ${NEW_DIR} && python3 get_cookies.py --auto${NC}"
echo ""
echo "2. 添加要监控的UP主:"
echo -e "   ${BLUE}nano ${NEW_DIR}/config.json${NC}"
echo "   找到 lottery_hub_ups 字段添加UP主"
echo ""
echo "3. 启动测试:"
echo -e "   ${BLUE}cd ${NEW_DIR} && python3 main.py${NC}"
echo ""
echo "4. 正式运行:"
echo -e "   ${BLUE}systemctl start bili-lottery${NC}"
echo ""

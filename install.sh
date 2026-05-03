#!/bin/bash
# B站自动抽奖系统 v5.1 - 一键安装脚本
# 用法: chmod +x install.sh && ./install.sh

set -e  # 遇到错误立即退出

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PROJECT_DIR="/opt/bili-lottery"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}  B站自动抽奖系统 v5.1 - 一键安装     ${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""

# 检查root权限
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}错误: 请使用 root 用户运行此脚本${NC}"
    echo "提示: 在Termius中你已经是以root登录的"
    exit 1
fi

# 1. 更新系统
echo -e "${YELLOW}[1/8] 更新系统软件包...${NC}"
apt-get update -qq && apt-get upgrade -y -qq
echo -e "${GREEN}      完成${NC}"

# 2. 安装基础依赖
echo -e "${YELLOW}[2/8] 安装基础依赖 (python3, pip, wget, curl, sqlite3)...${NC}"
apt-get install -y -qq python3 python3-pip wget curl sqlite3 psmisc > /dev/null 2>&1
echo -e "${GREEN}      完成${NC}"

# 3. 检查Python版本
echo -e "${YELLOW}[3/8] 检查Python版本...${NC}"
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo -e "      Python版本: ${GREEN}${PYTHON_VERSION}${NC}"

# 4. 安装Chrome浏览器
echo -e "${YELLOW}[4/8] 安装Chrome浏览器...${NC}"
if ! command -v google-chrome &> /dev/null; then
    wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -O /tmp/chrome.deb
    apt-get install -y -qq /tmp/chrome.deb > /dev/null 2>&1 || apt-get --fix-broken install -y -qq > /dev/null 2>&1
    rm -f /tmp/chrome.deb
    CHROME_VERSION=$(google-chrome --version 2>&1)
    echo -e "      ${GREEN}${CHROME_VERSION}${NC}"
else
    CHROME_VERSION=$(google-chrome --version 2>&1)
    echo -e "      Chrome已安装: ${GREEN}${CHROME_VERSION}${NC}"
fi

# 5. 安装Python依赖
echo -e "${YELLOW}[5/8] 安装Python依赖...${NC}"
pip3 install -q --no-cache-dir -r "${SCRIPT_DIR}/requirements.txt" -i https://pypi.tuna.tsinghua.edu.cn/simple
echo -e "      ${GREEN}完成${NC}"

# 6. 创建项目目录并复制文件
echo -e "${YELLOW}[6/8] 部署项目文件...${NC}"
mkdir -p "${PROJECT_DIR}"
mkdir -p "${PROJECT_DIR}/logs"
mkdir -p "${PROJECT_DIR}/data"
mkdir -p "${PROJECT_DIR}/chrome_profile"

# 复制程序文件
cp "${SCRIPT_DIR}/main.py" "${PROJECT_DIR}/"
cp "${SCRIPT_DIR}/config.json" "${PROJECT_DIR}/"
cp "${SCRIPT_DIR}/get_cookies.py" "${PROJECT_DIR}/"
cp "${SCRIPT_DIR}/check_health.sh" "${PROJECT_DIR}/"
chmod +x "${PROJECT_DIR}/check_health.sh"

# 如果有cookie文件也复制
if [ -f "${SCRIPT_DIR}/cookies.json" ]; then
    cp "${SCRIPT_DIR}/cookies.json" "${PROJECT_DIR}/"
    echo -e "      ${GREEN}Cookie文件已复制${NC}"
fi

echo -e "      ${GREEN}完成${NC}"

# 7. 配置systemd服务（开机自启 + 崩溃自动重启）
echo -e "${YELLOW}[7/8] 配置系统服务...${NC}"
cp "${SCRIPT_DIR}/bili-lottery.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable bili-lottery.service
echo -e "      ${GREEN}服务已配置${NC}"

# 8. 设置定时任务（每周清理日志 + 每日健康检查）
echo -e "${YELLOW}[8/8] 配置定时任务...${NC}"
(crontab -l 2>/dev/null || true) | grep -v "bili-lottery" | { cat; echo "0 6 * * 0 find ${PROJECT_DIR}/logs -name '*.log' -mtime +7 -delete 2>/dev/null"; } | crontab -
(crontab -l 2>/dev/null || true) | { cat; echo "0 8 * * * ${PROJECT_DIR}/check_health.sh >> ${PROJECT_DIR}/logs/health_check.log 2>&1"; } | crontab -
echo -e "      ${GREEN}完成${NC}"

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}  安装完成！                             ${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo -e "项目目录: ${BLUE}${PROJECT_DIR}${NC}"
echo ""
echo -e "${YELLOW}接下来你需要做的事:${NC}"
echo "  1. 配置Cookie（B站登录）:"
echo -e "     ${BLUE}cd ${PROJECT_DIR} && python3 get_cookies.py --auto${NC}"
echo "     （在本地电脑登录B站后导出cookie上传更简便）"
echo ""
echo "  2. 编辑 config.json 添加监控的UP主:"
echo -e "     ${BLUE}nano ${PROJECT_DIR}/config.json${NC}"
echo ""
echo "  3. 启动程序（前台测试）:"
echo -e "     ${BLUE}cd ${PROJECT_DIR} && python3 main.py${NC}"
echo ""
echo "  4. 正式运行（后台服务，开机自启）:"
echo -e "     ${BLUE}systemctl start bili-lottery${NC}"
echo ""
echo "  5. 常用命令:"
echo -e "     查看状态: ${BLUE}systemctl status bili-lottery${NC}"
echo -e "     查看日志: ${BLUE}journalctl -u bili-lottery -f${NC}"
echo -e "     重启服务: ${BLUE}systemctl restart bili-lottery${NC}"
echo -e "     停止服务: ${BLUE}systemctl stop bili-lottery${NC}"
echo ""

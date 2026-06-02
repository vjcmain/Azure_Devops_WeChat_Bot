#!/bin/bash

# ==========================================
# TFS to WeCom Smart Router Gateway 管理脚本
# ==========================================

SERVICE_NAME="tfs-wecom"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
APP_DIR="/opt/tfs-wecom"
APP_SCRIPT="${APP_DIR}/app_server.py"

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 打印带颜色的信息
info() { echo -e "${GREEN}[INFO] $1${NC}"; }
warn() { echo -e "${YELLOW}[WARN] $1${NC}"; }
error() { echo -e "${RED}[ERROR] $1${NC}"; }

# 检查是否以 root 权限运行
check_root() {
    if [ "$EUID" -ne 0 ]; then
        error "请使用 sudo 运行此命令！(例如: sudo ./manage.sh install)"
        exit 1
    fi
}

install_service() {
    check_root
    info "开始部署/更新 Systemd 服务配置..."

    # 检查工作目录和代码文件是否存在
    if [ ! -d "$APP_DIR" ]; then
        warn "目录 $APP_DIR 不存在，正在创建..."
        mkdir -p "$APP_DIR"
    fi

    if [ ! -f "$APP_SCRIPT" ]; then
        warn "警告: 找不到代码文件 $APP_SCRIPT，请确保代码已上传到该位置！"
    fi

    # 写入 systemd 配置文件
    cat <<EOF > $SERVICE_FILE
[Unit]
Description=TFS to WeCom Smart Router Gateway
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 $APP_SCRIPT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    info "重新加载 Systemd 守护进程..."
    systemctl daemon-reload
    
    info "设置服务开机自启..."
    systemctl enable $SERVICE_NAME
    
    info "正在启动服务..."
    systemctl restart $SERVICE_NAME
    
    info "部署完成！当前状态如下："
    systemctl status $SERVICE_NAME --no-pager
}

# 命令路由
case "$1" in
    install)
        install_service
        ;;
    start)
        info "启动服务: $SERVICE_NAME..."
        sudo systemctl start $SERVICE_NAME
        info "操作完成。"
        ;;
    stop)
        info "停止服务: $SERVICE_NAME..."
        sudo systemctl stop $SERVICE_NAME
        info "操作完成。"
        ;;
    restart)
        info "重启服务: $SERVICE_NAME..."
        sudo systemctl restart $SERVICE_NAME
        info "操作完成。"
        ;;
    status)
        sudo systemctl status $SERVICE_NAME
        ;;
    log|logs)
        info "正在追踪实时日志 (按 Ctrl+C 退出)..."
        sudo journalctl -u $SERVICE_NAME -f
        ;;
    *)
        echo "使用方法: $0 {install|start|stop|restart|status|log}"
        echo ""
        echo "  install  - 一键注册 Systemd 服务并设置开机自启"
        echo "  start    - 启动服务"
        echo "  stop     - 停止服务"
        echo "  restart  - 重启服务 (更新代码后使用)"
        echo "  status   - 查看运行状态"
        echo "  log      - 查看并持续追踪系统日志"
        exit 1
        ;;
esac

exit 0
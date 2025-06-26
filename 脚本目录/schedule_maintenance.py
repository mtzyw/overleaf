#!/usr/bin/env python3
"""
定时维护调度器 - 使用schedule库实现定时任务
pip install schedule
"""

import schedule
import time
import subprocess
import logging
from datetime import datetime
import os
import sys

# 设置日志 - 只输出到控制台
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class MaintenanceScheduler:
    """维护任务调度器"""
    
    def __init__(self):
        self.script_dir = "/Users/longshu/Desktop/未命名文件夹/newpy_副本/脚本目录"
        self.python_cmd = "python3"
        
    def run_command(self, command: str, description: str):
        """执行维护命令"""
        try:
            logger.info(f"开始执行: {description}")
            
            # 构建完整命令
            full_command = f"cd {self.script_dir} && {self.python_cmd} auto_maintenance.py {command}"
            
            # 执行命令
            result = subprocess.run(
                full_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=1800  # 30分钟超时
            )
            
            if result.returncode == 0:
                logger.info(f"✅ {description} 执行成功")
                if result.stdout:
                    logger.info(f"输出: {result.stdout.strip()}")
            else:
                logger.error(f"❌ {description} 执行失败")
                logger.error(f"错误: {result.stderr.strip()}")
                
        except subprocess.TimeoutExpired:
            logger.error(f"⏰ {description} 执行超时")
        except Exception as e:
            logger.error(f"💥 {description} 执行异常: {e}")
    
    def daily_full_maintenance(self):
        """每日完整维护"""
        logger.info("🌅 开始每日完整维护")
        self.run_command("full", "每日完整维护")
    
    def hourly_email_update(self):
        """每小时email_id更新"""
        logger.info("📧 开始每小时email_id更新")
        self.run_command("update-emails", "每小时email_id更新")
    
    def hourly_cleanup(self):
        """每小时过期清理"""
        logger.info("🗑️ 开始每小时过期清理")
        self.run_command("cleanup-expired", "每小时过期清理")
    
    def health_check(self):
        """健康检查"""
        logger.info("💊 开始系统健康检查")
        self.run_command("report", "系统健康检查")

def setup_schedule():
    """设置定时任务"""
    scheduler = MaintenanceScheduler()
    
    # 每日凌晨2点执行完整维护
    schedule.every().day.at("02:00").do(scheduler.daily_full_maintenance)
    
    # 每小时更新email_id（工作时间）
    schedule.every().hour.at(":05").do(scheduler.hourly_email_update)
    
    # 每2小时清理过期邀请
    schedule.every(2).hours.at(":10").do(scheduler.hourly_cleanup)
    
    # 每30分钟健康检查
    schedule.every(30).minutes.do(scheduler.health_check)
    
    logger.info("📅 定时任务已设置:")
    logger.info("  - 每日 02:00: 完整维护")
    logger.info("  - 每小时 :05: 更新email_id")
    logger.info("  - 每2小时 :10: 清理过期")
    logger.info("  - 每30分钟: 健康检查")

def run_scheduler():
    """运行调度器"""
    setup_schedule()
    
    logger.info("🚀 定时维护调度器已启动")
    logger.info("按 Ctrl+C 停止")
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # 每分钟检查一次
    except KeyboardInterrupt:
        logger.info("👋 调度器已停止")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='定时维护调度器')
    parser.add_argument('--setup-cron', action='store_true', help='生成crontab配置')
    parser.add_argument('--run', action='store_true', help='运行调度器')
    parser.add_argument('--test', action='store_true', help='测试单次执行')
    
    args = parser.parse_args()
    
    if args.setup_cron:
        # 生成crontab配置
        cron_config = f"""
# Overleaf邀请管理系统定时维护
# 每日凌晨2点完整维护
0 2 * * * cd {os.path.dirname(os.path.abspath(__file__))} && python3 auto_maintenance.py full >> scheduler.log 2>&1

# 每小时更新email_id
5 * * * * cd {os.path.dirname(os.path.abspath(__file__))} && python3 auto_maintenance.py update-emails >> scheduler.log 2>&1

# 每2小时清理过期
10 */2 * * * cd {os.path.dirname(os.path.abspath(__file__))} && python3 auto_maintenance.py cleanup-expired >> scheduler.log 2>&1

# 每30分钟健康检查
*/30 * * * * cd {os.path.dirname(os.path.abspath(__file__))} && python3 auto_maintenance.py report >> scheduler.log 2>&1
"""
        print("添加到crontab的配置:")
        print(cron_config)
        print("使用命令: crontab -e")
        
    elif args.test:
        # 测试单次执行
        scheduler = MaintenanceScheduler()
        scheduler.health_check()
        
    elif args.run:
        # 运行调度器
        try:
            import schedule
        except ImportError:
            print("请安装schedule库: pip install schedule")
            sys.exit(1)
            
        run_scheduler()
        
    else:
        parser.print_help()
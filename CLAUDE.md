# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个基于FastAPI的Overleaf邀请管理系统，用于批量管理Overleaf群组邀请、卡密系统和成员管理。

## 核心架构

### 技术栈
- **Web框架**: FastAPI + SQLAdmin (管理后台)
- **数据库**: SQLite + SQLAlchemy ORM
- **自动化**: Playwright (浏览器自动化)
- **验证码**: YesCaptcha服务
- **部署**: Uvicorn ASGI服务器

### 核心模块
- `app.py`: 主应用入口，包含FastAPI应用和SQLAdmin管理后台配置
- `models.py`: 数据模型定义（Account账户、Card卡密、Invite邀请）
- `invite_status_manager.py`: **新增**状态管理核心模块，统一处理邀请状态和数据一致性
- `overleaf_utils.py`: Overleaf操作工具函数（登录、获取token、发送邀请）
- `playwright_manager.py`: 单例模式的浏览器管理器，复用Browser实例
- `routers/`: API路由模块，按功能分离（accounts、cards、invites、members等）

### 数据模型关系
- Account (1) -> Invite (N): 一个账户可以发送多个邀请
- Card (1) -> Invite (N): 一个卡密可以对应多个邀请记录
- 核心字段：email_id（Overleaf用户ID）、expires_at（过期时间戳）、group_id（群组ID）

### 邀请状态定义（重构后）
- **PENDING**: 已发送，等待接受（email_id为空，未过期，未清理）
- **ACCEPTED**: 已接受，成员活跃（email_id存在，未清理）
- **EXPIRED**: 已过期，待清理（过期时间<当前时间，未清理）
- **PROCESSED**: 已处理（cleaned=True，包括删除/撤销/过期清理）

## 开发命令

### 启动开发服务器
```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

### 安装依赖
```bash
pip install -r requirements.txt
```

### Playwright浏览器初始化
```bash
playwright install chromium
```

### 数据一致性检查和修复
```bash
# 验证数据一致性
python 脚本目录/fix_data_consistency.py validate

# 修复账户计数 (dry-run)
python 脚本目录/fix_data_consistency.py fix-counts

# 修复账户计数 (实际执行)
python 脚本目录/fix_data_consistency.py fix-counts --apply

# 生成状态报告
python 脚本目录/fix_data_consistency.py report
```

## 重要脚本

### 维护脚本（脚本目录/）
- `remove_expired_members.py`: 清理过期成员
- `update_all_member_email_id.py`: 批量更新成员email_id

### 卡密生成脚本（卡密脚本/）
- `kami.py`: 生成并上传7天/30天卡密到API
- 生成规则：7天卡(3字母+2数字)，30天卡(3字母+3数字)

## API架构设计

### 路由结构
- `/api/v1/accounts/*`: 账户管理
- `/api/v1/cards/*`: 卡密管理  
- `/api/v1/invite/*`: 邀请相关操作
- `/api/v1/member/*`: 成员管理（删除、查询、更新email_id）
- `/api/v1/member/status/*`: **新增**状态监控和数据验证接口
- `/api/v1/member/fix/*`: **新增**数据修复接口
- `/api/v1/maintenance/*`: 系统维护

### 关键业务流程
1. **邀请流程**: 验证卡密 -> 获取/刷新账户session -> 发送Overleaf邀请 -> 记录结果
2. **账户管理**: 使用Playwright获取csrf_token和session_cookie
3. **成员清理**: 使用状态管理器批量处理过期邀请，区分已接受和未接受状态
4. **数据一致性**: 实时计算邀请计数，自动同步账户状态

### 新增监控接口
- `GET /api/v1/member/status/validation`: 验证系统数据一致性
- `GET /api/v1/member/status/account/{email}`: 获取指定账户详细状态
- `GET /api/v1/member/status/global`: 获取全局系统状态
- `POST /api/v1/member/fix/account_counts`: 修复所有账户邀请计数

## 重要配置

### 环境变量（当前硬编码在settings.py，建议改为环境变量）
- `YESCAPTCHA_KEY`: YesCaptcha验证码服务密钥
- `LOGIN_URL`: Overleaf登录页面URL
- `SITE_KEY`: reCaptcha站点密钥

### 数据库
- SQLite文件：`overleaf_inviter.db`
- 自动创建表结构（通过Base.metadata.create_all）

## 安全注意事项

⚠️ **当前存在安全隐患**：
- YesCaptcha API密钥硬编码
- CORS配置允许所有来源
- 生产环境需要配置适当的访问控制

## 系统重构说明（2024年重要更新）

### 重构内容
1. **引入状态管理器**: `invite_status_manager.py`统一管理邀请状态和数据一致性
2. **修复计数逻辑**: 使用实时计算替代缓存计数，解决`invites_sent`不准确问题
3. **优化事务管理**: 删除操作使用事务保护，确保数据一致性
4. **完善错误处理**: 404错误（用户不存在）正确标记为已处理，避免重复尝试

### 字段语义重新定义
- **`success`**: 仅表示邀请发送成功，不代表用户接受状态
- **`cleaned`**: 统一表示该记录已被系统处理（删除/撤销/过期清理）
- **`email_id`**: 存在表示邀请已被接受，为空表示pending状态
- **`invites_sent`**: 实时计算的活跃邀请数量（PENDING + ACCEPTED）

### 使用新功能
```bash
# 验证系统数据一致性
curl http://localhost:8000/api/v1/member/status/validation

# 查看账户状态
curl http://localhost:8000/api/v1/member/status/account/your@email.com

# 修复计数问题
curl -X POST http://localhost:8000/api/v1/member/fix/account_counts

# 批量清理过期邀请（支持智能状态区分）
curl -X POST http://localhost:8000/api/v1/member/cleanup_expired
```

## 测试和调试

### 测试文件
- `test.py`: 简单的网络连接测试脚本

### 日志
- 邀请操作有详细日志记录
- 使用Python标准logging模块

## 部署相关

### 浏览器资源管理
- 使用单例模式的Browser，避免重复创建
- 应用关闭时会自动清理浏览器资源（app.on_event("shutdown")）

### 数据库迁移
- 当前使用SQLAlchemy自动创建表，生产环境建议使用Alembic进行版本控制
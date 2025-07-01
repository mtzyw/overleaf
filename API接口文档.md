# Overleaf邀请管理系统 - 完整API接口文档

## 系统架构概述

这是一个基于FastAPI的Overleaf邀请管理系统，提供完整的邀请生命周期管理、数据一致性保障和自动化运维功能。

**核心特性**：
- 🔄 **智能同步**: 自动检测和修复数据库与Overleaf的差异
- 👤 **手动用户管理**: 专门处理expires_at=NULL的手动添加用户
- 📊 **数据一致性**: 全方位的数据验证和修复机制
- 🚀 **异步处理**: 支持后台批量任务和进度追踪
- 🛡️ **状态管理**: 统一的邀请状态管理器

---

## 📋 完整API接口清单

### 🏢 1. 账户管理 (`/api/v1/accounts`)

#### 1.1 获取账户列表
```http
GET /api/v1/accounts?page=1&size=20&email={email}
```
**功能**: 分页查询账户，支持邮箱筛选
**参数**:
- `page`: 页码，默认1
- `size`: 每页数量，默认20
- `email`: 可选，按邮箱筛选

**响应**: 账户列表

#### 1.2 添加新账户
```http
POST /api/v1/accounts/add
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "password123",
  "group_id": "group123456",
  "max_invites": 100
}
```
**功能**: 创建新的Overleaf账户

#### 1.3 删除账户
```http
POST /api/v1/accounts/delete
Content-Type: application/json

{
  "email": "user@example.com"
}
```
**功能**: 删除指定账户

#### 1.4 刷新账户Token
```http
POST /api/v1/accounts/refresh
Content-Type: application/json

{
  "email": "user@example.com"
}
```
**功能**: 刷新账户的session和CSRF token

---

### 🎫 2. 卡密管理 (`/api/v1/cards`)

#### 2.1 获取卡密列表
```http
GET /api/v1/cards?page=1&size=50&used=false
```
**功能**: 分页查询卡密，支持使用状态筛选
**参数**:
- `page`: 页码，默认1
- `size`: 每页数量，默认50
- `used`: 可选，筛选使用状态

#### 2.2 批量添加卡密
```http
POST /api/v1/cards/add
Content-Type: application/json

[
  {"code": "abc12", "days": 7},
  {"code": "def34", "days": 30}
]
```
**功能**: 批量创建卡密，重复code会被跳过

#### 2.3 删除卡密
```http
POST /api/v1/cards/delete
Content-Type: application/json

{
  "code": "abc12"
}
```
**功能**: 删除指定卡密

---

### 📧 3. 邀请管理 (`/api/v1/invite`)

#### 3.1 发送邀请
```http
POST /api/v1/invite
Content-Type: application/json

{
  "email": "user@example.com",
  "card": "abc12"
}
```
**功能**: 使用卡密向用户发送Overleaf邀请
**特性**:
- 自动选择可用账户
- 支持多账户轮换重试
- 智能处理跨群组用户
- 详细的错误处理和日志

#### 3.2 获取邀请记录
```http
GET /api/v1/invite/records?page=1&size=50&email=user@example.com
```
**功能**: 分页查询邀请记录，支持邮箱筛选

#### 3.3 更新邀请过期时间
```http
POST /api/v1/invite/update_expiration
Content-Type: application/json

{
  "email": "user@example.com",
  "expires_at": 1704067200
}
```
**功能**: 修改指定邮箱的邀请过期时间

#### 3.4 🆕 检测卡密状态
```http
GET /api/v1/invite/detect?card=CARD30D
```
**功能**: 智能检测卡密状态，判断是新邀请还是重新激活模式
**响应示例**:
```json
{
  "mode": "reactivate",
  "email": "user@example.com", 
  "remaining_days": 15,
  "expires_at": 1735660800,
  "can_reactivate": true,
  "message": "检测到绑定邮箱：user@example.com，剩余15天权益"
}
```

#### 3.5 🆕 一键重新激活
```http
POST /api/v1/invite/reactivate
Content-Type: application/json

{
  "card": "CARD30D"
}
```
**功能**: 通过卡密一键重新激活，自动识别绑定邮箱
**特性**:
- 只需要传入卡密，系统自动查找绑定邮箱
- 防止用户输入错误邮箱
- 自动验证权益有效期
- 无缝对接现有邀请逻辑

---

### 👥 4. 成员管理 (`/api/v1/member`)

#### 4.1 删除成员
```http
POST /api/v1/member/remove
Content-Type: application/json

{
  "email": "user@example.com"
}
```
**功能**: 从Overleaf群组中删除已接受邀请的成员
**特性**:
- 使用事务管理器确保数据一致性
- 支持跨群组重复用户检测
- 自动处理404（用户不存在）情况

#### 4.2 撤销未接受邀请
```http
POST /api/v1/member/revoke_unaccepted
Content-Type: application/json

{
  "email": "user@example.com"
}
```
**功能**: 撤销尚未接受的邀请（PENDING状态）

#### 4.3 批量清理过期成员
```http
POST /api/v1/member/cleanup_expired
```
**功能**: 批量清理所有过期的邀请记录
**特性**:
- 智能区分已接受和未接受状态
- 限制单次处理100个记录
- 自动更新账户计数

#### 4.4 数据验证接口
```http
GET /api/v1/member/status/validation
```
**功能**: 验证系统数据一致性，返回发现的问题列表

#### 4.5 获取账户状态
```http
GET /api/v1/member/status/account/{account_email}
```
**功能**: 获取指定账户的详细状态信息

#### 4.6 修复账户计数
```http
POST /api/v1/member/fix/account_counts
```
**功能**: 修复所有账户的邀请计数不一致问题

#### 4.7 获取全局状态
```http
GET /api/v1/member/status/global
```
**功能**: 获取系统整体状态统计

---

### 🔍 5. 成员查询 (`/api/v1/members_query`)

#### 5.1 查询组长成员
```http
GET /api/v1/members_query/leader_members/{leader_email}
```
**功能**: 根据组长邮箱查询其名下所有活跃成员
**响应包含**:
- 总成员数统计
- 活跃成员列表（含过期时间和email_id）
- 过期但未清理的成员数量

---

### 🔧 6. 系统维护 (`/api/v1/maintenance`)

#### 6.1 清理过期记录
```http
POST /api/v1/maintenance/cleanup_expired?delete_records=true&limit=100
```
**功能**: 清理过期邀请记录
**参数**:
- `delete_records`: 是否真正删除记录（默认True）
- `limit`: 单次处理的最大数量（默认100）

---

### 📊 7. 数据一致性管理 (`/api/v1/data-consistency`)

#### 7.1 验证数据一致性
```http
GET /api/v1/data-consistency/validate
```
**功能**: 全面验证系统数据一致性
**检查项目**:
- 账户计数一致性
- 邀请状态逻辑一致性
- 孤立的卡密关联

#### 7.2 生成一致性报告
```http
GET /api/v1/data-consistency/report
```
**功能**: 生成详细的数据一致性报告
**包含信息**:
- 每个账户的详细状态
- 全局统计数据
- 配额使用率

#### 7.3 修复计数问题
```http
POST /api/v1/data-consistency/fix-counts?dry_run=false
```
**功能**: 修复所有账户的邀请计数
**参数**:
- `dry_run`: 是否只预览不实际修复（默认false）

#### 7.4 获取账户一致性
```http
GET /api/v1/data-consistency/account/{email}
```
**功能**: 获取指定账户的详细一致性信息

#### 7.5 清理过期邀请
```http
POST /api/v1/data-consistency/cleanup-expired?dry_run=false&account_email={email}
```
**功能**: 清理过期邀请，支持指定账户
**参数**:
- `dry_run`: 是否只预览（默认false）
- `account_email`: 可选，指定处理的账户

#### 7.6 检查孤立卡密
```http
GET /api/v1/data-consistency/orphaned-cards
```
**功能**: 检查孤立的卡密关联和未使用的卡密

---

### 🔄 8. 数据同步 (`/api/v1/sync`)

#### 8.1 获取同步状态
```http
GET /api/v1/sync/status
```
**功能**: 获取当前同步任务的状态和进度

#### 8.2 启动全量同步
```http
POST /api/v1/sync/all
```
**功能**: 启动所有账户的同步任务（后台异步执行）
**特性**:
- 后台异步处理
- 进度追踪
- 批量处理优化

#### 8.3 同步单个账户
```http
POST /api/v1/sync/account/{email}
```
**功能**: 同步指定账户的数据
**同步内容**:
- 检测Overleaf中的实际成员
- 创建数据库外用户记录
- 修复状态不一致问题
- 更新email_id

#### 8.4 获取同步结果
```http
GET /api/v1/sync/results
```
**功能**: 获取最后一次同步的结果摘要

---

### 👤 9. 手动用户管理 (`/api/v1/manual-users`)

专门管理expires_at=NULL的手动添加用户

#### 9.1 获取手动用户列表
```http
GET /api/v1/manual-users/list?account_email={email}&limit=100
```
**功能**: 获取所有手动添加的用户列表
**参数**:
- `account_email`: 可选，按账户筛选
- `limit`: 返回数量限制（默认100）

#### 9.2 获取手动用户统计
```http
GET /api/v1/manual-users/stats
```
**功能**: 获取手动用户的详细统计信息
**统计内容**:
- 总数统计
- 按账户分布
- 接受/待处理状态统计
- 无卡密关联统计

#### 9.3 设置用户过期时间
```http
POST /api/v1/manual-users/{user_id}/set-expiry
Content-Type: application/json

{
  "days": 30,
  "card_id": 123,
  "note": "客户续费"
}
```
**功能**: 为手动用户设置过期时间，转换为正常管理

#### 9.4 批量设置过期时间
```http
POST /api/v1/manual-users/bulk-set-expiry
Content-Type: application/json

{
  "user_ids": [1, 2, 3],
  "days": 30,
  "card_id": 123,
  "note": "批量续费"
}
```
**功能**: 批量为多个手动用户设置过期时间

#### 9.5 删除手动用户
```http
DELETE /api/v1/manual-users/{user_id}?reason=客户取消
```
**功能**: 删除（标记为已清理）手动用户

#### 9.6 获取用户详情
```http
GET /api/v1/manual-users/{user_id}/details
```
**功能**: 获取手动用户的详细信息和状态

---

### ✉️ 10. 邮箱ID更新 (`/api/v1/email_ids`)

#### 10.1 批量更新邮箱ID
```http
POST /api/v1/email_ids/update
Content-Type: application/json

{
  "leader_email": "leader@example.com"
}
```
**功能**: 从Overleaf获取真实成员数据，更新本地email_id
**特性**:
- 自动解析Overleaf页面数据
- 只更新指定组长账户的记录
- 防止跨群组数据污染

---

## 🚀 使用示例

### 典型业务流程

#### 1. 发送邀请完整流程
```bash
# 1. 添加卡密
curl -X POST "http://localhost:8000/api/v1/cards/add" \
  -H "Content-Type: application/json" \
  -d '[{"code":"test123","days":7}]'

# 2. 发送邀请
curl -X POST "http://localhost:8000/api/v1/invite" \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","card":"test123"}'

# 3. 查看邀请记录
curl "http://localhost:8000/api/v1/invite/records?email=user@example.com"
```

#### 2. 数据一致性检查和修复
```bash
# 1. 验证数据一致性
curl "http://localhost:8000/api/v1/data-consistency/validate"

# 2. 生成详细报告
curl "http://localhost:8000/api/v1/data-consistency/report"

# 3. 修复计数问题
curl -X POST "http://localhost:8000/api/v1/data-consistency/fix-counts"

# 4. 清理过期邀请
curl -X POST "http://localhost:8000/api/v1/member/cleanup_expired"
```

#### 3. 同步Overleaf数据
```bash
# 1. 同步单个账户
curl -X POST "http://localhost:8000/api/v1/sync/account/leader@example.com"

# 2. 启动全量同步
curl -X POST "http://localhost:8000/api/v1/sync/all"

# 3. 查看同步状态
curl "http://localhost:8000/api/v1/sync/status"
```

#### 4. 手动用户管理
```bash
# 1. 查看手动用户列表
curl "http://localhost:8000/api/v1/manual-users/list"

# 2. 为手动用户设置过期时间
curl -X POST "http://localhost:8000/api/v1/manual-users/123/set-expiry" \
  -H "Content-Type: application/json" \
  -d '{"days":30,"card_id":456,"note":"客户续费"}'

# 3. 批量设置过期时间
curl -X POST "http://localhost:8000/api/v1/manual-users/bulk-set-expiry" \
  -H "Content-Type: application/json" \
  -d '{"user_ids":[1,2,3],"days":30,"note":"批量续费"}'
```

#### 5. 🆕 一键重新激活完整流程
```bash
# 1. 检测卡密状态（前端智能判断）
curl "http://localhost:8000/api/v1/invite/detect?card=CARD30D"

# 2. 根据检测结果选择操作：
# 如果是新卡密 -> 正常邀请流程
curl -X POST "http://localhost:8000/api/v1/invite" \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","card":"CARD30D"}'

# 如果可重新激活 -> 一键重新激活
curl -X POST "http://localhost:8000/api/v1/invite/reactivate" \
  -H "Content-Type: application/json" \
  -d '{"card":"CARD30D"}'
```

---

## 📋 邀请状态说明

系统使用统一的状态管理器，邀请状态定义如下：

- **PENDING**: 已发送，等待接受（email_id为空，未过期，未清理）
- **ACCEPTED**: 已接受，成员活跃（email_id存在，未清理）  
- **EXPIRED**: 已过期，待清理（过期时间<当前时间，未清理）
- **PROCESSED**: 已处理（cleaned=True，包括删除/撤销/过期清理）

## 🔐 权限和安全

- 当前版本允许跨域访问（生产环境需要限制）
- YesCaptcha API密钥需要通过环境变量配置
- 建议在生产环境中添加认证中间件

## 📊 监控和日志

- 所有关键操作都有详细日志记录
- 支持实时数据一致性验证
- 提供系统状态监控接口
- 异步任务进度追踪

## 🚀 性能优化

- 使用单例模式管理浏览器资源
- 支持批量操作减少数据库访问
- 异步处理长时间运行的任务
- 智能缓存和会话复用

---

**版本**: v2.0 (2024年重构版本)
**更新日期**: 2024年最新版本

**重要提醒**: 使用前请确保已配置好YesCaptcha服务和Playwright浏览器环境。
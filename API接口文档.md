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
GET /api/v1/accounts?page=1&size=10&email={email}
```
**功能**: 分页查询账户，支持邮箱筛选
**响应**: 账户列表和分页信息

#### 1.2 添加新账户
```http
POST /api/v1/accounts/add
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "password123",
  "group_id": "group123"
}
```

#### 1.3 删除账户
```http
POST /api/v1/accounts/delete
Content-Type: application/json

{
  "email": "user@example.com"
}
```

#### 1.4 刷新账户Token
```http
POST /api/v1/accounts/refresh
Content-Type: application/json

{
  "email": "user@example.com"
}
```
**功能**: 重新登录Overleaf获取最新session和csrf_token

---

### 💳 2. 卡密管理 (`/api/v1/cards`)

#### 2.1 获取卡密列表
```http
GET /api/v1/cards?page=1&size=10&used=false
```
**参数**: used - 筛选已使用/未使用的卡密

#### 2.2 批量新增卡密
```http
POST /api/v1/cards/add
Content-Type: application/json

[
  {
    "code": "ABC123",
    "days": 30
  },
  {
    "code": "XYZ789", 
    "days": 7
  }
]
```

#### 2.3 删除卡密
```http
POST /api/v1/cards/delete
Content-Type: application/json

{
  "card_ids": [1, 2, 3]
}
```

---

### 📧 3. 邀请管理 (`/api/v1/invite`)

#### 3.1 发送邀请（核心功能）
```http
POST /api/v1/invite
Content-Type: application/json

{
  "card_code": "ABC123",
  "email": "newuser@example.com"
}
```
**功能**: 使用卡密发送Overleaf邀请，自动选择可用账户

#### 3.2 查询邀请记录
```http
GET /api/v1/invite/records?page=1&size=10&email={email}
```

#### 3.3 更新邀请过期时间
```http
POST /api/v1/invite/update_expiration
Content-Type: application/json

{
  "email": "user@example.com",
  "additional_days": 30
}
```

---

### 👥 4. 成员查询 (`/api/v1/members_query`)

#### 4.1 查询组长下的所有成员
```http
GET /api/v1/members_query/leader_members/{leader_email}
```
**响应**: 组长名下的活跃成员和过期成员列表

---

### 🔧 5. 成员管理 (`/api/v1/email_ids` & `/api/v1/member`)

#### 5.1 批量更新Email ID
```http
POST /api/v1/email_ids/update
Content-Type: application/json

{
  "leader_email": "leader@example.com"
}
```
**功能**: 从Overleaf拉取真实成员数据更新email_id

#### 5.2 删除已接受的成员
```http
POST /api/v1/member/remove
Content-Type: application/json

{
  "member_email": "member@example.com"
}
```

#### 5.3 撤销未接受的邀请
```http
POST /api/v1/member/revoke_unaccepted
Content-Type: application/json

{
  "member_email": "member@example.com"
}
```

#### 5.4 批量清理过期成员
```http
POST /api/v1/member/cleanup_expired
```

#### 5.5 系统状态监控
```http
GET /api/v1/member/status/validation          # 验证数据一致性
GET /api/v1/member/status/account/{email}     # 指定账户状态
GET /api/v1/member/status/global              # 全局系统状态
POST /api/v1/member/fix/account_counts        # 修复账户计数
```

---

### 🛠️ 6. 维护功能 (`/api/v1/maintenance`)

#### 6.1 清理过期邀请
```http
POST /api/v1/maintenance/cleanup_expired?delete_records=false&limit=100
```
**参数**: 
- delete_records: 是否真正删除记录
- limit: 单次处理数量限制

---

### 🔄 7. 同步管理 (`/api/v1/sync`) ⭐ **新增**

#### 7.1 获取同步状态
```http
GET /api/v1/sync/status
```
**响应**: 当前同步进度、运行状态、预计剩余时间

#### 7.2 启动全部账户同步（异步）
```http
POST /api/v1/sync/all
```
**功能**: 后台异步同步所有25个账户，自动处理数据库外用户
**响应**: 启动确认信息

#### 7.3 同步单个账户
```http
POST /api/v1/sync/account/{email}
```
**功能**: 立即同步指定账户
**响应**: 详细同步结果

#### 7.4 获取上次同步结果
```http
GET /api/v1/sync/results
```
**响应**: 最后一次同步的摘要结果

---

### 👤 8. 手动用户管理 (`/api/v1/manual-users`) ⭐ **新增**

#### 8.1 获取手动用户列表
```http
GET /api/v1/manual-users/list?account_email={email}&limit=100
```
**功能**: 查看所有expires_at=NULL的手动添加用户
**参数**: 可按账户筛选

#### 8.2 获取手动用户统计
```http
GET /api/v1/manual-users/stats
```
**响应**: 总数、按账户分布、接受状态、无卡密数量

#### 8.3 为手动用户设置过期时间
```http
POST /api/v1/manual-users/{user_id}/set-expiry
Content-Type: application/json

{
  "days": 30,
  "card_id": 123,
  "note": "客户确认30天有效期"
}
```

#### 8.4 批量设置过期时间
```http
POST /api/v1/manual-users/bulk-set-expiry
Content-Type: application/json

{
  "user_ids": [1, 2, 3],
  "days": 30,
  "card_id": 123,
  "note": "批量处理"
}
```

#### 8.5 删除手动用户
```http
DELETE /api/v1/manual-users/{user_id}?reason=客户取消订阅
```

#### 8.6 获取手动用户详情
```http
GET /api/v1/manual-users/{user_id}/details
```

---

### 📊 9. 数据一致性管理 (`/api/v1/data-consistency`) ⭐ **新增**

#### 9.1 验证数据一致性
```http
GET /api/v1/data-consistency/validate
```
**功能**: 检查系统是否存在数据不一致问题
**响应**: 问题列表、受影响账户、建议操作

#### 9.2 生成系统状态报告
```http
GET /api/v1/data-consistency/report
```
**功能**: 完整的系统健康报告
**响应**: 所有账户状态、配额使用率、全局统计

#### 9.3 修复账户计数
```http
POST /api/v1/data-consistency/fix-counts?dry_run=false
```
**功能**: 修复所有账户的邀请计数不匹配问题
**参数**: dry_run=true 仅预览，false 实际执行

#### 9.4 获取单个账户详情
```http
GET /api/v1/data-consistency/account/{email}
```
**响应**: 指定账户的详细一致性信息

#### 9.5 清理过期邀请
```http
POST /api/v1/data-consistency/cleanup-expired?dry_run=false&account_email={email}
```
**功能**: 清理过期邀请（自动跳过手动用户）
**参数**: 可指定账户或全部处理

#### 9.6 检查孤立数据
```http
GET /api/v1/data-consistency/orphaned-cards
```
**功能**: 检查孤立的卡密关联和未使用的卡密

---

## 🚀 前端集成建议

### 1. 一键同步功能
```javascript
// 启动全部同步
async function startFullSync() {
  const response = await fetch('/api/v1/sync/all', { method: 'POST' });
  const result = await response.json();
  
  // 轮询检查进度
  const checkProgress = setInterval(async () => {
    const status = await fetch('/api/v1/sync/status').then(r => r.json());
    updateProgressBar(status.progress);
    
    if (!status.is_running) {
      clearInterval(checkProgress);
      showSyncComplete();
    }
  }, 2000);
}
```

### 2. 手动用户管理界面
```javascript
// 获取手动用户列表
async function getManualUsers() {
  const response = await fetch('/api/v1/manual-users/list');
  const users = await response.json();
  return users;
}

// 批量设置过期时间
async function batchSetExpiry(userIds, days) {
  const response = await fetch('/api/v1/manual-users/bulk-set-expiry', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_ids: userIds, days: days })
  });
  return response.json();
}
```

### 3. 定时任务支持
```javascript
// 定时数据一致性检查
setInterval(async () => {
  const validation = await fetch('/api/v1/data-consistency/validate').then(r => r.json());
  if (!validation.is_valid) {
    notifyAdmin('发现数据不一致问题，需要处理');
  }
}, 30 * 60 * 1000); // 每30分钟检查一次

// 定时全量同步
function scheduleAutoSync() {
  // 每天凌晨2点执行全量同步
  const schedule = '0 2 * * *'; // cron格式
  cron.schedule(schedule, async () => {
    await fetch('/api/v1/sync/all', { method: 'POST' });
  });
}
```

### 4. 系统监控面板
```javascript
// 获取系统概览
async function getSystemOverview() {
  const [consistency, manualStats, syncStatus] = await Promise.all([
    fetch('/api/v1/data-consistency/report').then(r => r.json()),
    fetch('/api/v1/manual-users/stats').then(r => r.json()),
    fetch('/api/v1/sync/status').then(r => r.json())
  ]);
  
  return {
    totalAccounts: consistency.total_accounts,
    healthyAccounts: consistency.consistent_accounts,
    manualUsers: manualStats.total_manual_users,
    isSyncing: syncStatus.is_running,
    quotaUtilization: consistency.quota_utilization
  };
}
```

## 📈 推荐使用场景

### 日常运维场景
1. **定期数据同步**: 使用 `/api/v1/sync/all` 每日自动同步
2. **手动用户处理**: 通过 `/api/v1/manual-users/` 接口管理客户续费
3. **系统健康检查**: 定期调用 `/api/v1/data-consistency/validate`
4. **过期清理**: 自动化调用 `/api/v1/data-consistency/cleanup-expired`

### 客户服务场景
1. **邀请发送**: 核心接口 `/api/v1/invite`
2. **成员查询**: 使用 `/api/v1/members_query/leader_members/{email}`
3. **延期服务**: `/api/v1/invite/update_expiration`
4. **成员删除**: `/api/v1/member/remove` 或 `/api/v1/member/revoke_unaccepted`

### 故障排查场景
1. **数据不一致**: `/api/v1/data-consistency/validate` + `/api/v1/data-consistency/fix-counts`
2. **孤立数据**: `/api/v1/data-consistency/orphaned-cards`
3. **账户状态**: `/api/v1/data-consistency/account/{email}`
4. **手动修复**: 各种 dry_run 参数预览再执行

## ✨ 核心功能特点

✅ **异步处理**: 同步任务在后台运行，不会阻塞API
✅ **进度跟踪**: 实时查询同步进度和状态
✅ **数据安全**: 所有操作都有dry_run预览模式
✅ **智能同步**: 自动处理数据库外用户，维护数据一致性
✅ **批量操作**: 支持批量设置过期时间和删除用户
✅ **详细日志**: 每个操作都有详细的结果和元数据记录
✅ **状态管理**: 统一的邀请状态管理器确保数据准确性
✅ **容错机制**: 完善的错误处理和重试逻辑

## 🎯 系统优化建议

1. **添加API认证**: 建议添加JWT或API Key认证机制
2. **请求限流**: 防止API被滥用，特别是同步相关接口
3. **操作日志**: 记录所有API调用和数据变更日志
4. **数据备份**: 重要操作前自动备份数据库
5. **监控告警**: 集成监控系统，异常时自动告警

现在你可以通过这些API接口实现：
1. 🔄 前端一键同步所有账户
2. ⏰ 定时自动数据一致性检查  
3. 🖥️ 可视化的手动用户管理界面
4. 🗑️ 自动化的过期邀请清理
5. 📊 系统健康状态监控
6. 🎯 完整的运维自动化流程
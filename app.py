# app.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from database import engine, Base
import models
from playwright_manager import close_browser


# 自动创建所有表
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Overleaf Inviter 管理后台")
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# --- CORS 设置 START ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],         # 生产环境请替换为严格的白名单
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- CORS 设置 END ---

# --- SQLAdmin 管理后台 START ---
from sqladmin import Admin, ModelView

admin = Admin(app, engine, title="Overleaf Inviter Admin")

class AccountAdmin(ModelView, model=models.Account):
    column_list = [
        models.Account.id,
        models.Account.email,
        models.Account.group_id,
        models.Account.invites_sent,
        models.Account.max_invites,
        models.Account.updated_at,
    ]
    can_create = True
    can_edit   = True
    can_delete = True

class CardAdmin(ModelView, model=models.Card):
    column_list = [
        models.Card.id,
        models.Card.code,
        models.Card.days,
        models.Card.used,
    ]
    can_create = True
    can_edit   = True
    can_delete = True

class InviteAdmin(ModelView, model=models.Invite):
    column_list = [
        models.Invite.id,
        models.Invite.account_id,
        models.Invite.card_id,
        models.Invite.email,
        models.Invite.email_id,
        models.Invite.expires_at,
        models.Invite.success,
        models.Invite.result,
        models.Invite.created_at,
    ]
    can_create = False
    can_edit   = True
    can_delete = True

admin.add_view(AccountAdmin)
admin.add_view(CardAdmin)
admin.add_view(InviteAdmin)
# --- SQLAdmin 管理后台 END ---

# 挂载子路由 —— 不要用 prefix，这里 routers 里已经写了完整路径
from routers.accounts import router as accounts_router
from routers.cards import    router as cards_router
from routers.invites import  router as invite_router
from routers.update_email_id import router as update_email_id_router
from routers.remove_member   import router as remove_member_router
from routers.maintenance import router as maintenance_router

app.include_router(accounts_router,    tags=["accounts"])
app.include_router(cards_router,       tags=["cards"])
app.include_router(invite_router,      tags=["invites"])
app.include_router(update_email_id_router, tags=["members"])
app.include_router(remove_member_router,   tags=["members"])
app.include_router(maintenance_router, tags=["maintenance"])

@app.on_event("shutdown")
async def on_shutdown():
    await close_browser()

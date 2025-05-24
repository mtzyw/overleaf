# settings.py

class Settings:
    # Overleaf 登录页
    LOGIN_URL = "https://www.overleaf.com/login"

    # YesCaptcha 服务配置
    YESCAPTCHA_KEY = "1a41fe89a169c17ebc4285ba9b4b8056678fb2a546600"
    SITE_KEY       = "6LebiTwUAAAAAMuPyjA4pDA4jxPxPe2K9_ndL74Q"

    # SQLite 数据库路径
    SQLALCHEMY_DATABASE_URL = "sqlite:///./overleaf_inviter.db"


settings = Settings()

import os

def get_db_url():
    host = os.getenv("DB_HOST", "db")
    port = os.getenv("DB_PORT", "5432")
    user = os.getenv("DB_USER", "yao")
    password = os.getenv("DB_PASSWORD", "3141")
    dbname = os.getenv("DB_NAME", "pvd_db")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

def get_admin_password():
    return os.getenv("ADMIN_PWD", "default_pwd")

def get_nas_mount():
    return os.getenv("NAS_MOUNT", "/app/nas_data")

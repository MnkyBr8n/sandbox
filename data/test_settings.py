"""Quick test to verify settings are loading from .env"""
from sandbox.app.config.settings import get_settings

settings = get_settings()

print(f"Environment: {settings.environment}")
print(f"Postgres DSN: {settings.postgres_dsn}")
print(f"Schema path: {settings.notebook_schema_path}")
print(f"Schema exists: {settings.notebook_schema_path.exists()}")
print(f"Log level: {settings.log_level}")

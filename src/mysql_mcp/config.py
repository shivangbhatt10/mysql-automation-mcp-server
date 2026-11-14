"""Configuration management for MySQL MCP server using pydantic-settings, user-level config, and python-dotenv."""

from functools import lru_cache
import json
from pathlib import Path
import tempfile
from typing import Any, Dict, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# User-level cross-platform persistent directory: ~/.mysql-mcp
USER_DATA_DIR = Path.home() / ".mysql-mcp"
CONFIG_FILE = USER_DATA_DIR / "config.json"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def load_persisted_config() -> Dict[str, Any]:
    """Load user configuration saved in ~/.mysql-mcp/config.json if it exists."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def persist_config(updates: Dict[str, Any]) -> None:
    """Save or update user configuration in ~/.mysql-mcp/config.json."""
    try:
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        current = load_persisted_config()
        # Filter out None values and update
        for k, v in updates.items():
            if v is not None:
                current[k] = v
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
    except Exception:
        pass


def clear_persisted_config() -> None:
    """Remove user configuration file ~/.mysql-mcp/config.json."""
    if CONFIG_FILE.exists():
        try:
            CONFIG_FILE.unlink()
        except Exception:
            pass


class Settings(BaseSettings):
    """
    Application settings loaded with cascading priority:
    1. Explicit environment variables (MYSQL_HOST, MYSQL_USER, etc.)
    2. .env file in workspace
    3. Persisted user configuration in ~/.mysql-mcp/config.json
    4. Default values
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # MySQL connection configuration
    mysql_host: str = Field(default="localhost", description="MySQL server hostname or IP")
    mysql_port: int = Field(default=3306, description="MySQL server port")
    mysql_user: str = Field(default="root", description="MySQL username")
    mysql_password: str = Field(default="", description="MySQL user password")
    mysql_database: Optional[str] = Field(
        default=None,
        description="Active MySQL database name. Can be None if connected at instance level.",
    )

    # Query limits
    mysql_default_limit: int = Field(default=50, description="Default LIMIT for SELECT queries")
    mysql_max_limit: int = Field(default=1000, description="Maximum permitted LIMIT for SELECT queries")

    # Cross-platform user data directories (defaults to ~/.mysql-mcp/exports and ~/.mysql-mcp/cache)
    mysql_exports_dir: Path = Field(
        default=USER_DATA_DIR / "exports",
        description="Directory for exported query results",
    )
    mysql_cache_dir: Path = Field(
        default=USER_DATA_DIR / "cache",
        description="Directory for cached schemas and queries",
    )

    # Connection pooling configuration
    mysql_pool_size: int = Field(default=5, description="Initial/base connection pool size")
    mysql_pool_max_overflow: int = Field(default=10, description="Maximum overflow connections beyond pool size")
    mysql_pool_timeout: float = Field(default=30.0, description="Seconds to wait before timing out on connection checkout")
    mysql_connect_timeout: int = Field(default=10, description="Seconds to wait for establishing a TCP MySQL connection")
    mysql_charset: str = Field(default="utf8mb4", description="MySQL character set")

    @field_validator("mysql_exports_dir", "mysql_cache_dir", mode="after")
    @classmethod
    def resolve_directory_path(cls, path_val: Path) -> Path:
        """Resolve relative directory paths safely against USER_DATA_DIR or PROJECT_ROOT."""
        if not path_val.is_absolute():
            # If path starts with exports or cache, resolve in USER_DATA_DIR
            return (USER_DATA_DIR / path_val).resolve()
        return path_val.resolve()

    def ensure_directories(self) -> None:
        """
        Ensure exports and cache directories exist on the filesystem.
        Falls back to the system temp directory if configured locations encounter permission issues.
        """
        for attr, fallback_subdir in [
            ("mysql_exports_dir", "exports"),
            ("mysql_cache_dir", "cache"),
        ]:
            target_path: Path = getattr(self, attr)
            try:
                target_path.mkdir(parents=True, exist_ok=True)
            except (OSError, PermissionError):
                fallback_path = Path(tempfile.gettempdir()) / "mysql_mcp" / fallback_subdir
                try:
                    fallback_path.mkdir(parents=True, exist_ok=True)
                    setattr(self, attr, fallback_path)
                except Exception:
                    pass

    def get_connection_dict(self, database: Optional[str] = None) -> Dict[str, Any]:
        """Return connection parameter dictionary for pymysql.connect."""
        params: Dict[str, Any] = {
            "host": self.mysql_host,
            "port": self.mysql_port,
            "user": self.mysql_user,
            "password": self.mysql_password,
            "charset": self.mysql_charset,
            "connect_timeout": self.mysql_connect_timeout,
        }
        db = database if database is not None else self.mysql_database
        if db:
            params["database"] = db
        return params


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton instance of Settings, overlaying persisted config if present."""
    # 1. Base settings from env and .env
    settings = Settings()

    # 2. Overlay persisted configuration from ~/.mysql-mcp/config.json for any field not explicitly in .env
    persisted = load_persisted_config()
    if persisted:
        if "mysql_host" in persisted and not settings.mysql_host:
            settings.mysql_host = persisted["mysql_host"]
        if "mysql_port" in persisted and not settings.mysql_port:
            settings.mysql_port = int(persisted["mysql_port"])
        if "mysql_user" in persisted and not settings.mysql_user:
            settings.mysql_user = persisted["mysql_user"]
        if "mysql_password" in persisted and not settings.mysql_password:
            settings.mysql_password = persisted["mysql_password"]
        if "mysql_database" in persisted and not settings.mysql_database:
            settings.mysql_database = persisted["mysql_database"]

    try:
        settings.ensure_directories()
    except Exception:
        pass

    return settings

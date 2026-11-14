"""Configuration management for MySQL MCP server using pydantic-settings and python-dotenv."""

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

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
    mysql_database: str = Field(default="ecommerce_demo", description="Default database name")

    # Query limits
    mysql_default_limit: int = Field(default=50, description="Default LIMIT for SELECT queries")
    mysql_max_limit: int = Field(default=1000, description="Maximum permitted LIMIT for SELECT queries")

    # Directories
    mysql_exports_dir: Path = Field(default=Path("./exports"), description="Directory for exported query results")
    mysql_cache_dir: Path = Field(default=Path("./cache"), description="Directory for cached schemas and queries")

    # Connection pooling configuration
    mysql_pool_size: int = Field(default=5, description="Initial/base connection pool size")
    mysql_pool_max_overflow: int = Field(default=10, description="Maximum overflow connections beyond pool size")
    mysql_pool_timeout: float = Field(default=30.0, description="Seconds to wait before timing out on connection checkout")
    mysql_connect_timeout: int = Field(default=10, description="Seconds to wait for establishing a TCP MySQL connection")
    mysql_charset: str = Field(default="utf8mb4", description="MySQL character set")

    def ensure_directories(self) -> None:
        """Ensure exports and cache directories exist on the filesystem."""
        self.mysql_exports_dir.mkdir(parents=True, exist_ok=True)
        self.mysql_cache_dir.mkdir(parents=True, exist_ok=True)

    def get_connection_dict(self, database: str | None = None) -> Dict[str, Any]:
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
    """Return a cached singleton instance of Settings."""
    settings = Settings()
    settings.ensure_directories()
    return settings


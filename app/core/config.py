"""Configuración centralizada de jg_agente basada en Pydantic Settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Entorno y servicio
    ENV: str = Field(
        default="development", description="Entorno de ejecución (development, staging, production)"
    )
    DEBUG: bool = Field(default=False, description="Modo depuración")
    AGENT_ID: str = Field(default="jg_agente_local", description="Identificador único del agente")
    AGENT_PORT: int = Field(default=8000, description="Puerto interno de escucha")

    # PostgreSQL para Checkpoints y tablas core_*
    POSTGRES_HOST: str = Field(default="jg_agente_postgres", description="Host de PostgreSQL")
    POSTGRES_PORT: int = Field(default=5432, description="Puerto de PostgreSQL")
    POSTGRES_USER: str = Field(default="postgres", description="Usuario de base de datos")
    POSTGRES_PASSWORD: str = Field(default="postgres", description="Contraseña de base de datos")
    POSTGRES_DB: str = Field(default="jg_agente", description="Nombre de la base de datos")
    DATABASE_URL: str | None = Field(default=None, description="URL de conexión SQLAlchemy async")

    @property
    def async_database_url(self) -> str:
        """Devuelve la URL asíncrona normalizada para SQLAlchemy (asyncpg)."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()

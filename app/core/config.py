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
    AGENT_NAME: str | None = Field(
        default=None, description="Nombre descriptivo del agente para el Dashboard"
    )
    AGENT_PORT: int = Field(default=8000, description="Puerto interno de escucha")

    # Registro y comunicación con jg_dashboard (Control Plane)
    DASHBOARD_URL: str = Field(
        default="http://jg_dashboard:8080", description="URL base de jg_dashboard"
    )
    AGENT_BOOTSTRAP_TOKEN: str | None = Field(
        default=None, description="Token temporal de registro de 24h emitido por Dashboard"
    )
    PERMANENT_AGENT_SECRET: str | None = Field(
        default=None, description="Secreto permanente del agente emitido por Dashboard"
    )
    CREDENTIALS_FILE: str = Field(
        default=".agent_credentials.json",
        description="Ruta al archivo local para persistir credenciales de forma segura",
    )
    DASHBOARD_REGISTRATION_TIMEOUT: float = Field(
        default=10.0, description="Timeout en segundos para registro con Dashboard"
    )
    DASHBOARD_REGISTRATION_RETRIES: int = Field(
        default=3, description="Número de reintentos para registro ante fallos transitorios"
    )
    REQUIRE_DASHBOARD_REGISTRATION: bool = Field(
        default=False, description="Exige registro exitoso obligatorio contra el Dashboard en boot"
    )
    VERIFY_CREDENTIALS_ON_BOOT: bool = Field(
        default=True,
        description="Verifica activamente la credencial permanente contra el Dashboard en el arranque",
    )

    # PostgreSQL para Checkpoints y tablas core_*
    POSTGRES_HOST: str = Field(default="jg_agente_postgres", description="Host de PostgreSQL")
    POSTGRES_PORT: int = Field(default=5432, description="Puerto de PostgreSQL")
    POSTGRES_USER: str = Field(default="postgres", description="Usuario de base de datos")
    POSTGRES_PASSWORD: str = Field(default="postgres", description="Contraseña de base de datos")
    POSTGRES_DB: str = Field(default="jg_agente", description="Nombre de la base de datos")
    DATABASE_URL: str | None = Field(default=None, description="URL de conexión SQLAlchemy async")

    # Seguridad y protección SSRF
    SSRF_ENFORCE_PROTECTION: bool = Field(
        default=True, description="Habilita la validación y bloqueo estricto contra SSRF"
    )
    SSRF_ALLOWED_HOSTS: list[str] = Field(
        default_factory=list,
        description="Dominios y hostnames explícitamente permitidos para tools de red",
    )
    SSRF_ALLOWED_NETWORKS: list[str] = Field(
        default_factory=list,
        description="Rangos de red CIDR explícitamente permitidos (ej. '10.200.0.0/24')",
    )
    SSRF_ALLOW_PRIVATE_NETWORKS: bool = Field(
        default=False,
        description="Habilita el acceso a redes privadas si se autoriza explícitamente por configuración",
    )

    # Perfil de capacidades y plugins para validación en boot
    PLUGINS_DIR: str | None = Field(
        default=None,
        description="Directorio local alternativo para escaneo de plugins",
    )
    REQUIRED_PLUGINS: list[str] = Field(
        default_factory=list,
        description="Lista de nombres de plugins obligatorios para el arranque del agente",
    )
    REQUIRED_TOOLS: list[str] = Field(
        default_factory=list,
        description="Lista de nombres de herramientas obligatorias para el arranque del agente",
    )
    REQUIRE_PLANNER: bool = Field(
        default=False,
        description="Exige la presencia obligatoria de un PlannerEngine registrado",
    )
    REQUIRE_OBSERVER: bool = Field(
        default=False,
        description="Exige la presencia obligatoria de un ObserverEngine registrado",
    )
    REQUIRE_VERIFIER: bool = Field(
        default=False,
        description="Exige la presencia obligatoria de un VerifierEngine registrado",
    )

    # Proveedor de Modelos de Lenguaje (LLM)
    LLM_PROVIDER: str = Field(
        default="mock",
        description="Proveedor de LLM a utilizar ('mock', 'openai', 'custom', 'ollama')",
    )
    LLM_MODEL: str = Field(
        default="gpt-4o-mini",
        description="Nombre del modelo cognitivo a emplear",
    )
    LLM_API_KEY: str | None = Field(
        default=None,
        description="Clave de API para el proveedor de LLM",
    )
    LLM_BASE_URL: str | None = Field(
        default=None,
        description="URL base para APIs compatibles con OpenAI / proxies locales",
    )
    LLM_TEMPERATURE: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Temperatura de muestreo para el LLM",
    )
    LLM_MAX_TOKENS: int = Field(
        default=2048,
        gt=0,
        description="Máximo de tokens por respuesta del LLM",
    )
    DEFAULT_SYSTEM_PROMPT: str = Field(
        default=(
            "Eres un agente inteligente autónomo de ejecución orientado a objetivos. "
            "Analiza las solicitudes, decide si debes invocar herramientas o responder directamente, "
            "y actúa con máxima precisión, seguridad y concisión."
        ),
        description="Prompt del sistema base para el razonamiento cognitivo",
    )

    @property
    def async_database_url(self) -> str:
        """Devuelve la URL asíncrona normalizada para SQLAlchemy (asyncpg o aiosqlite)."""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def sync_database_url(self) -> str:
        """Devuelve la URL síncrona normalizada para inspección y utilidades."""
        if self.DATABASE_URL:
            return self.DATABASE_URL.replace("+asyncpg", "").replace("+aiosqlite", "")
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()

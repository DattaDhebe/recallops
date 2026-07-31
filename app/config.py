from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "RecallOps"
    database_url: str = "sqlite:///./incident_memory.db"
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "amazon.nova-lite-v1:0"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    embedding_dimensions: Literal[512] = 512
    use_bedrock: bool = False
    require_cockroachdb: bool = False
    competition_mode: bool = False
    use_cockroach_mcp: bool = False
    cockroach_mcp_url: str = "https://cockroachlabs.cloud/mcp"
    cockroach_mcp_api_key: str | None = None
    cockroach_mcp_cluster_id: str | None = None
    cockroach_mcp_database: str = "defaultdb"
    cockroach_mcp_timeout_seconds: float = Field(default=20.0, gt=0, le=30)
    minimum_relevance: float = Field(default=0.15, ge=0, le=1)
    api_key: str | None = None
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def validate_runtime_integrations(self) -> None:
        """Fail closed when an enabled integration is missing its scope or secret."""

        if self.competition_mode:
            missing: list[str] = []
            if not self.require_cockroachdb:
                missing.append("REQUIRE_COCKROACHDB=true")
            if not self.use_bedrock:
                missing.append("USE_BEDROCK=true")
            if not self.use_cockroach_mcp:
                missing.append("USE_COCKROACH_MCP=true")
            if not self.api_key:
                missing.append("API_KEY")
            if missing:
                raise RuntimeError(
                    "COMPETITION_MODE is enabled, but required production settings are missing: "
                    + ", ".join(missing)
                )

        if not self.use_cockroach_mcp:
            return
        if not self.cockroach_mcp_api_key:
            raise RuntimeError(
                "USE_COCKROACH_MCP is enabled, but COCKROACH_MCP_API_KEY is not configured"
            )
        if not self.cockroach_mcp_cluster_id:
            raise RuntimeError(
                "USE_COCKROACH_MCP is enabled, but COCKROACH_MCP_CLUSTER_ID is not configured"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()

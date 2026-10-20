from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # Pluggy
    pluggy_client_id: str = ""
    pluggy_client_secret: str = ""
    pluggy_client_user_id: str = "cfo-central"
    pluggy_connector_ids: str = "200"  # 200 = MeuPluggy; "*" = todos
    pluggy_include_sandbox: bool = False
    pluggy_item_ids: str = ""  # itens extras (vírgula)

    # Infra
    database_url: str = "postgresql+psycopg://cfo:cfo@localhost:5432/cfo"
    secret_key: str = Field(default="troque-esta-chave", min_length=8)
    session_hours: int = 12
    public_url: str = ""  # habilita webhookUrl no connect token
    frontend_dist: Path = ROOT / "frontend" / "dist"
    timezone: str = "America/Sao_Paulo"

    # Rotinas
    scheduler_enabled: bool = True
    pluggy_sync_hours: float = 4
    market_sync_hour: int = 19
    tx_window_days: int = 90  # releitura incremental

    # Regras de negócio
    review_min_amount: float = 50.0
    review_min_confidence: float = 0.6
    # pendente sem efetivação há mais de N dias deixa de contar (razão, saldo histórico e saúde); vale para conta corrente
    pending_stale_days: int = 10  # conta corrente
    # no cartão o pendente é a compra ainda não faturada (vive até o fechamento): limite bem maior
    pending_stale_days_card: int = 40
    fgc_limit: float = 250_000.0
    classifier_enabled: bool = True  # classificador treinado nas suas decisões (scikit-learn)
    owner_names: str = ""  # nomes do titular p/ detectar transferência própria (vírgula)

    # Alertas por e-mail (Gmail: smtp.gmail.com:587 + senha de app)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_to: str = ""  # vazio = smtp_user
    alerts_hour: int = 8      # resumo diário de alertas (horário de Brasília)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_user and self.smtp_password)

    @property
    def connector_ids(self) -> list[int]:
        raw = [x.strip() for x in self.pluggy_connector_ids.split(",") if x.strip()]
        return [] if "*" in raw else [int(x) for x in raw]

    @property
    def extra_item_ids(self) -> list[str]:
        return [x.strip() for x in self.pluggy_item_ids.split(",") if x.strip()]

    @property
    def webhook_url(self) -> str | None:
        return f"{self.public_url.rstrip('/')}/api/webhooks/pluggy" if self.public_url else None


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""An explicit response allowlist: configuration values never enter this DTO."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

CheckCode = Literal[
    "mail_enabled",
    "host",
    "port",
    "authentication",
    "sender",
    "tls",
    "timeout",
    "account_sid",
    "auth_token",
    "sdk",
    "credentials_reference",
    "credentials_file",
]
CheckState = Literal["ok", "missing", "invalid", "disabled"]
ProviderState = Literal["paused", "incomplete", "locally_configured"]


class ProviderConfigurationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: CheckCode
    state: CheckState


class ProviderDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: Literal["EMAIL", "SMS", "PUSH"]
    provider: Literal["SMTP", "TWILIO", "FCM"]
    state: ProviderState
    checks: list[ProviderConfigurationCheck]


class NotificationProviderDiagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    scope: Literal["local_only"] = "local_only"
    external_delivery_verified: Literal[False] = False
    checked_at: str
    notifications_enabled: bool
    providers: list[ProviderDiagnostic] = Field(min_length=3, max_length=3)

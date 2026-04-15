import time
from pathlib import Path

from pydantic_settings import BaseSettings

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class IBConfig(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 7497  # TWS paper: 7497, TWS live: 7496, GW paper: 4002, GW live: 4001
    client_id: int = hash(time.time_ns()) % 2**16
    readonly: bool = True  # Safety: read-only by default for R&D

    model_config = {"env_prefix": "IB_", "env_file": str(_ENV_FILE)}

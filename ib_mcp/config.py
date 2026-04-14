from pydantic_settings import BaseSettings


class IBConfig(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 7497  # TWS paper: 7497, TWS live: 7496, GW paper: 4002, GW live: 4001
    client_id: int = 1
    readonly: bool = True  # Safety: read-only by default for R&D

    model_config = {"env_prefix": "IB_"}

"""Client configuration management."""

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class ClientConfig:
    """Client configuration."""

    def __init__(
        self,
        server: str = "http://localhost:19420",
        device_id: str | None = None,
        api_key: str | None = None,
    ):
        self.server = server
        self.device_id = device_id
        self.api_key = api_key

    @classmethod
    def load(cls, config_path: Path | None = None) -> "ClientConfig":
        """Load config from file or use defaults."""
        if config_path is None:
            # Try default locations
            config_path = cls.get_default_config_path()

        if config_path.exists():
            try:
                with open(config_path) as f:
                    data = yaml.safe_load(f)
                    logger.info(f"Loaded config from {config_path}")
                    return cls(
                        server=data.get("server", "http://localhost:19420"),
                        device_id=data.get("device_id"),
                        api_key=data.get("api_key"),
                    )
            except Exception as e:
                logger.warning(f"Failed to load config from {config_path}: {e}")

        logger.info("Using default config (no config file found)")
        return cls()

    @staticmethod
    def get_default_config_path() -> Path:
        """Get default config file path for the platform."""
        import platform

        if platform.system() == "Windows":
            # Windows: %USERPROFILE%\.cortex\client.yaml
            home = Path.home()
            return home / ".cortex" / "client.yaml"
        else:
            # Linux/Mac: ~/.config/cortex/client.yaml
            from os import environ

            config_dir = Path(environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            return config_dir / "cortex" / "client.yaml"

    def save(self, config_path: Path | None = None) -> None:
        """Save config to file."""
        if config_path is None:
            config_path = self.get_default_config_path()

        config_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "server": self.server,
            "device_id": self.device_id,
            "api_key": self.api_key,
        }

        with open(config_path, "w") as f:
            yaml.safe_dump(data, f)

        logger.info(f"Saved config to {config_path}")

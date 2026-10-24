"""Settings from the environment. Refuses to start when a required key is missing."""
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

MAX_LEVEL = 60

REQUIRED = ("DATABASE_URL", "PUBLIC_ORIGIN", "SESSION_PEPPER")
REQUIRED_MAIL = ("MAIL_FROM", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str
    public_origin: str
    session_pepper: str
    mail_from: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    dev: bool = False
    static_root: Path | None = None
    data_root: Path | None = None
    media_root: Path | None = None

    @property
    def host(self) -> str:
        return urlsplit(self.public_origin).hostname or ""

    @property
    def cookie_name(self) -> str:
        return "jstudy" if self.dev else "__Host-jstudy"

    @classmethod
    def from_env(cls, env=os.environ) -> "Settings":
        dev = env.get("JSTUDY_DEV") == "1"
        missing = [k for k in REQUIRED if not env.get(k)]
        if not dev:
            missing += [k for k in REQUIRED_MAIL if not env.get(k)]
        if missing:
            raise ConfigError("missing required settings: " + ", ".join(missing))
        origin = env["PUBLIC_ORIGIN"].rstrip("/")
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.path or parts.query or parts.fragment:
            raise ConfigError("PUBLIC_ORIGIN must look like https://host[:port]")
        if dev and parts.hostname not in LOOPBACK_HOSTS:
            raise ConfigError("JSTUDY_DEV=1 needs a loopback PUBLIC_ORIGIN (http://127.0.0.1:port)")
        if not dev and parts.scheme != "https":
            raise ConfigError("PUBLIC_ORIGIN must be https outside dev mode (the __Host- cookie needs it)")
        if len(env["SESSION_PEPPER"]) < 16:
            raise ConfigError("SESSION_PEPPER is too short, use openssl rand -base64 32")
        return cls(
            database_url=env["DATABASE_URL"],
            public_origin=origin,
            session_pepper=env["SESSION_PEPPER"],
            mail_from=env.get("MAIL_FROM", ""),
            smtp_host=env.get("SMTP_HOST", ""),
            smtp_port=int(env.get("SMTP_PORT") or 587),
            smtp_user=env.get("SMTP_USER", ""),
            smtp_password=env.get("SMTP_PASSWORD", ""),
            google_client_id=env.get("GOOGLE_CLIENT_ID", ""),
            google_client_secret=env.get("GOOGLE_CLIENT_SECRET", ""),
            dev=dev,
            static_root=_directory(env, "JSTUDY_STATIC_ROOT") if dev else None,
            data_root=_directory(env, "JSTUDY_DATA_ROOT") if dev else None,
            media_root=_directory(env, "JSTUDY_MEDIA_ROOT") if dev else None,
        )


def _directory(env, key: str) -> Path | None:
    value = env.get(key)
    if not value:
        return None
    path = Path(value).resolve()
    if not path.is_dir():
        raise ConfigError(f"{key} is not a directory: {value}")
    return path


def load_env_file(path: str, env=os.environ) -> None:
    """Reads KEY=VALUE lines (systemd EnvironmentFile style) into env without overriding what is already set."""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        env.setdefault(key.strip(), value)

"""Application configuration sourced from environment variables."""
import os
from pathlib import Path

class Config:
    @staticmethod
    def apply(app):
        env_file = Path(app.root_path) / ".env"
        if env_file.is_file():
            for raw_line in env_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key, value = key.strip(), value.strip().strip("\"'")
                if key and value and not os.environ.get(key):
                    os.environ[key] = value
        app.config.update(
            SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-this-key"),
            SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL") or f"sqlite:///{Path(app.instance_path, 'medishield.db').as_posix()}",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
            SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
        )

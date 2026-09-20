import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    data: Path
    password: str
    secret: str
    secure: bool
    site_title: str
    site_description: str
    upload_limit: int
    extract_limit: int
    zip_entries: int
    base_domain: str = ""

    @classmethod
    def load(cls) -> "Config":
        import secrets

        password = os.getenv("ADMIN_PASSWORD", "")
        if not password:
            raise RuntimeError("ADMIN_PASSWORD is required")
        if os.getenv("PROJECTS_SANDBOX", "true").lower() != "true":
            raise RuntimeError("PROJECTS_SANDBOX must stay true for same-origin hosting")
        data = Path(os.getenv("DATA_DIR", "/data")).resolve()
        for folder in (data, data / "projects", data / "media", data / "tmp"):
            folder.mkdir(parents=True, exist_ok=True)
        key_path = data / "secret_key"
        secret = os.getenv("SECRET_KEY", "")
        if not secret:
            if not key_path.exists():
                key_path.write_text(secrets.token_hex(32))
                key_path.chmod(0o600)
            secret = key_path.read_text().strip()
        base_domain = os.getenv("BASE_DOMAIN", "").strip().lower()
        return cls(
            data=data,
            password=password,
            secret=secret,
            secure=os.getenv("COOKIE_SECURE", "true").lower() == "true",
            site_title=os.getenv("SITE_TITLE", "SiteFlow"),
            site_description=os.getenv("SITE_DESCRIPTION", "一些想法，一些尝试，一些值得分享的作品。"),
            upload_limit=int(os.getenv("MAX_UPLOAD_MB", "100")) * 1024 * 1024,
            extract_limit=int(os.getenv("MAX_EXTRACT_MB", "500")) * 1024 * 1024,
            zip_entries=int(os.getenv("MAX_ZIP_ENTRIES", "5000")),
            base_domain=base_domain,
        )

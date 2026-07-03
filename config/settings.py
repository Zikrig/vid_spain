import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _parse_admin_ids(raw: str) -> frozenset[int]:
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    bot_token: str = os.environ["BOT_TOKEN"]
    admin_ids: frozenset[int] = field(
        default_factory=lambda: _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
    )
    consultation_url: str = os.getenv(
        "CONSULTATION_URL",
        "https://example.com/consultation?utm_source={source}&tg_id={user_id}",
    )
    database_url: str = os.getenv(
        "DATABASE_URL", "sqlite+aiosqlite:///data/bot.db"
    )
    start_image_path: Path = BASE_DIR / "assets" / "start_image.png"


settings = Settings()

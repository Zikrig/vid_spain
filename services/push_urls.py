from config.settings import settings
from services.models import User


def consultation_url(user: User) -> str:
    return settings.consultation_url.format(
        source=user.source or "direct",
        user_id=user.id,
    )


def resolve_push_button_url(url_template: str | None, user: User) -> str | None:
    if not url_template:
        return None
    return url_template.replace("{consultation_url}", consultation_url(user))


def push_button_url(push, user: User) -> str | None:
    return resolve_push_button_url(push.button_url, user) or (
        consultation_url(user) if push.button_text else None
    )

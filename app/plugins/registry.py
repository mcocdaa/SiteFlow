from app.plugins.base import AppPlugin
from app.plugins.resume.plugin import ResumePlugin

_apps: dict[str, AppPlugin] = {}


def register(plugin: AppPlugin) -> None:
    _apps[plugin.type] = plugin


def get(app_type: str) -> AppPlugin | None:
    return _apps.get(app_type)


def all_apps() -> list[AppPlugin]:
    return list(_apps.values())


register(ResumePlugin())

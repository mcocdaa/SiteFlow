from app.plugins.base import AppPlugin

_apps: dict[str, AppPlugin] = {}


def register(plugin: AppPlugin) -> None:
    _apps[plugin.type] = plugin


def get(app_type: str) -> AppPlugin | None:
    return _apps.get(app_type)


def all_apps() -> list[AppPlugin]:
    return list(_apps.values())

"""群聊昵称优先插件入口。"""

from __future__ import annotations

from src.app.plugin_system.base import BasePlugin, register_plugin

from .config import GroupCardnamePreferenceConfig
from .event_handler import (
    GroupCardnameHistoryFormatterHandler,
    GroupCardnamePromptRuleHandler,
    GroupCardnameUnreadFormatterHandler,
    GroupCardnameUnreadPrefetchHandler,
)


@register_plugin
class GroupCardnamePreferencePlugin(BasePlugin):
    """让 chatter 在群聊中优先用群名片称呼陌生成员。"""

    plugin_name = "group_cardname_preference"

    configs: list[type] = [GroupCardnamePreferenceConfig]
    dependencies: list[str] = []

    def get_components(self) -> list[type]:
        """返回插件提供的组件类。

        Returns:
            事件处理器类列表。
        """
        return [
            GroupCardnamePromptRuleHandler,
            GroupCardnameHistoryFormatterHandler,
            GroupCardnameUnreadFormatterHandler,
            GroupCardnameUnreadPrefetchHandler,
        ]

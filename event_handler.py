"""群聊昵称优先插件的事件处理器。

四个处理器分工：
- ``on_prompt_build``：仅当本轮上下文出现陌生标记时，修改 user prompt 的称呼规则；
- ``neo_default_chatter:build_history_text``：给历史消息中的陌生成员加标记；
- ``neo_default_chatter:format_unread_line``：给未读消息中的陌生成员加标记；
- ``neo_default_chatter:fetch_unreads``：在默认拉取完成后批量预取成员互动信息。
"""

from __future__ import annotations

from typing import Any

from src.app.plugin_system.base import BaseChatter, BaseEventHandler
from src.app.plugin_system.types import EventType
from src.kernel.event import EventDecision

from .config import GroupCardnamePreferenceConfig
from .familiarity import (
    collect_group_senders,
    is_bot_message,
    is_group_chat,
    is_stranger,
    mark_stranger_in_line,
    prefetch_strangers,
    replace_name_preference_rule,
)

_HISTORY_EVENT = "neo_default_chatter:build_history_text"
_UNREAD_LINE_EVENT = "neo_default_chatter:format_unread_line"
_FETCH_UNREADS_EVENT = "neo_default_chatter:fetch_unreads"


def _get_plugin_config(plugin: Any) -> GroupCardnamePreferenceConfig:
    """读取插件配置，缺失时返回默认配置。

    Args:
        plugin: 所属插件实例。

    Returns:
        插件配置实例。
    """
    config = getattr(plugin, "config", None)
    if isinstance(config, GroupCardnamePreferenceConfig):
        return config
    return GroupCardnamePreferenceConfig()


def _build_line(message: Any, time_format: str, marker: str, stranger: bool) -> str:
    """格式化单条消息并按需追加陌生标记。

    Args:
        message: 待格式化的消息。
        time_format: 时间格式。
        marker: 陌生标记。
        stranger: 是否陌生成员。

    Returns:
        格式化后的消息行。
    """
    line = BaseChatter.format_message_line(message, time_format)
    if not stranger:
        return line
    return mark_stranger_in_line(line, message, marker)


class GroupCardnamePromptRuleHandler(BaseEventHandler):
    """在 user prompt 中写入“陌生成员优先群名片”的称呼规则。"""

    name = "group_cardname_prompt_rule"
    description = "本轮上下文出现陌生标记时，调整 user prompt 的称呼偏好"
    weight = 100
    init_subscribe: list[EventType | str] = [EventType.ON_PROMPT_BUILD]

    async def execute(
        self, event_name: str, params: dict[str, Any]
    ) -> tuple[EventDecision, dict[str, Any]]:
        """替换 user prompt 模板中的称呼规则。"""
        config = _get_plugin_config(self.plugin)
        section = config.plugin
        if not section.enabled:
            return EventDecision.SUCCESS, params
        if params.get("name") != section.prompt_name:
            return EventDecision.SUCCESS, params

        values = params.get("values")
        if not isinstance(values, dict) or not is_group_chat(values.get("chat_type")):
            return EventDecision.SUCCESS, params

        marker = section.stranger_marker
        history = str(values.get("history") or "")
        unreads = str(values.get("unreads") or "")
        if marker not in history and marker not in unreads:
            return EventDecision.SUCCESS, params

        template = params.get("template")
        if not isinstance(template, str):
            return EventDecision.SUCCESS, params

        params["template"] = replace_name_preference_rule(template, marker)
        return EventDecision.SUCCESS, params


class GroupCardnameHistoryFormatterHandler(BaseEventHandler):
    """给历史消息中的陌生群成员追加标记。"""

    name = "group_cardname_history_formatter"
    description = "格式化历史消息时为陌生群成员追加群名片标记"
    weight = 200
    init_subscribe: list[EventType | str] = [_HISTORY_EVENT]

    async def execute(
        self, event_name: str, params: dict[str, Any]
    ) -> tuple[EventDecision, dict[str, Any]]:
        """替换默认的历史消息格式化结果。"""
        config = _get_plugin_config(self.plugin)
        section = config.plugin
        if not section.enabled:
            return EventDecision.PASS, params

        chat_stream = params.get("chat_stream")
        if chat_stream is None or not is_group_chat(getattr(chat_stream, "chat_type", "")):
            return EventDecision.PASS, params

        context = getattr(chat_stream, "context", None)
        messages = list(getattr(context, "history_messages", None) or [])
        if not messages:
            return EventDecision.PASS, params

        platform, user_ids = collect_group_senders(messages)
        if not platform:
            platform = str(getattr(chat_stream, "platform", "") or "")
        await prefetch_strangers(
            platform,
            user_ids,
            ttl_seconds=section.cache_ttl_seconds,
        )

        lines: list[str] = []
        for message in messages:
            stranger = False
            if not is_bot_message(message):
                user_id = str(getattr(message, "sender_id", "") or "")
                stranger = await is_stranger(
                    str(getattr(message, "platform", "") or platform),
                    user_id,
                    max_interactions=section.stranger_max_interactions,
                    grace_seconds=section.new_user_grace_seconds,
                    ttl_seconds=section.cache_ttl_seconds,
                )
            lines.append(
                _build_line(message, "%H:%M", section.stranger_marker, stranger)
            )

        params["lines"] = lines
        return EventDecision.STOP, params


class GroupCardnameUnreadFormatterHandler(BaseEventHandler):
    """给未读消息中的陌生群成员追加标记。"""

    name = "group_cardname_unread_formatter"
    description = "格式化未读消息时为陌生群成员追加群名片标记"
    weight = 200
    init_subscribe: list[EventType | str] = [_UNREAD_LINE_EVENT]

    async def execute(
        self, event_name: str, params: dict[str, Any]
    ) -> tuple[EventDecision, dict[str, Any]]:
        """陌生成员走自定义格式化，其余消息交回默认处理器。"""
        config = _get_plugin_config(self.plugin)
        section = config.plugin
        if not section.enabled:
            return EventDecision.PASS, params

        message = params.get("message")
        if message is None or is_bot_message(message):
            return EventDecision.PASS, params
        if not is_group_chat(getattr(message, "chat_type", "")):
            return EventDecision.PASS, params

        user_id = str(getattr(message, "sender_id", "") or "")
        if not user_id:
            return EventDecision.PASS, params

        stranger = await is_stranger(
            str(getattr(message, "platform", "") or ""),
            user_id,
            max_interactions=section.stranger_max_interactions,
            grace_seconds=section.new_user_grace_seconds,
            ttl_seconds=section.cache_ttl_seconds,
        )
        if not stranger:
            return EventDecision.PASS, params

        time_format = str(params.get("time_format") or "%H:%M")
        params["formatted_line"] = _build_line(
            message, time_format, section.stranger_marker, stranger=True
        )
        return EventDecision.STOP, params


class GroupCardnameUnreadPrefetchHandler(BaseEventHandler):
    """在默认 fetch_unreads 完成后批量预取未读消息发送者信息。"""

    name = "group_cardname_unread_prefetch"
    description = "批量预取未读群消息发送者的互动次数"
    weight = -100
    init_subscribe: list[EventType | str] = [_FETCH_UNREADS_EVENT]

    async def execute(
        self, event_name: str, params: dict[str, Any]
    ) -> tuple[EventDecision, dict[str, Any]]:
        """批量查询未读消息中的群成员，减少格式化阶段的数据库访问。"""
        config = _get_plugin_config(self.plugin)
        section = config.plugin
        if not section.enabled:
            return EventDecision.PASS, params

        messages = params.get("messages")
        if not isinstance(messages, list) or not messages:
            return EventDecision.PASS, params

        platform, user_ids = collect_group_senders(messages)
        if not platform or not user_ids:
            return EventDecision.PASS, params

        await prefetch_strangers(
            platform,
            user_ids,
            ttl_seconds=section.cache_ttl_seconds,
        )
        return EventDecision.SUCCESS, params

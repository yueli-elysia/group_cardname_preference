"""群成员熟悉度查询与消息行标注工具。

负责三件事：
1. 批量查询 ``person_info`` 并把互动次数缓存到进程内；
2. 按配置判断某个群成员是否仍属于“陌生用户”；
3. 在消息行和 user prompt 模板中写入陌生标记与称呼规则。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Iterable

from src.app.plugin_system.api import database_api, log_api
from src.core.models.sql_alchemy import PersonInfo

if TYPE_CHECKING:
    from src.core.models.message import Message

logger = log_api.get_logger("group_cardname_preference")

# 缓存结构：{(platform, user_id): (expires_at, interaction_count, first_interaction)}
_CACHE: dict[tuple[str, str], tuple[float, int | None, float | None]] = {}

_OLD_NAME_RULE = (
    "同一人更换群名片后，冒号前的用户昵称通常更稳定；"
    "称呼对方时，我优先参考用户昵称，除非对方希望使用群名片。"
)


def clear_cache() -> None:
    """清空成员熟悉度缓存，主要供测试和配置热更新场景使用。"""
    _CACHE.clear()


def is_group_chat(chat_type: Any) -> bool:
    """判断聊天类型是否为群聊。

    Args:
        chat_type: 字符串或带 ``value`` 的枚举。

    Returns:
        是否为群聊。
    """
    if hasattr(chat_type, "value"):
        chat_type = chat_type.value
    return str(chat_type or "").strip().lower() == "group"


def is_bot_message(message: "Message") -> bool:
    """判断消息是否由机器人自己发出。

    Args:
        message: 待判断的消息。

    Returns:
        消息角色为 bot 时返回 True。
    """
    return str(getattr(message, "sender_role", "") or "").strip().lower() == "bot"


def collect_group_senders(
    messages: Iterable["Message"],
) -> tuple[str, set[str]]:
    """收集一批消息中的群聊发送者。

    Args:
        messages: 消息列表。

    Returns:
        ``(platform, user_ids)``；没有可用群聊消息时 platform 为空字符串。
    """
    platform = ""
    user_ids: set[str] = set()
    for message in messages:
        if not is_group_chat(getattr(message, "chat_type", "")):
            continue
        if is_bot_message(message):
            continue
        user_id = str(getattr(message, "sender_id", "") or "").strip()
        if not user_id:
            continue
        if not platform:
            platform = str(getattr(message, "platform", "") or "").strip()
        user_ids.add(user_id)
    return platform, user_ids


def _is_stranger_from_values(
    interaction_count: int | None,
    first_interaction: float | None,
    *,
    max_interactions: int,
    grace_seconds: int,
    now: float,
) -> bool:
    """根据互动次数与首次互动时间判断是否陌生。

    Args:
        interaction_count: 历史互动次数。
        first_interaction: 首次互动时间戳。
        max_interactions: 视为陌生的最大互动次数。
        grace_seconds: 首次互动后的宽限秒数。
        now: 当前时间戳。

    Returns:
        是否仍属于陌生成员。
    """
    count = int(interaction_count or 0)
    if count <= max(0, int(max_interactions)):
        return True

    grace = max(0, int(grace_seconds))
    if grace > 0 and first_interaction is not None:
        if now - float(first_interaction) <= grace:
            return True

    return False


def _read_cache(
    platform: str,
    user_id: str,
    now: float,
) -> tuple[int | None, float | None] | None:
    """读取缓存中的成员互动信息。

    Args:
        platform: 平台标识。
        user_id: 平台用户 ID。
        now: 当前时间戳。

    Returns:
        命中且未过期时返回 ``(interaction_count, first_interaction)``，否则返回 None。
    """
    entry = _CACHE.get((platform, user_id))
    if entry is None:
        return None
    expires_at, interaction_count, first_interaction = entry
    if expires_at <= now:
        _CACHE.pop((platform, user_id), None)
        return None
    return interaction_count, first_interaction


async def _fetch_person_rows(
    platform: str,
    user_ids: set[str],
) -> dict[str, Any]:
    """从数据库批量读取成员记录。

    Args:
        platform: 平台标识。
        user_ids: 平台用户 ID 集合。

    Returns:
        以 user_id 为键的 ``PersonInfo`` 映射。
    """
    if not user_ids:
        return {}

    rows = await (
        database_api.query(PersonInfo)
        .filter(platform=platform, user_id__in=list(user_ids))
        .all()
    )
    return {
        str(getattr(row, "user_id", "") or ""): row
        for row in rows
        if getattr(row, "user_id", None)
    }


async def prefetch_strangers(
    platform: str,
    user_ids: Iterable[str],
    *,
    ttl_seconds: int,
) -> None:
    """批量预取成员互动信息并写入缓存。

    Args:
        platform: 平台标识。
        user_ids: 平台用户 ID 集合。
        ttl_seconds: 缓存有效秒数。
    """
    if not platform:
        return

    now = time.time()
    ids = {str(user_id).strip() for user_id in user_ids if str(user_id).strip()}
    missing = {user_id for user_id in ids if _read_cache(platform, user_id, now) is None}
    if not missing:
        return

    try:
        rows = await _fetch_person_rows(platform, missing)
    except Exception:
        logger.warning(
            f"查询群成员互动信息失败 platform={platform} users={len(missing)}",
            exc_info=True,
        )
        rows = {}

    expires_at = now + max(0, int(ttl_seconds))
    for user_id in missing:
        row = rows.get(user_id)
        if row is None:
            _CACHE[(platform, user_id)] = (expires_at, None, None)
            continue
        _CACHE[(platform, user_id)] = (
            expires_at,
            int(getattr(row, "interaction_count", 0) or 0),
            (
                float(getattr(row, "first_interaction"))
                if getattr(row, "first_interaction", None) is not None
                else None
            ),
        )

    if missing:
        logger.debug(
            f"预取群成员互动信息 platform={platform} "
            f"requested={len(missing)} found={len(rows)}"
        )


async def is_stranger(
    platform: str,
    user_id: str,
    *,
    max_interactions: int,
    grace_seconds: int,
    ttl_seconds: int,
) -> bool:
    """判断单个成员是否仍属于陌生用户。

    Args:
        platform: 平台标识。
        user_id: 平台用户 ID。
        max_interactions: 视为陌生的最大互动次数。
        grace_seconds: 首次互动宽限秒数。
        ttl_seconds: 缓存有效秒数。

    Returns:
        陌生返回 True，否则返回 False。
    """
    if not platform or not user_id:
        return False

    now = time.time()
    cached = _read_cache(platform, user_id, now)
    if cached is None:
        await prefetch_strangers(
            platform,
            {user_id},
            ttl_seconds=ttl_seconds,
        )
        cached = _read_cache(platform, user_id, time.time())
        if cached is None:
            # 查询失败时保守地按陌生处理，仍然优先使用群名片
            return True

    interaction_count, first_interaction = cached
    return _is_stranger_from_values(
        interaction_count,
        first_interaction,
        max_interactions=max_interactions,
        grace_seconds=grace_seconds,
        now=now,
    )


def mark_stranger_in_line(
    line: str,
    message: "Message",
    marker: str,
) -> str:
    """在消息行的名字字段后追加陌生标记。

    标记与群名片之间用空格分隔，避免模型把它误认为名字的一部分。
    仅当消息同时拥有 QQ 昵称、群名片且两者不同时追加标记；
    没有群名片时无法体现“优先群名片”，保持原行不变。

    Args:
        line: 已经格式化好的消息行。
        message: 对应的消息。
        marker: 陌生标记文本。

    Returns:
        追加标记后的消息行。
    """
    if is_bot_message(message):
        return line

    nickname = str(getattr(message, "sender_name", "") or "")
    cardname = str(getattr(message, "sender_cardname", "") or "")
    if not cardname or cardname == nickname:
        return line

    target = f"$群名片:{cardname}"
    index = line.find(target)
    if index < 0:
        return line
    end = index + len(target)
    return f"{line[:end]} {marker}{line[end:]}"


def replace_name_preference_rule(template: str, marker: str) -> str:
    """把 user prompt 中的称呼偏好改为“陌生成员优先群名片”。

    Args:
        template: 原始的 user prompt 模板。
        marker: 陌生标记文本。

    Returns:
        修改后的模板；模板结构变化时在末尾追加补充规则。
    """
    new_rule = (
        "同一人更换群名片后，冒号前的用户昵称通常更稳定。"
        f"称呼对方时：消息行里出现{marker}标记的成员是你还不熟悉的人，"
        "优先使用他的群名片称呼；其他熟悉的成员，仍优先参考用户昵称，"
        "除非对方希望使用群名片。"
    )

    if _OLD_NAME_RULE in template:
        return template.replace(_OLD_NAME_RULE, new_rule, 1)

    if f"出现{marker}标记" in template:
        return template

    return (
        f"{template}\n\n"
        f"称呼规则：群聊消息行中出现{marker}标记的成员，"
        "优先使用他的群名片称呼；熟悉的成员仍优先参考用户昵称。"
    )

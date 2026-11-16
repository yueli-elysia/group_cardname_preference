"""群聊昵称优先插件配置。

配置文件默认路径：config/plugins/group_cardname_preference/config.toml
"""

from __future__ import annotations

from typing import ClassVar

from src.app.plugin_system.base import BaseConfig, Field, SectionBase, config_section


class GroupCardnamePreferenceConfig(BaseConfig):
    """群聊昵称优先插件配置。"""

    name: ClassVar[str] = "config"
    description: ClassVar[str] = "群聊中让陌生成员优先使用群名片称呼"

    @config_section("plugin")
    class PluginSection(SectionBase):
        """插件行为配置。"""

        enabled: bool = Field(
            default=True,
            description="是否启用插件",
        )

        stranger_max_interactions: int = Field(
            default=1,
            description=(
                "互动次数不超过该值时视为陌生成员。"
                "person_info.interaction_count 会按收到的消息累加，"
                "新成员连发多条时建议配合 new_user_grace_seconds 使用。"
            ),
        )

        new_user_grace_seconds: int = Field(
            default=1800,
            description=(
                "首次互动时间距今不超过该秒数时仍视为陌生成员，"
                "用于避免新成员连发多条消息后立刻被当成熟人。0 表示关闭该补充判断。"
            ),
        )

        stranger_marker: str = Field(
            default="[陌生]",
            description="追加在消息名字段后的陌生标记，同时用于提示词规则说明",
        )

        prompt_name: str = Field(
            default="neo_default_chatter_user_prompt",
            description="需要修改称呼规则的 user prompt 模板名",
        )

        cache_ttl_seconds: int = Field(
            default=30,
            description="成员互动次数缓存的有效秒数，避免同一轮内反复查询数据库",
        )

    plugin: PluginSection = Field(default_factory=PluginSection)

"""HAWGCS UI 添加集成流程"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_TOKEN,
    DOMAIN,
)

# ── 步骤说明（传给前端直接显示，不依赖自动翻译查找）───────────────────────────
_DESC = (
    "Gitee 仓库地址已使用默认值，无需修改。\n\n"
    "如遇 403 报错（请求频率超限），请填入 Gitee Personal Access Token 获取更高调用额度。"
    "Token 为可选参数，留空也能用；也可后续在「设置」中补充添加。"
)
_DESC_TOKEN = (
    "访问 Gitee 仓库时，如遇 403 报错（请求频率超限），请在此填入 Token 即可继续使用。"
    "留空则使用匿名访问，频率受限。"
)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """配置 → 设备与服务 → HAWGCS → 配置"""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_TOKEN,
                        default=self.config_entry.data.get(CONF_TOKEN, ""),
                        description={"suggested_value": self.config_entry.data.get(CONF_TOKEN, "")},
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                }
            ),
            description_placeholders={"description": _DESC_TOKEN},
        )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """点"添加集成" → 弹出表单填仓库信息。"""

    VERSION = 1

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return OptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Optional(
                            CONF_TOKEN,
                            default="",
                            description={"suggested_value": ""},
                        ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                    }
                ),
                description_placeholders={"description": _DESC},
            )

        return self.async_create_entry(
            title="HAWGCS 插件商店",
            data={
                "repo": "hawgcs/hawgcs",
                "branch": "master",
                "index_path": "plugins/repositories.json",
                CONF_TOKEN: user_input.get(CONF_TOKEN, ""),
            },
        )

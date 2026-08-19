"""HAWGCS UI 添加集成流程"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_BRANCH,
    CONF_INDEX_PATH,
    CONF_REPO,
    CONF_TOKEN,
    DEFAULT_BRANCH,
    DEFAULT_INDEX_PATH,
    DEFAULT_REPO,
    DOMAIN,
)

USER_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_REPO, default=DEFAULT_REPO): str,
        vol.Optional(CONF_BRANCH, default=DEFAULT_BRANCH): str,
        vol.Optional(CONF_INDEX_PATH, default=DEFAULT_INDEX_PATH): str,
        vol.Optional(CONF_TOKEN, default=""): str,
    },
)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """配置 → 设备与服务 → HAWGCS → 配置"""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """初始化选项流。"""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """管理选项。"""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_TOKEN,
                        default=self.config_entry.data.get(CONF_TOKEN, ""),
                    ): str,
                }
            ),
            description_placeholders={
                "token_hint": "修改 Gitee Personal Access Token（留空表示不使用）",
            },
        )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """点"添加集成" → 弹出表单填仓库信息。"""

    VERSION = 1

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """返回选项流处理器。"""
        return OptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(
            step_id="user",
            data_schema=USER_SCHEMA,
            description_placeholders={
                "token_hint": "Gitee Personal Access Token（可选，不填也能用，高频使用可能触发 403 限制）",
            },
        )

        repo = user_input.get(CONF_REPO, DEFAULT_REPO)
        branch = user_input.get(CONF_BRANCH, DEFAULT_BRANCH)

        await self.async_set_unique_id(f"{repo}@{branch}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title="HAWGCS 插件商店",
            data={
                CONF_REPO: repo,
                CONF_BRANCH: branch,
                CONF_INDEX_PATH: user_input.get(CONF_INDEX_PATH, DEFAULT_INDEX_PATH),
                CONF_TOKEN: user_input.get(CONF_TOKEN, ""),
            },
        )

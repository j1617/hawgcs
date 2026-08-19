"""Integration（后端集成）Store"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..const import TYPE_INTEGRATION
from .base import StoreBase

_LOGGER = logging.getLogger(__name__)


class IntegrationStore(StoreBase):
    type = TYPE_INTEGRATION

    async def install(self, item: dict[str, Any]) -> dict[str, Any]:
        slug = item["slug"]
        path = item["path"]  # 远程仓库下的相对路径，如 "integrations/helloworld"

        _LOGGER.info("安装 integration [%s] from %s", slug, path)
        downloaded = await self.download_tree(path, slug)

        # 装完触发 HA 重新加载该集成
        await self._reload_integration(slug)

        return {
            "msg": f"✅ Integration [{slug}] 安装完成（{len(downloaded)} 个文件）。"
                    f"请前往「配置 → 设备与服务 → 添加集成」搜索并添加「{item.get('name', slug)}」。"
                    f"如果找不到，请重启 Home Assistant。",
            "files": downloaded,
            "slug": slug,
        }

    async def uninstall(self, slug: str) -> dict[str, Any]:
        target = self.target_dir(slug)
        if not os.path.isdir(target):
            raise HomeAssistantError(f"[{slug}] 未安装")

        # 先尝试 unload（关闭 config entry）
        await self._unload_integration(slug)
        await self._rmtree(target)

        return {"msg": f"✅ [{slug}] 已卸载，请重启 HA 使变更完全生效。"}

    async def reload(self, item: dict[str, Any]) -> dict[str, Any]:
        slug = item["slug"]
        await self._reload_integration(slug)
        return {"msg": f"✅ [{slug}] 已重载。"}

    # ---- 已安装状态 ----

    def is_installed(self, slug: str) -> bool:
        return os.path.isdir(self.target_dir(slug))

    def get_installed(self) -> list[dict[str, Any]]:
        root = self.target_root
        if not os.path.isdir(root):
            return []
        result = []
        for name in os.listdir(root):
            sub = os.path.join(root, name)
            if not os.path.isdir(sub):
                continue
            manifest = os.path.join(sub, "manifest.json")
            version = None
            domain = name
            if os.path.isfile(manifest):
                try:
                    with open(manifest, encoding="utf-8") as f:
                        data = json.load(f)
                    version = data.get("version")
                    domain = data.get("domain", domain)
                except Exception:  # noqa: BLE001
                    pass
            result.append({"slug": name, "version": version, "domain": domain})
        return result

    async def async_get_installed(self) -> list[dict[str, Any]]:
        """async 包装，供 HA 事件循环调用。"""
        return await self.hass.async_add_executor_job(self.get_installed)

    # ---- HA config entry reload ----

    async def _reload_integration(self, slug: str) -> None:
        """触发 HA 重新加载指定的 integration。

        新安装的集成没有 config entry，需要：
        1. 先尝试调用 homeassistant.reload_all 服务（2024.x 支持）
        2. 或者重启 HA 才能完全生效
        """
        # 尝试调用 reload_all 服务来加载新集成
        try:
            await self.hass.services.async_call(
                "homeassistant", "reload_all", blocking=False
            )
            _LOGGER.info("已触发 reload_all 服务加载新集成: %s", slug)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("reload_all 服务调用失败: %s", err)

        # 如果有已存在的 config entry，尝试重载
        entries = [
            e for e in self.hass.config_entries.async_entries(slug)
        ]
        if entries:
            for entry in entries:
                try:
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    _LOGGER.info("重载 config entry: %s", entry.entry_id)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("重载 entry %s 失败: %s", entry.entry_id, err)

    async def _unload_integration(self, slug: str) -> None:
        """卸载前先 unload config entry（如果存在）。"""
        entries = [
            e for e in self.hass.config_entries.async_entries(slug)
        ]
        for entry in entries:
            try:
                await self.hass.config_entries.async_unload_entry(entry.entry_id)
                _LOGGER.info("卸载 config entry: %s", entry.entry_id)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("卸载 entry %s 失败: %s", entry.entry_id, err)

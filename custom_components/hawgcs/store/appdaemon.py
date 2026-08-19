"""AppDaemon Store"""
from __future__ import annotations

import logging
import os
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..const import TYPE_APPDAEMON
from .base import StoreBase

_LOGGER = logging.getLogger(__name__)


class AppDaemonStore(StoreBase):
    type = TYPE_APPDAEMON

    async def install(self, item: dict[str, Any]) -> dict[str, Any]:
        slug = item["slug"]
        path = item["path"]  # 如 "appdaemon/apps/my-app"

        _LOGGER.info("安装 appdaemon [%s] from %s", slug, path)
        downloaded = await self.download_tree(path, slug)

        # 通知 hassio 重启 appdaemon
        await self._restart_appdaemon()

        return {
            "msg": f"✅ AppDaemon app [{slug}] 安装完成（{len(downloaded)} 个文件），已重启 AppDaemon。",
            "files": downloaded,
            "slug": slug,
        }

    async def uninstall(self, slug: str) -> dict[str, Any]:
        target = self.target_dir(slug)
        if not os.path.isdir(target):
            raise HomeAssistantError(f"[{slug}] 未安装")
        await self._rmtree(target)
        await self._restart_appdaemon()
        return {"msg": f"✅ [{slug}] 已卸载，AppDaemon 已重启。"}

    async def reload(self, item: dict[str, Any]) -> dict[str, Any]:
        await self._restart_appdaemon()
        return {"msg": f"✅ AppDaemon 已重启。"}

    def is_installed(self, slug: str) -> bool:
        return os.path.isdir(self.target_dir(slug))

    def get_installed(self) -> list[dict[str, Any]]:
        root = self.target_root
        if not os.path.isdir(root):
            return []
        return [
            {"slug": name, "version": None}
            for name in os.listdir(root)
            if os.path.isdir(os.path.join(root, name))
        ]

    # ---- hassio AppDaemon 重启 ----

    async def _restart_appdaemon(self) -> None:
        """通过 hassio service 重启 AppDaemon addon。"""
        try:
            await self.hass.services.async_call(
                "hassio", "addon_restart",
                {"addon": "local_appdaemon"},
                blocking=True,
            )
            _LOGGER.info("AppDaemon 重启已触发")
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("无法通过 hassio 重启 AppDaemon（Addon 名可能不是 local_appdaemon）: %s", err)

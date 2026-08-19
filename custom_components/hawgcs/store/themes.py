"""Theme Store"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..const import TYPE_THEME
from .base import StoreBase

_LOGGER = logging.getLogger(__name__)


class ThemeStore(StoreBase):
    type = TYPE_THEME

    async def install(self, item: dict[str, Any]) -> dict[str, Any]:
        slug = item["slug"]
        path = item["path"]  # 如 "themes/dark-mode.yaml" 或 "themes/dark-mode/..."

        _LOGGER.info("安装 theme [%s] from %s", slug, path)
        downloaded = await self._install_theme(slug, path)

        # 通知 frontend 主题更新
        await self._notify_theme_change()

        return {
            "msg": f"✅ Theme [{slug}] 安装完成。"
                    f"请前往「配置 → 主题」选择使用。如果主题未显示，请刷新浏览器页面。",
            "files": downloaded,
            "slug": slug,
        }

    async def uninstall(self, slug: str) -> dict[str, Any]:
        target = self.target_dir(slug)
        if not os.path.isdir(target):
            raise HomeAssistantError(f"[{slug}] 未安装")
        await self._rmtree(target)
        await self._notify_theme_change()
        return {"msg": f"✅ [{slug}] 已卸载。"}

    async def reload(self, item: dict[str, Any]) -> dict[str, Any]:
        await self._notify_theme_change()
        return {"msg": f"✅ [{item['slug']}] 已刷新。"}

    def is_installed(self, slug: str) -> bool:
        # 检查目录形式或单文件形式
        return os.path.isdir(self.target_dir(slug)) or os.path.isfile(
            os.path.join(self.target_root, f"{slug}.yaml")
        ) or os.path.isfile(os.path.join(self.target_root, f"{slug}.yml"))

    def get_installed(self) -> list[dict[str, Any]]:
        root = self.target_root
        if not os.path.isdir(root):
            return []
        result = []
        for name in os.listdir(root):
            sub = os.path.join(root, name)
            if os.path.isdir(sub):
                # 目录形式的主题
                yaml_files = [f for f in os.listdir(sub) if f.endswith((".yaml", ".yml"))]
                result.append({
                    "slug": name,
                    "version": None,
                    "main_file": yaml_files[0] if yaml_files else None,
                })
            elif name.endswith((".yaml", ".yml")):
                # 单文件主题（如 dark-mode.yaml）
                slug = name.replace(".yaml", "").replace(".yml", "")
                result.append({
                    "slug": slug,
                    "version": None,
                    "main_file": name,
                })
        return result

    async def async_get_installed(self) -> list[dict[str, Any]]:
        """async 包装，供 HA 事件循环调用。"""
        return await self.hass.async_add_executor_job(self.get_installed)

    # ---- 安装主题：可能是单文件也可能是目录 ----

    async def _install_theme(self, slug: str, remote_path: str) -> list[str]:
        # 先试试是不是单文件
        try:
            content = await self._download_bytes(self.raw_url(remote_path))
            # 是文件，直接写
            target = os.path.join(self.target_root, f"{slug}.yaml")
            await self._write_atomic(target, content)
            return [f"{slug}.yaml"]
        except HomeAssistantError:
            pass

        # 是目录，拉整个目录
        return await self.download_tree(remote_path, slug)

    # ---- 通知 frontend ----

    async def _notify_theme_change(self) -> None:
        """通知 HA 前端主题已更新。"""
        try:
            # 触发主题更新事件
            self.hass.bus.async_fire("themes_updated")
            
            # 调用 frontend 重载主题服务（2024.x 正确方式）
            try:
                await self.hass.services.async_call(
                    "frontend", "reload_themes", blocking=False
                )
            except Exception:
                pass
                
            _LOGGER.info("已触发主题更新")
        except Exception:  # noqa: BLE001
            pass

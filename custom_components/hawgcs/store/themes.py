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
        path = item["path"]  # 如 "themes/meow-day.yaml"
        version = item.get("version", "unknown")

        _LOGGER.info("安装 theme [%s] v%s from %s", slug, version, path)
        downloaded = await self._install_theme(slug, path, version)

        # 通知 frontend 主题更新
        await self._notify_theme_change()

        return {
            "msg": f"✅ Theme [{slug}] 安装完成。"
                    f"请前往「设置 → 主题」选择使用。如果主题未显示，请刷新浏览器页面。",
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
        # 只认目录形式（含 .hacs.json）
        return os.path.isdir(self.target_dir(slug))

    def _read_meta(self, slug: str) -> dict[str, Any] | None:
        """读取主题的 .hacs.json 元数据，兼容旧单文件形式。"""
        # 新目录形式
        meta_file = os.path.join(self.target_dir(slug), ".hacs.json")
        if os.path.isfile(meta_file):
            try:
                with open(meta_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:  # noqa: BLE001
                pass
        # 旧单文件形式（version 字段写死在 yaml 里不现实，直接返回 None 驱动迁移）
        return None

    def get_installed(self) -> list[dict[str, Any]]:
        root = self.target_root
        if not os.path.isdir(root):
            return []
        result = []
        for name in os.listdir(root):
            sub = os.path.join(root, name)
            if not os.path.isdir(sub):
                continue
            meta = self._read_meta(name)
            yaml_files = [
                f for f in os.listdir(sub)
                if f.endswith((".yaml", ".yml")) and not f.startswith(".")
            ]
            result.append({
                "slug": name,
                "version": meta.get("version") if meta else None,
                "main_file": yaml_files[0] if yaml_files else None,
            })
        return result

    async def async_get_installed(self) -> list[dict[str, Any]]:
        """async 包装，供 HA 事件循环调用。"""
        return await self.hass.async_add_executor_job(self.get_installed)

    # ---- 安装主题：统一写入 themes/{slug}/ 目录 + .hacs.json ----

    async def _install_theme(self, slug: str, remote_path: str, version: str) -> list[str]:
        # 统一写到目录里（哪怕是单文件主题）
        target_dir = os.path.join(self.target_root, slug)
        yaml_name = f"{slug}.yaml"
        target_file = os.path.join(target_dir, yaml_name)
        meta_file = os.path.join(target_dir, ".hacs.json")

        # 下载主题文件内容
        content = await self._download_bytes(self.raw_url(remote_path))
        await self._write_atomic(target_file, content)

        # 写元数据文件（version 来源：repositories.json）
        meta = {"version": version, "slug": slug}
        await self._write_atomic(meta_file, json.dumps(meta, ensure_ascii=False).encode())

        return [f"{slug}/{yaml_name}", f"{slug}/.hacs.json"]

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

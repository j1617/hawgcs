"""Lovelace 卡片 Store"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..const import TYPE_LOVELACE
from .base import StoreBase

_LOGGER = logging.getLogger(__name__)


# 模块级别辅助函数，供 _register_resource 和 _unregister_resource 共用
def _read_file_sync(path):
    with open(path, encoding="utf-8") as f:
        return f.read()

def _write_resources_sync(path, res_data):
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(res_data, indent=2))


class LovelaceStore(StoreBase):
    type = TYPE_LOVELACE

    async def install(self, item: dict[str, Any]) -> dict[str, Any]:
        slug = item["slug"]
        path = item["path"]          # 远程路径，如 "lovelace/battery-card"
        filename = item["filename"]  # 要注册的 js 文件，如 "battery-card.js"

        _LOGGER.info("安装 lovelace [%s] file=%s", slug, filename)

        # 确保 www/community 目录存在
        await self._ensure_www_community()

        # 使用递归下载，支持子目录（如 battery-card/dist/battery-card.js）
        downloaded = await self.download_tree_recursive(path, slug)

        # 验证文件是否真的下载了
        target = self.target_dir(slug)
        js_file = os.path.join(target, filename)
        if not os.path.isfile(js_file):
            _LOGGER.error("JS 文件未找到: %s", js_file)
            raise HomeAssistantError(f"安装失败：JS 文件 {filename} 未下载成功")
        
        _LOGGER.info("JS 文件已下载: %s (%s bytes)", js_file, os.path.getsize(js_file))

        # 注册到 lovelace resources
        resource_url = f"/local/community/{slug}/{filename}"
        await self._register_resource(slug, resource_url, "module")

        # 检查资源是否真的注册成功
        store_path = self.hass.config.path(".storage/lovelace_resources")
        resource_registered = False
        if os.path.isfile(store_path):
            try:
                import functools
                raw = await self.hass.async_add_executor_job(
                    functools.partial(_read_file_sync, store_path)
                )
                check_data = json.loads(raw)
                resource_registered = any(
                    item.get("url") == resource_url 
                    for item in check_data.get("items", [])
                )
            except Exception:  # noqa: BLE001
                pass
        
        if resource_registered:
            msg = f"✅ Lovelace 卡片 [{slug}] 安装完成，资源已注册。"
            msg += "请刷新浏览器页面（F5）或清除缓存后，在仪表板编辑时添加卡片。"
        else:
            msg = f"⚠️ Lovelace 卡片 [{slug}] 文件已下载，但资源注册可能失败。"
            msg += f"请手动前往「配置 → Lovelace → 资源」添加资源：{resource_url}"
            msg += "或者重启 Home Assistant。"

        return {
            "msg": msg,
            "files": downloaded,
            "slug": slug,
            "resource_url": resource_url,
            "resource_registered": resource_registered,
        }

    async def _ensure_www_community(self) -> None:
        """确保 www/community 目录存在。"""
        import functools
        www_root = self.hass.config.path("www")
        community_dir = self.target_root
        
        # 创建 www 目录（如果不存在）
        if not os.path.isdir(www_root):
            await self.hass.async_add_executor_job(
                functools.partial(os.makedirs, www_root, exist_ok=True)
            )
            _LOGGER.info("创建 www 目录: %s", www_root)
        
        # 创建 community 目录（如果不存在）
        if not os.path.isdir(community_dir):
            await self.hass.async_add_executor_job(
                functools.partial(os.makedirs, community_dir, exist_ok=True)
            )
            _LOGGER.info("创建 community 目录: %s", community_dir)

    async def uninstall(self, slug: str) -> dict[str, Any]:
        target = self.target_dir(slug)
        if not os.path.isdir(target):
            raise HomeAssistantError(f"[{slug}] 未安装")

        # 从 lovelace resources 注销
        await self._unregister_resource(slug)
        await self._rmtree(target)
        
        # 触发前端刷新
        await self._fire_frontend_reload()

        return {"msg": f"✅ [{slug}] 已卸载，请刷新浏览器页面。"}

    async def reload(self, item: dict[str, Any]) -> dict[str, Any]:
        """重新加载资源。"""
        slug = item["slug"]
        filename = item.get("filename", f"{slug}.js")
        resource_url = f"/local/community/{slug}/{filename}"
        
        # 尝试重新注册资源
        try:
            await self._register_resource(slug, resource_url, "module")
            return {"msg": f"✅ [{slug}] 资源已重新加载，请刷新浏览器页面。"}
        except Exception as err:  # noqa: BLE001
            return {"msg": f"⚠️ [{slug}] 重新加载失败: {err}"}

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
            # 读 hacs.json 获取版本号（HACS 标准）
            version = None
            hacs_json = os.path.join(sub, "hacs.json")
            if os.path.isfile(hacs_json):
                try:
                    with open(hacs_json, encoding="utf-8") as f:
                        data = json.load(f)
                    version = data.get("version")
                except Exception:  # noqa: BLE001
                    pass
            # 找主 js 文件
            js_files = [f for f in os.listdir(sub) if f.endswith(".js")]
            result.append({
                "slug": name,
                "version": version,
                "main_file": js_files[0] if js_files else None,
            })
        return result
    async def async_get_installed(self) -> list[dict[str, Any]]:
        """async 包装，供 HA 事件循环调用。"""
        return await self.hass.async_add_executor_job(self.get_installed)

    # ---- lovelace resource 注册 ----

    def _get_resource_handler(self):
        """获取 Lovelace 资源处理器（参考 HACS 实现）。"""
        try:
            from homeassistant.components.lovelace.resources import ResourceStorageCollection
            
            hass_data = self.hass.data
            if not hass_data:
                _LOGGER.error("无法访问 hass data")
                return None

            lovelace_data = hass_data.get("lovelace")
            if lovelace_data is None:
                _LOGGER.warning("无法访问 lovelace 集成数据")
                return None

            # 兼容不同 HA 版本
            if hasattr(lovelace_data, 'resources'):
                resources = lovelace_data.resources
            else:
                resources = lovelace_data.get("resources")

            if resources is None:
                _LOGGER.warning("无法访问 dashboard resources")
                return None

            if not hasattr(resources, 'store') or resources.store is None:
                _LOGGER.info("YAML 模式检测到，无法自动更新 resources")
                return None

            if resources.store.key != "lovelace_resources" or resources.store.version != 1:
                _LOGGER.warning("无法使用 dashboard resources: key=%s, version=%s", 
                               getattr(resources.store, 'key', None),
                               getattr(resources.store, 'version', None))
                return None

            return resources
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("获取 resource handler 失败: %s", err)
            return None

    async def _register_resource(self, slug: str, url: str, res_type: str) -> None:
        """注册 Lovelace 资源到 HA（参考 HACS 实现）。"""
        # 方法1: 使用 HACS 方式通过 lovelace 实例注册
        resources = self._get_resource_handler()
        if resources:
            try:
                if not resources.loaded:
                    await resources.async_load()

                # 检查是否已存在
                for entry in resources.async_items():
                    if entry.get("url") == url:
                        _LOGGER.info("资源已存在，跳过: %s", url)
                        return

                # 创建新资源（注意：HACS 使用 res_type 而不是 type）
                await resources.async_create_item({"res_type": res_type, "url": url})
                _LOGGER.info("已通过 lovelace 实例注册资源: %s", url)
                return
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("通过 lovelace 实例注册失败: %s", err)

        # 方法2: 直接写入 .storage/lovelace_resources（兼容模式）
        await self._register_resource_fallback(slug, url, res_type)

    async def _register_resource_fallback(self, slug: str, url: str, res_type: str) -> None:
        """回退方法：直接写入 .storage/lovelace_resources。"""
        store_path = self.hass.config.path(".storage/lovelace_resources")
        data = {"items": [], "version": 1}

        if os.path.isfile(store_path):
            try:
                import functools
                raw = await self.hass.async_add_executor_job(
                    functools.partial(_read_file_sync, store_path)
                )
                data = json.loads(raw)
            except Exception:  # noqa: BLE001
                pass

        items: list = data.setdefault("items", [])

        # 已经注册过就跳过
        if any(item.get("url") == url for item in items):
            _LOGGER.info("资源已注册，跳过: %s", url)
            return

        # 生成新的 ID
        new_id = max([int(it.get("id", 0)) for it in items if str(it.get("id", "")).isdigit()], default=0) + 1
        
        # HA 2024.x 格式
        new_item = {
            "id": str(new_id),
            "url": url,
            "type": res_type,
        }
        items.append(new_item)
        data["version"] = 1
        
        _LOGGER.info("准备写入 lovelace_resources: %s", new_item)

        import functools
        await self.hass.async_add_executor_job(
            functools.partial(_write_resources_sync, store_path, data)
        )

        _LOGGER.info("已写入 lovelace_resources: %s", url)

    async def _unregister_resource(self, slug: str) -> None:
        """从 lovelace_resources 删除该 slug 的资源。"""
        prefix = f"/local/community/{slug}/"
        
        # 方法1: 使用 HACS 方式通过 lovelace 实例删除
        resources = self._get_resource_handler()
        if resources:
            try:
                if not resources.loaded:
                    await resources.async_load()

                for entry in resources.async_items():
                    if entry.get("url", "").startswith(prefix):
                        await resources.async_delete_item(entry["id"])
                        _LOGGER.info("已通过 lovelace 实例注销资源: %s", entry.get("url"))
                        return
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("通过 lovelace 实例注销失败: %s", err)

        # 方法2: 直接修改存储文件（兼容模式）
        store_path = self.hass.config.path(".storage/lovelace_resources")
        if not os.path.isfile(store_path):
            return

        try:
            import functools
            raw = await self.hass.async_add_executor_job(
                functools.partial(_read_file_sync, store_path)
            )
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            return

        items: list = data.setdefault("items", [])
        kept = [it for it in items if not it.get("url", "").startswith(prefix)]
        data["items"] = kept

        await self.hass.async_add_executor_job(
            functools.partial(_write_resources_sync, store_path, data)
        )
        _LOGGER.info("已从文件注销 lovelace 资源: %s*", prefix)

    async def _fire_frontend_reload(self) -> None:
        """通知 frontend 重新加载 lovelace 资源。
        
        HACS 方式：通过 lovelace 实例调用 async_load 重新加载资源
        """
        try:
            resources = self._get_resource_handler()
            if resources and hasattr(resources, 'async_load'):
                await resources.async_load()
                _LOGGER.info("已通过 lovelace 实例重新加载资源")
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("触发前端重载失败: %s", err)

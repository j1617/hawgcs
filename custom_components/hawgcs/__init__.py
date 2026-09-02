"""HAWGCS - HomeAssistant W Git Component Store
支持 integration / lovelace / theme / appdaemon 四类资源的安装卸载。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Any

from aiohttp import web
from homeassistant.components import frontend
from homeassistant.components.frontend import async_register_built_in_panel
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import aiohttp
from homeassistant.helpers import aiohttp_client

from .api import register_api
from .const import (
    ALL_TYPES,
    CONF_BRANCH,
    CONF_INDEX_PATH,
    CONF_REPO,
    CONF_TOKEN,
    DEFAULT_BRANCH,
    DEFAULT_INDEX_PATH,
    DEFAULT_REPO,
    DOMAIN,
    TARGET_DIR_NAME,
    VERSION,
)
from .store import STORE_MAP, StoreBase

_LOGGER = logging.getLogger(__name__)


class HAWGCSPanelView(HomeAssistantView):
    """自定义视图提供 panel.html，强制 Content-Type 带 charset=utf-8，解决中文乱码。
    面板 UI 本身不需要认证（只展示静态界面），所有操作走 /api/hawgcs/* 需认证。
    """

    url = "/api/hawgcs/panel"
    name = "api:hawgcs:panel"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass = request.app.get("hass")
        if hass is None:
            _LOGGER.error("request.app['hass'] 不存在")
            return web.Response(status=500, text="hass not found in request", charset="utf-8")
        
        panel_path = os.path.join(os.path.dirname(__file__), "panel.html")
        _LOGGER.info("尝试读取 panel.html: %s", panel_path)
        
        try:
            content = await hass.async_add_executor_job(
                self._read_panel, panel_path
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("读取 panel.html 失败: %s | path=%s", err, panel_path, exc_info=True)
            return web.Response(
                status=500,
                text=f"读取面板文件失败: {err} | path={panel_path}",
                charset="utf-8",
            )
        
        _LOGGER.info("panel.html 读取成功，大小: %d bytes", len(content))
        return web.Response(
            body=content.encode("utf-8"),
            content_type="text/html",
        )

    @staticmethod
    def _read_panel(path: str) -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()


# ────────────────────────────────────────────
#  Lifecycle
# ────────────────────────────────────────────

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, None)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    store = HawgcsManager(hass, entry.data)

    # 拉一次索引（允许失败，启动后 UI 可手动刷新）
    try:
        await store.refresh_plugin_list()
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("首次拉取索引失败: %s", err)

    hass.data[DOMAIN] = store

    # 先注销旧面板
    frontend.async_remove_panel(hass, DOMAIN)

    # 注册自定义视图，确保返回正确的 Content-Type 头
    hass.http.register_view(HAWGCSPanelView())

    # 使用 iframe 类型注册面板，指向自定义视图
    async_register_built_in_panel(
        hass,
        component_name="iframe",
        sidebar_title="HAWGCS 插件商店",
        sidebar_icon="mdi:storefront-outline",
        frontend_url_path=DOMAIN,
        require_admin=False,
        config={"url": "/api/hawgcs/panel"},
    )

    register_api(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.pop(DOMAIN, None)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


# ────────────────────────────────────────────
#  HawgcsManager — 统一调度层
# ────────────────────────────────────────────

class HawgcsManager:
    """持有 entry 配置，按类型分发安装/卸载请求，并维护本地已安装状态。"""

    def __init__(self, hass: HomeAssistant, entry_data: dict) -> None:
        self.hass = hass
        self.repo = entry_data.get(CONF_REPO) or DEFAULT_REPO
        self.branch = entry_data.get(CONF_BRANCH) or DEFAULT_BRANCH
        self.index_path = entry_data.get(CONF_INDEX_PATH) or DEFAULT_INDEX_PATH
        self.token = entry_data.get(CONF_TOKEN, "")
        self.plugin_list: list[dict] = []
        self._index_loaded = False

        # 每种类型一个 Store 实例（复用，节省 session）
        self._stores: dict[str, StoreBase] = {}
        for rtype, cls in STORE_MAP.items():
            self._stores[rtype] = cls(hass, self.repo, self.branch, self.token)

    # ── 索引 ──

    @property
    def index_url(self) -> str:
        # Gitee raw 地址（会 302 跳转，aiohttp 自动跟随）
        return f"https://gitee.com/{self.repo}/raw/{self.branch}/{self.index_path}"

    def _get_self_version(self) -> str | None:
        """读取自身的版本号。"""
        try:
            manifest_path = os.path.join(os.path.dirname(__file__), "manifest.json")
            with open(manifest_path, "r", encoding="utf-8") as f:
                import json
                data = json.load(f)
                return data.get("version")
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("读取自身版本失败: %s", err)
            return None

    def _add_self_to_list(self, data: list) -> None:
        """将 HAWGCS 自身添加到插件列表。"""
        # 检查是否已在列表中
        for item in data:
            if item.get("slug") == "hawgcs" and item.get("type") == "integration":
                # 已存在，更新本地版本
                item["_is_self"] = True
                return
        
        # 不存在，添加自身
        local_version = self._get_self_version()
        self_item = {
            "slug": "hawgcs",
            "type": "integration",
            "name": "HAWGCS Git 插件商店",
            "description": "Home Assistant Git 插件商店，支持从 Gitee 仓库安装集成、Lovelace 卡片、主题",
            "domain": "hawgcs",
            "version": local_version or "1.2.0",
            "author": "hawgcs",
            "homeassistant_min": "2024.1.0",
            "url": f"https://gitee.com/{self.repo}",
            "path": "integrations/hawgcs",
            "_is_self": True,  # 标记为自身
        }
        data.insert(0, self_item)
        _LOGGER.info("已将 HAWGCS 自身添加到插件列表，版本: %s", local_version)

    async def refresh_plugin_list(self, entry_id: str = None) -> list[dict]:  # noqa: ARG002
        """拉远程 repositories.json 并标出已安装项。"""
        _LOGGER.debug("开始拉取索引: %s", self.index_url)
        try:
            session = aiohttp_client.async_get_clientsession(self.hass)
            async with session.get(
                self.index_url,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    raise HomeAssistantError(f"索引 {self.index_url} 返回 {resp.status}")
                text = await resp.text()
        except Exception as err:
            _LOGGER.error("拉取索引失败: %s", err)
            raise HomeAssistantError(f"拉取索引失败: {err}") from err

        try:
            data = _parse_index(text)
        except Exception as err:
            _LOGGER.error("索引解析失败: %s", err)
            raise HomeAssistantError(f"索引解析失败：{err}") from err

        # 添加自身到插件列表
        self._add_self_to_list(data)

        # enrich：标已安装 / 本地版本 / 是否有更新
        for item in data:
            try:
                await self._enrich_item(item)
            except Exception as err:
                _LOGGER.warning(" enrich 失败 %s: %s", item.get("slug"), err)

        self.plugin_list = data
        self._index_loaded = True
        _LOGGER.debug("索引加载完成: %s 条", len(data))

        # 加载 tips.json
        tips = await self._load_tips()
        
        return {
            "repositories": data,
            "tips": tips,
        }

    async def _load_tips(self) -> dict | None:
        """加载 tips.json（与 repositories.json 同级目录）。"""
        # tips.json 路径：索引同级目录
        tips_path_raw = self.index_path.rsplit("/", 1)[0] + "/tips.json"
        tips_url = (
            f"https://gitee.com/{self.repo}/raw/{self.branch}/{tips_path_raw}"
        )
        
        try:
            session = aiohttp_client.async_get_clientsession(self.hass)
            headers = {"Accept": "application/json"}
            if self.token:
                headers["Authorization"] = f"token {self.token}"
            
            async with session.get(
                tips_url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("tips.json 加载失败: status=%s", resp.status)
                    return None
                text = await resp.text()
                import json
                tips = json.loads(text)
                _LOGGER.info("tips.json 加载成功: %s", tips)
                return tips
        except Exception as err:
            _LOGGER.debug("tips.json 加载异常（不影响运行）: %s", err)
            return None

    async def _enrich_item(self, item: dict) -> None:
        """给单条 item 追加 installed / local_version / has_update 字段。"""
        rtype = item.get("type", "integration")
        slug = item.get("slug")
        if not slug or rtype not in self._stores:
            # 特殊处理：自身
            if item.get("_is_self"):
                item["installed"] = True
                item["local_version"] = item.get("version")
                item["has_update"] = False
            return

        store: StoreBase = self._stores[rtype]
        try:
            installed_list = await self.hass.async_add_executor_job(store.get_installed)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("读取 %s 已安装列表失败: %s", rtype, err)
            return

        local = next((x for x in installed_list if x["slug"] == slug), None)

        item["installed"] = local is not None
        item["local_version"] = (local or {}).get("version") if local else None
        # Lovelace 卡片没有 manifest.json，get_installed 返回的 version 永远是 None；
        # 此时用 repositories.json 里的 remote version 填充，显示效果更好。
        if not item["local_version"] and item.get("version"):
            item["local_version"] = item["version"]

        remote_ver = item.get("version")
        local_ver = item.get("local_version")
        item["has_update"] = (
            bool(local) and local_ver is not None
            and remote_ver is not None
            and _ver_gt(remote_ver, local_ver)
        )

    # ── 安装 / 卸载 / 更新 ──

    async def install(self, slug: str, rtype: str) -> dict[str, Any]:
        item = self._find_item(slug, rtype)
        if not item:
            raise HomeAssistantError(f"索引中找不到 [{slug}] ({rtype})")
        
        # 特殊处理：自身更新
        if item.get("_is_self"):
            return await self._update_self(item)
        
        store = self._stores.get(rtype)
        if not store:
            raise HomeAssistantError(f"不支持的类型: {rtype}")
        result = await store.install(item)
        # 重刷索引以更新 installed 标记
        await self.refresh_plugin_list()
        return result

    async def uninstall(self, slug: str, rtype: str) -> dict[str, Any]:
        # 禁止卸载自身
        if slug == "hawgcs" and rtype == "integration":
            raise HomeAssistantError("HAWGCS 不能卸载自身")
        
        store = self._stores.get(rtype)
        if not store:
            raise HomeAssistantError(f"不支持的类型: {rtype}")
        result = await store.uninstall(slug)
        await self.refresh_plugin_list()
        return result

    async def update(self, slug: str, rtype: str) -> dict[str, Any]:
        """更新等价于重新 install（store.install 本身就覆盖写）。"""
        return await self.install(slug, rtype)

    # ── 自身更新 ──

    async def _update_self(self, item: dict) -> dict[str, Any]:
        """更新 HAWGCS 自身（像普通插件一样从 integrations/hawgcs 下载）。"""
        from .store.integrations import IntegrationStore
        
        _LOGGER.info("开始更新 HAWGCS 自身...")
        
        remote_path = item.get("path") or "integrations/hawgcs"
        _LOGGER.info("开始更新 HAWGCS 自身，远程路径: %s", remote_path)

        # 仅复用 IntegrationStore 做递归下载，不走 install 的 rmtree/reload
        temp_store = IntegrationStore(self.hass, self.repo, self.branch, self.token)

        try:
            downloaded = await temp_store.download_tree_recursive(remote_path, "hawgcs")
            if not downloaded:
                raise HomeAssistantError("远程未返回任何文件，更新中止（本地文件保持不动）")
            _LOGGER.info("HAWGCS 更新完成，共 %s 个文件", len(downloaded))

            # 更新索引
            await self.refresh_plugin_list()
            
            return {
                "msg": f"✅ HAWGCS 已更新（{len(downloaded)} 个文件）。\n\n需要重启 Home Assistant 才能生效。",
                "requires_restart": True,
            }
        except Exception as err:
            _LOGGER.error("更新 HAWGCS 失败: %s", err, exc_info=True)
            raise HomeAssistantError(f"更新失败: {err}") from err

    # ── 状态 ──

    async def status(self) -> dict[str, Any]:
        by_type: dict[str, list] = {}
        for rtype, store in self._stores.items():
            try:
                by_type[rtype] = store.get_installed()
            except Exception as err:  # noqa: BLE001
                by_type[rtype] = []
                _LOGGER.warning("读取 %s 已安装列表失败: %s", rtype, err)

        return {
            "repo": self.repo,
            "branch": self.branch,
            "index_url": self.index_url,
            "index_loaded": self._index_loaded,
            "total_remote": len(self.plugin_list),
            "installed_by_type": by_type,
            "version": VERSION,
        }

    async def restart_ha(self) -> None:
        """重启 Home Assistant。"""
        try:
            await self.hass.services.async_call("homeassistant", "restart")
            _LOGGER.info("已调用 homeassistant.restart 服务")
        except Exception as err:
            _LOGGER.error("重启 HA 失败: %s", err)
            raise HomeAssistantError(f"重启失败: {err}") from err

    # ── helpers ──

    def _find_item(self, slug: str, rtype: str) -> dict | None:
        return next(
            (it for it in self.plugin_list
             if it.get("slug") == slug and it.get("type") == rtype),
            None,
        )


# ────────────────────────────────────────────
#  工具函数
# ────────────────────────────────────────────

def _parse_index(text: str) -> list[dict]:
    """解析 repositories.json，支持两种格式：
    - 数组   [...]
    - 对象   {repositories: [...]} （HACS 新格式）
    """
    import json

    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        repos = data.get("repositories") or data.get("items") or []
        return repos
    raise ValueError(f"无法识别的索引格式: {type(data)}")


def _ver_gt(new: str, old: str) -> bool:
    """简单版本号比对：new > old 返回 True。"""
    import re

    def _norm(v: str) -> list[int]:
        return [int(x) for x in re.split(r"[.+-]", v) if x.isdigit()]

    try:
        return _norm(new) > _norm(old)
    except Exception:  # noqa: BLE001
        return new != old

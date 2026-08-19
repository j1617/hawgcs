"""Store 基类：公共的拉索引、列目录、下载逻辑"""
from __future__ import annotations

import logging
import os
import shutil
from abc import ABC, abstractmethod
from typing import Any, Optional

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import aiohttp_client

from ..const import TYPE_INTEGRATION, TYPE_LOVELACE, TYPE_THEME, TYPE_APPDAEMON

_LOGGER = logging.getLogger(__name__)

# 每个类型装到 config_dir 下的哪个子目录
_TARGET_ROOT = {
    TYPE_INTEGRATION: "custom_components",
    TYPE_LOVELACE: "www/community",
    TYPE_THEME: "themes",
    TYPE_APPDAEMON: "appdaemon/apps",
}


class StoreBase(ABC):
    """所有 Store 的基类。子类只需实现 install / uninstall / reload / get_installed。"""

    # 子类覆盖
    type: str = ""
    _target_dir: str = ""

    def __init__(self, hass: HomeAssistant, repo: str, branch: str, token: str = "") -> None:
        self.hass = hass
        self.repo = repo
        self.branch = branch
        self.token = token

    # ==================== 公共 HTTP 工具 ====================

    async def _get_json(self, url: str, timeout: int = 15, retries: int = 3, headers: dict | None = None) -> Any:
        """带重试的 JSON GET，应对 Gitee API 不稳定。"""
        last_err: Exception | None = None
        import asyncio
        for attempt in range(1, retries + 1):
            try:
                session = aiohttp_client.async_get_clientsession(self.hass)
                headers = dict(headers) if headers else {}
                if self.token and "Authorization" not in headers:
                    headers["Authorization"] = f"token {self.token}"
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    if resp.status == 204:
                        return None
                    if resp.status != 200:
                        text = await resp.text()
                        _LOGGER.warning("_get_json [%s] 非200 [%s]: %s...", url, resp.status, text[:200])
                        raise HomeAssistantError(f"[{resp.status}] {url}")
                    text = await resp.text()
                    try:
                        import json
                        return json.loads(text)
                    except Exception as err:
                        _LOGGER.warning("JSON解析失败 [%s] 第%d次: %s", url, attempt, err)
                        raise HomeAssistantError(f"JSON解析失败 [{url}]: {err}") from err
            except Exception as err:
                last_err = err
                if attempt < retries:
                    _LOGGER.info("_get_json [%s] 第%d次失败，1秒后重试...", url, attempt)
                    await asyncio.sleep(1)
                    continue
                raise
        raise last_err or HomeAssistantError(f"_get_json [{url}] 全部重试失败")

    async def _download_bytes(self, url: str) -> bytes:
        session = aiohttp_client.async_get_clientsession(self.hass)
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                raise HomeAssistantError(f"[{resp.status}] {url}")
            return await resp.read()

    # ==================== Gitee 工具 ====================

    def raw_url(self, path: str) -> str:
        """raw 文件直链（公开仓库适用）。Gitee 会 302 跳转，aiohttp 自动跟随。"""
        return f"https://gitee.com/{self.repo}/raw/{self.branch}/{path}"

    def api_list_url(self, path: str) -> str:
        """OpenAPI 列目录。"""
        return f"https://gitee.com/api/v5/repos/{self.repo}/contents/{path}?ref={self.branch}"

    async def list_remote_entries(self, path: str) -> list[dict[str, Any]]:
        """返回目录下的全部条目（file + dir），不过滤。"""
        data = await self._get_json(self.api_list_url(path))
        if not isinstance(data, list):
            return []
        return data

    async def list_remote_dir(self, path: str) -> list[dict[str, Any]]:
        """返回目录下的文件列表（扁平，type=file 的项）。"""
        return [i for i in await self.list_remote_entries(path) if i.get("type") == "file"]

    # ==================== 文件系统工具 ====================

    @property
    def target_root(self) -> str:
        return self.hass.config.path(_TARGET_ROOT[self.type])

    def target_dir(self, slug: str) -> str:
        """根据 slug 拼目标目录。"""
        return os.path.join(self.target_root, slug)

    def manifest_path(self, slug: str) -> str:
        """统一取某个已安装项的 manifest 路径（供版本比对）。"""
        return os.path.join(self.target_dir(slug), "manifest.json")

    async def _write_atomic(self, path: str, data: bytes) -> None:
        """写文件，临时文件原子替换。"""
        await self.hass.async_add_executor_job(self._write_atomic_sync, path, data)

    def _write_atomic_sync(self, path: str, data: bytes) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + f".{os.getpid()}.tmp"
        with open(tmp, "wb") as fp:
            fp.write(data)
        os.replace(tmp, path)

    async def _rmtree(self, path: str) -> None:
        await self.hass.async_add_executor_job(shutil.rmtree, path)

    # ==================== 模板方法（子类实现） ====================

    @abstractmethod
    async def install(self, item: dict[str, Any]) -> dict[str, Any]:
        """下载并安装，返回 {msg, files}。"""
        raise NotImplementedError

    @abstractmethod
    async def uninstall(self, slug: str) -> dict[str, Any]:
        """卸载，返回 {msg}。"""
        raise NotImplementedError

    @abstractmethod
    async def reload(self, item: dict[str, Any]) -> dict[str, Any]:
        """重新加载/注册，返回 {msg}。"""
        raise NotImplementedError

    @abstractmethod
    def get_installed(self) -> list[dict[str, Any]]:
        """返回本地已安装项列表，每项含 {slug, version}。"""
        raise NotImplementedError

    @abstractmethod
    def is_installed(self, slug: str) -> bool:
        raise NotImplementedError

    # ==================== 公共下载入口（子类可复用） ====================

    async def download_tree(self, remote_path: str, target_slug: str) -> list[str]:
        """拉取远程目录（flat list）到本地目标目录，返回下载的文件路径列表。"""
        entries = await self.list_remote_dir(remote_path)
        if not entries:
            raise HomeAssistantError(f"远程目录不存在或为空：{remote_path}")

        target = self.target_dir(target_slug)
        _LOGGER.info("下载目标目录: %s", target)

        # 清旧
        if os.path.isdir(target):
            await self._rmtree(target)
        import functools
        await self.hass.async_add_executor_job(
            functools.partial(os.makedirs, target, exist_ok=True)
        )

        downloaded: list[str] = []
        session = aiohttp_client.async_get_clientsession(self.hass)

        for entry in entries:
            rel = entry["name"]
            if self._skip_file(rel):
                _LOGGER.debug("跳过文件: %s", rel)
                continue
            raw = self.raw_url(f"{remote_path}/{entry['name']}")
            try:
                content = await self._download_bytes(raw)
            except Exception as err:
                _LOGGER.warning("下载 %s 失败，跳过: %s", raw, err)
                continue
            save = os.path.join(target, rel)
            await self._write_atomic(save, content)
            downloaded.append(rel)
            _LOGGER.info("已下载: %s -> %s", rel, save)

        if not downloaded:
            raise HomeAssistantError(f"没有文件被下载：{remote_path}")

        _LOGGER.info("下载完成: %s 个文件到 %s", len(downloaded), target)
        return downloaded

    @staticmethod
    def _skip_file(rel: str) -> bool:
        """跳过不需要的文件。"""
        base = os.path.basename(rel)
        if base.startswith("."):
            return True
        # 不下载二进制
        bad_ext = {".png", ".jpg", ".jpeg", ".gif", ".zip", ".tar", ".gz", ".ico"}
        if os.path.splitext(base)[1].lower() in bad_ext:
            return True
        return False

    async def download_tree_recursive(
        self, remote_path: str, target_slug: str, _rel: str = ""
    ) -> list[str]:
        """递归下载远程目录（保留子目录结构），覆盖式写入，不清空目标目录。

        用于 HAWGCS 自身更新等多级包场景：避免 rmtree 误删 store/ 等子包，
        且能递归拉取子目录（download_tree 只处理扁平文件）。
        """
        entries = await self.list_remote_entries(remote_path)
        if not entries:
            if not _rel:
                raise HomeAssistantError(f"远程目录不存在或为空：{remote_path}")
            return []

        target = self.target_dir(target_slug)
        downloaded: list[str] = []

        for entry in entries:
            name = entry["name"]
            rel = os.path.join(_rel, name) if _rel else name
            etype = entry.get("type")
            if etype == "dir":
                sub = await self.download_tree_recursive(
                    f"{remote_path}/{name}", target_slug, _rel=rel
                )
                downloaded.extend(sub)
                continue
            if self._skip_file(rel):
                _LOGGER.debug("跳过文件: %s", rel)
                continue
            raw = self.raw_url(f"{remote_path}/{name}")
            try:
                content = await self._download_bytes(raw)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("下载 %s 失败，跳过: %s", raw, err)
                continue
            save = os.path.join(target, rel)
            await self._write_atomic(save, content)
            downloaded.append(rel)
            _LOGGER.info("已下载: %s -> %s", rel, save)

        return downloaded

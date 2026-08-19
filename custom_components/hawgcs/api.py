"""HAWGCS HTTP API"""
from __future__ import annotations

import logging

from aiohttp import web
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import VERSION
from homeassistant.helpers import aiohttp_client

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _store(request: web.Request):
    s = request.app["hass"].data.get(DOMAIN)
    if s is None:
        raise web.HTTPInternalServerError(reason="hawgcs_not_initialized")
    return s


def _json(request: web.Request) -> dict:
    try:
        return request.match_info
    except Exception:  # noqa: BLE001
        raise web.HTTPBadRequest(reason="invalid_json")


async def api_list(request: web.Request) -> web.Response:
    """GET /api/hawgcs/list"""
    store = _store(request)
    try:
        data = await store.refresh_plugin_list()
    except HomeAssistantError as err:
        raise web.HTTPBadRequest(reason=str(err))
    except Exception as err:
        import logging
        logging.getLogger(__name__).exception("api_list 失败")
        raise web.HTTPInternalServerError(reason=f"内部错误: {err}")
    return web.json_response(data)


async def api_install(request: web.Request) -> web.Response:
    """POST /api/hawgcs/install  {slug, type}"""
    store = _store(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise web.HTTPBadRequest(reason="invalid_json")
    slug = body.get("slug") or body.get("domain")
    rtype = body.get("type")
    if not slug or not rtype:
        raise web.HTTPBadRequest(reason="slug and type are required")
    try:
        result = await store.install(slug, rtype)
    except HomeAssistantError as err:
        return web.json_response({"status": "error", "msg": str(err)}, status=400)
    except Exception as err:
        _LOGGER.exception("api_install 失败: %s/%s", rtype, slug)
        return web.json_response({"status": "error", "msg": f"安装失败: {err}"}, status=500)
    return web.json_response({"status": "ok", **result})


async def api_uninstall(request: web.Request) -> web.Response:
    """POST /api/hawgcs/uninstall  {slug, type}"""
    store = _store(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise web.HTTPBadRequest(reason="invalid_json")
    slug = body.get("slug")
    rtype = body.get("type")
    if not slug or not rtype:
        raise web.HTTPBadRequest(reason="slug and type are required")
    try:
        result = await store.uninstall(slug, rtype)
    except HomeAssistantError as err:
        return web.json_response({"status": "error", "msg": str(err)}, status=400)
    return web.json_response({"status": "ok", **result})


async def api_update(request: web.Request) -> web.Response:
    """POST /api/hawgcs/update  {slug, type}"""
    store = _store(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise web.HTTPBadRequest(reason="invalid_json")
    slug = body.get("slug")
    rtype = body.get("type")
    if not slug or not rtype:
        raise web.HTTPBadRequest(reason="slug and type are required")
    try:
        result = await store.update(slug, rtype)
    except HomeAssistantError as err:
        return web.json_response({"status": "error", "msg": str(err)}, status=400)
    return web.json_response({"status": "ok", **result})


async def api_status(request: web.Request) -> web.Response:
    """GET /api/hawgcs/status"""
    store = _store(request)
    try:
        result = await store.status()
    except Exception as err:  # noqa: BLE001
        return web.json_response({"status": "error", "msg": str(err)}, status=500)

    return web.json_response({"status": "ok", **result})


async def api_version(request: web.Request) -> web.Response:
    """GET /api/hawgcs/version - 返回 HAWGCS 版本号（从 manifest.json 读取）"""
    import os, json
    base_dir = os.path.dirname(__file__)
    manifest_path = os.path.join(base_dir, "manifest.json")
    try:
        with open(manifest_path, encoding="utf-8") as f:
            data = json.load(f)
        version = data.get("version", VERSION)
    except Exception:
        version = VERSION
    return web.json_response({"status": "ok", "version": version})
    return web.json_response(result)


async def api_restart(request: web.Request) -> web.Response:
    """POST /api/hawgcs/restart - 重启 Home Assistant"""
    store = _store(request)
    try:
        await store.restart_ha()
    except HomeAssistantError as err:
        return web.json_response({"status": "error", "msg": str(err)}, status=400)
    except Exception as err:
        _LOGGER.exception("api_restart 失败")
        return web.json_response({"status": "error", "msg": f"重启失败: {err}"}, status=500)
    
    return web.json_response({"status": "ok", "msg": "正在重启 Home Assistant..."})


@callback
def register_api(hass: HomeAssistant) -> None:
    """向 HA HTTP server 注册路由。"""
    router = hass.http.app.router
    router.add_get("/api/hawgcs/list", api_list)
    router.add_post("/api/hawgcs/install", api_install)
    router.add_post("/api/hawgcs/uninstall", api_uninstall)
    router.add_post("/api/hawgcs/update", api_update)
    router.add_get("/api/hawgcs/status", api_status)
    router.add_post("/api/hawgcs/restart", api_restart)
    router.add_get("/api/hawgcs/version", api_version)
    _LOGGER.debug("HAWGCS API 已注册: list / install / uninstall / update / status / restart / version")

"""HAWGCS store 模块
按资源类型划分子模块，每个类型独立管理自己的安装/卸载/重载逻辑。
"""
from __future__ import annotations

from .base import StoreBase
from .integrations import IntegrationStore
from .lovelace import LovelaceStore
from .themes import ThemeStore

# type -> class 映射，供 Manager 按 type 调度
STORE_MAP = {
    "integration": IntegrationStore,
    "lovelace": LovelaceStore,
    "theme": ThemeStore,
}

__all__ = [
    "StoreBase",
    "IntegrationStore",
    "LovelaceStore",
    "ThemeStore",
    "STORE_MAP",
]

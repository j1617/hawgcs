"""HAWGCS 常量"""
from __future__ import annotations

DOMAIN = "hawgcs"

# 版本号
VERSION = "1.8.0"

# Gitee 仓库默认配置
DEFAULT_REPO = "hawgcs/hawgcs"
DEFAULT_BRANCH = "master"
DEFAULT_INDEX_PATH = "plugins/repositories.json"

CONF_REPO = "repo"
CONF_BRANCH = "branch"
CONF_INDEX_PATH = "index_path"
CONF_TOKEN = "token"

# ===================== 资源类型 =====================
TYPE_INTEGRATION = "integration"
TYPE_LOVELACE = "lovelace"
TYPE_THEME = "theme"
TYPE_APPDAEMON = "appdaemon"

ALL_TYPES = [TYPE_INTEGRATION, TYPE_LOVELACE, TYPE_THEME]

# 类型标签（UI 显示用）
TYPE_LABEL = {
    TYPE_INTEGRATION: "Integration",
    TYPE_LOVELACE: "Lovelace 卡片",
    TYPE_THEME: "Theme",
}

# 类型对应的 HA 主题 emoji（UI 用）
TYPE_ICON = {
    TYPE_INTEGRATION: "mdi:puzzle",
    TYPE_LOVELACE: "mdi:view-dashboard-outline",
    TYPE_THEME: "mdi:palette",
}

# 类型 -> 安装目标根目录名（相对 HA config_dir）
TARGET_DIR_NAME = {
    TYPE_INTEGRATION: "custom_components",
    TYPE_LOVELACE: "www/community",
    TYPE_THEME: "themes",
}

# 类型 -> 索引字段（每个 repo 必填字段校验用）
REQUIRED_FIELDS = {
    TYPE_INTEGRATION: {"slug", "type", "name", "domain", "path", "version"},
    TYPE_LOVELACE: {"slug", "type", "name", "repo", "path", "filename", "version"},
    TYPE_THEME: {"slug", "type", "name", "path", "version"},
}
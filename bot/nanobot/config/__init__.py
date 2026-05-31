"""Configuration module for nanobot."""

from nanobot.config.loader import get_config_path, load_config
from nanobot.config.capabilities import (
    context_prompt_files,
    load_capabilities,
    mode_trigger_file,
    monitor_log,
    observability_log,
    project_root_for,
    trigger_files,
)
from nanobot.config.paths import (
    get_bridge_install_dir,
    get_cli_history_path,
    get_cron_dir,
    get_data_dir,
    get_legacy_sessions_dir,
    is_default_workspace,
    get_logs_dir,
    get_media_dir,
    get_runtime_subdir,
    get_webui_dir,
    get_workspace_path,
)
from nanobot.config.schema import Config

__all__ = [
    "Config",
    "load_config",
    "load_capabilities",
    "project_root_for",
    "trigger_files",
    "context_prompt_files",
    "mode_trigger_file",
    "observability_log",
    "monitor_log",
    "get_config_path",
    "get_data_dir",
    "get_runtime_subdir",
    "get_media_dir",
    "get_cron_dir",
    "get_logs_dir",
    "get_webui_dir",
    "get_workspace_path",
    "is_default_workspace",
    "get_cli_history_path",
    "get_bridge_install_dir",
    "get_legacy_sessions_dir",
]

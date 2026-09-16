"""Safe tool registry for GW Project Bot.

Tools are registered as metadata only. Secrets stay in cPanel environment
variables; this module never stores API keys or tokens.
"""
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class ToolDefinition:
    key: str
    name: str
    description: str = ""
    handler: str = ""
    enabled: bool = True
    api_name: str = ""
    api_base_url: str = ""
    secret_env: str = ""


TOOLS = {
    "username_search": ToolDefinition(
        key="username_search",
        name="Username Search",
        description="Search public username information through the configured provider.",
        handler="username_api",
        api_name="",
        api_base_url="",
        secret_env="USERNAME_API_KEY",
    ),
    "tiktok_lookup": ToolDefinition(
        key="tiktok_lookup",
        name="TikTok Lookup",
        description="Lookup public TikTok profile information through the configured provider.",
        handler="tiktok_api",
        api_name="",
        api_base_url="",
        secret_env="TIKTOK_API_KEY",
    ),
}


def list_tools():
    """Return tool metadata for the dashboard or bot menu."""
    return [asdict(tool) for tool in TOOLS.values()]


def get_tool(key: str) -> Optional[ToolDefinition]:
    return TOOLS.get(key)


def register_tool(tool: ToolDefinition) -> None:
    """Register or replace a tool definition in memory.

    Persisting tool settings should be handled by the dashboard database.
    Never put actual secret values in ToolDefinition.
    """
    if not tool.key or not tool.name:
        raise ValueError("Tool key and name are required")
    TOOLS[tool.key] = tool

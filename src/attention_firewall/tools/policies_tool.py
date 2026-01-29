"""Policies tool for Amplifier - manages notification policies (VIPs, keywords, rules)."""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class PoliciesTool:
    """Tool for managing notification policies.

    Manages VIP lists, keywords, and app-specific rules.
    """

    def __init__(self, server_url: str = "http://localhost:19420", api_key: str | None = None):
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def name(self) -> str:
        return "policies"

    @property
    def description(self) -> str:
        return """Manage notification policies - VIPs, keywords, and app rules.

Operations:
- list_vips: Show current VIP senders
- add_vip: Add a sender to VIP list
- remove_vip: Remove a sender from VIP list
- list_keywords: Show escalation keywords
- add_keyword: Add an escalation keyword
- remove_keyword: Remove a keyword
- list_apps: Show app-specific rules
- mute_app: Mute notifications from an app
- unmute_app: Unmute an app
- get_config: Get full policy configuration

Examples:
- policies(operation="list_vips")
- policies(operation="add_vip", sender="Alice Smith", reason="Manager")
- policies(operation="add_keyword", keyword="urgent", reason="Escalation trigger")
- policies(operation="mute_app", app="WhatsApp", duration="2h")"""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "list_vips",
                        "add_vip",
                        "remove_vip",
                        "list_keywords",
                        "add_keyword",
                        "remove_keyword",
                        "list_apps",
                        "mute_app",
                        "unmute_app",
                        "get_config",
                    ],
                    "description": "Operation to perform",
                },
                "sender": {
                    "type": "string",
                    "description": "Sender name (for VIP operations)",
                },
                "keyword": {
                    "type": "string",
                    "description": "Keyword (for keyword operations)",
                },
                "app": {
                    "type": "string",
                    "description": "App name (for app operations)",
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for the policy change",
                },
                "duration": {
                    "type": "string",
                    "description": "Duration for temporary mutes (e.g., '2h', '1d')",
                },
            },
            "required": ["operation"],
        }

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Execute the policies operation."""
        operation = kwargs.get("operation")

        try:
            if operation == "list_vips":
                return await self._list_vips()
            elif operation == "add_vip":
                return await self._add_vip(kwargs.get("sender"), kwargs.get("reason"))
            elif operation == "remove_vip":
                return await self._remove_vip(kwargs.get("sender"))
            elif operation == "list_keywords":
                return await self._list_keywords()
            elif operation == "add_keyword":
                return await self._add_keyword(kwargs.get("keyword"), kwargs.get("reason"))
            elif operation == "remove_keyword":
                return await self._remove_keyword(kwargs.get("keyword"))
            elif operation == "list_apps":
                return await self._list_apps()
            elif operation == "mute_app":
                return await self._mute_app(kwargs.get("app"), kwargs.get("duration"))
            elif operation == "unmute_app":
                return await self._unmute_app(kwargs.get("app"))
            elif operation == "get_config":
                return await self._get_config()
            else:
                return {"success": False, "error": f"Unknown operation: {operation}"}
        except httpx.HTTPError as e:
            return {"success": False, "error": f"HTTP error: {e}"}
        except Exception as e:
            logger.exception("Policies tool error")
            return {"success": False, "error": f"Error: {e}"}

    async def _get_config(self) -> dict[str, Any]:
        """Get the current policy configuration."""
        response = await self._client.get(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
        )
        response.raise_for_status()
        config = response.json()
        return {"success": True, "output": f"Current configuration:\n{config}"}

    async def _list_vips(self) -> dict[str, Any]:
        """List current VIP senders."""
        response = await self._client.get(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
        )
        response.raise_for_status()
        config = response.json()

        vips = config.get("config", {}).get("global", {}).get("vip_senders", [])
        if not vips:
            return {"success": True, "output": "No VIP senders configured.", "vips": []}

        output = f"VIP Senders ({len(vips)}):\n"
        for vip in vips:
            output += f"- {vip}\n"

        return {"success": True, "output": output, "vips": vips}

    async def _add_vip(self, sender: str | None, reason: str | None) -> dict[str, Any]:
        """Add a sender to the VIP list."""
        if not sender:
            return {"success": False, "error": "Sender name required"}

        # Get current config
        response = await self._client.get(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
        )
        response.raise_for_status()
        config = response.json()

        # Add VIP
        vips = config.get("config", {}).get("global", {}).get("vip_senders", [])
        if sender in vips:
            return {"success": True, "output": f"{sender} is already a VIP"}

        vips.append(sender)

        # Update config
        if "global" not in config.get("config", {}):
            config["config"]["global"] = {}
        config["config"]["global"]["vip_senders"] = vips

        response = await self._client.put(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
            json=config["config"],
        )
        response.raise_for_status()

        msg = f"Added {sender} to VIP list"
        if reason:
            msg += f" (reason: {reason})"

        return {"success": True, "output": msg}

    async def _remove_vip(self, sender: str | None) -> dict[str, Any]:
        """Remove a sender from the VIP list."""
        if not sender:
            return {"success": False, "error": "Sender name required"}

        # Get current config
        response = await self._client.get(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
        )
        response.raise_for_status()
        config = response.json()

        # Remove VIP
        vips = config.get("config", {}).get("global", {}).get("vip_senders", [])
        if sender not in vips:
            return {"success": True, "output": f"{sender} is not in the VIP list"}

        vips.remove(sender)
        config["config"]["global"]["vip_senders"] = vips

        response = await self._client.put(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
            json=config["config"],
        )
        response.raise_for_status()

        return {"success": True, "output": f"Removed {sender} from VIP list"}

    async def _list_keywords(self) -> dict[str, Any]:
        """List escalation keywords."""
        response = await self._client.get(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
        )
        response.raise_for_status()
        config = response.json()

        keywords = config.get("config", {}).get("global", {}).get("keywords", [])
        if not keywords:
            return {
                "success": True,
                "output": "No escalation keywords configured.",
                "keywords": [],
            }

        output = f"Escalation Keywords ({len(keywords)}):\n"
        for kw in keywords:
            output += f"- {kw}\n"

        return {"success": True, "output": output, "keywords": keywords}

    async def _add_keyword(self, keyword: str | None, reason: str | None) -> dict[str, Any]:
        """Add an escalation keyword."""
        if not keyword:
            return {"success": False, "error": "Keyword required"}

        response = await self._client.get(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
        )
        response.raise_for_status()
        config = response.json()

        keywords = config.get("config", {}).get("global", {}).get("keywords", [])
        if keyword.lower() in [k.lower() for k in keywords]:
            return {
                "success": True,
                "output": f"'{keyword}' is already an escalation keyword",
            }

        keywords.append(keyword)
        if "global" not in config.get("config", {}):
            config["config"]["global"] = {}
        config["config"]["global"]["keywords"] = keywords

        response = await self._client.put(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
            json=config["config"],
        )
        response.raise_for_status()

        msg = f"Added '{keyword}' to escalation keywords"
        if reason:
            msg += f" (reason: {reason})"

        return {"success": True, "output": msg}

    async def _remove_keyword(self, keyword: str | None) -> dict[str, Any]:
        """Remove an escalation keyword."""
        if not keyword:
            return {"success": False, "error": "Keyword required"}

        response = await self._client.get(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
        )
        response.raise_for_status()
        config = response.json()

        keywords = config.get("config", {}).get("global", {}).get("keywords", [])
        keyword_lower = keyword.lower()
        matching = [k for k in keywords if k.lower() == keyword_lower]

        if not matching:
            return {
                "success": True,
                "output": f"'{keyword}' is not an escalation keyword",
            }

        keywords.remove(matching[0])
        config["config"]["global"]["keywords"] = keywords

        response = await self._client.put(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
            json=config["config"],
        )
        response.raise_for_status()

        return {"success": True, "output": f"Removed '{keyword}' from escalation keywords"}

    async def _list_apps(self) -> dict[str, Any]:
        """List app-specific rules."""
        response = await self._client.get(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
        )
        response.raise_for_status()
        config = response.json()

        apps = config.get("config", {}).get("apps", {})
        if not apps:
            return {
                "success": True,
                "output": "No app-specific rules configured.",
                "apps": {},
            }

        output = f"App Rules ({len(apps)} apps):\n"
        for app_name, rules in apps.items():
            output += f"\n{app_name}:\n"
            for key, value in rules.items():
                output += f"  - {key}: {value}\n"

        return {"success": True, "output": output, "apps": apps}

    async def _mute_app(self, app: str | None, duration: str | None) -> dict[str, Any]:
        """Mute notifications from an app."""
        if not app:
            return {"success": False, "error": "App name required"}

        response = await self._client.get(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
        )
        response.raise_for_status()
        config = response.json()

        if "apps" not in config.get("config", {}):
            config["config"]["apps"] = {}

        if app not in config["config"]["apps"]:
            config["config"]["apps"][app] = {}

        config["config"]["apps"][app]["muted"] = True
        if duration:
            config["config"]["apps"][app]["mute_until"] = duration

        response = await self._client.put(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
            json=config["config"],
        )
        response.raise_for_status()

        msg = f"Muted notifications from {app}"
        if duration:
            msg += f" for {duration}"

        return {"success": True, "output": msg}

    async def _unmute_app(self, app: str | None) -> dict[str, Any]:
        """Unmute notifications from an app."""
        if not app:
            return {"success": False, "error": "App name required"}

        response = await self._client.get(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
        )
        response.raise_for_status()
        config = response.json()

        apps = config.get("config", {}).get("apps", {})
        if app not in apps:
            return {"success": True, "output": f"{app} is not muted"}

        apps[app].pop("muted", None)
        apps[app].pop("mute_until", None)

        response = await self._client.put(
            f"{self.server_url}/config/notification-rules",
            headers=self._headers(),
            json=config["config"],
        )
        response.raise_for_status()

        return {"success": True, "output": f"Unmuted notifications from {app}"}


def create_tool() -> PoliciesTool:
    """Factory function to create the policies tool."""
    return PoliciesTool(
        server_url=os.environ.get("CORTEX_SERVER_URL", "http://localhost:19420"),
        api_key=os.environ.get("CORTEX_API_KEY"),
    )

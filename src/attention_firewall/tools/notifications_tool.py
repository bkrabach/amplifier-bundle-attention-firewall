"""Notifications tool for Amplifier - manages notification triage items."""

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class NotificationsTool:
    """Tool for managing notification triage items.

    Following ADR-001: Domain-centric naming with operation parameter.
    """

    def __init__(self, server_url: str = "http://localhost:19420", api_key: str | None = None):
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def name(self) -> str:
        return "notifications"

    @property
    def description(self) -> str:
        return """Manage notification triage items.

Use for viewing, updating, and analyzing notifications.

Operations:
- list: Get triage items (filters: view=pending|expired|all, app=..., limit=...)
- get: Get single item by ID
- update: Update item (action: dealt_with|ignore|already_handled, feedback: optional text)
- bulk_update: Update multiple items at once
- stats: Get notification statistics
- summary: Get recent activity summary

Examples:
- notifications(operation="stats") - Quick stats
- notifications(operation="list", filters={"view": "pending", "limit": 20})
- notifications(operation="update", id="123", action="dealt_with", feedback="...")
- notifications(operation="bulk_update", ids=["1","2","3"], action="ignore")"""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list", "get", "update", "bulk_update", "stats", "summary"],
                    "description": "Operation to perform",
                },
                "id": {
                    "type": "string",
                    "description": "Item ID (for get/update operations)",
                },
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Item IDs (for bulk_update operation)",
                },
                "action": {
                    "type": "string",
                    "enum": ["dealt_with", "ignore", "already_handled", "archive"],
                    "description": "Action to take (for update/bulk_update)",
                },
                "feedback": {
                    "type": "string",
                    "description": "Natural language feedback for learning",
                },
                "filters": {
                    "type": "object",
                    "description": "Filters for list operation",
                    "properties": {
                        "view": {
                            "type": "string",
                            "enum": ["pending", "expired", "all"],
                        },
                        "app": {"type": "string"},
                        "limit": {"type": "integer"},
                        "offset": {"type": "integer"},
                    },
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
        """Execute the notifications operation."""
        operation = kwargs.get("operation")

        try:
            if operation == "list":
                return await self._list_items(kwargs.get("filters", {}))
            elif operation == "get":
                return await self._get_item(kwargs.get("id"))
            elif operation == "update":
                return await self._update_item(
                    kwargs.get("id"), kwargs.get("action"), kwargs.get("feedback")
                )
            elif operation == "bulk_update":
                return await self._bulk_update(
                    kwargs.get("ids", []), kwargs.get("action"), kwargs.get("feedback")
                )
            elif operation == "stats":
                return await self._get_stats()
            elif operation == "summary":
                return await self._get_summary()
            else:
                return {"success": False, "error": f"Unknown operation: {operation}"}
        except httpx.HTTPError as e:
            return {"success": False, "error": f"HTTP error: {e}"}
        except Exception as e:
            logger.exception("Notifications tool error")
            return {"success": False, "error": f"Error: {e}"}

    async def _list_items(self, filters: dict) -> dict[str, Any]:
        """List triage items with optional filters."""
        params = {}
        if filters.get("limit"):
            params["limit"] = filters["limit"]

        response = await self._client.get(
            f"{self.server_url}/triage/items",
            headers=self._headers(),
            params=params,
        )
        response.raise_for_status()
        data = response.json()

        # Filter by view if specified
        view = filters.get("view", "pending")
        if view == "pending":
            items = (
                data.get("surfaced", []) + data.get("expiring_soon", []) + data.get("pending", [])
            )
        elif view == "expired":
            items = data.get("expired", [])
        else:  # all
            items = (
                data.get("surfaced", [])
                + data.get("expiring_soon", [])
                + data.get("pending", [])
                + data.get("expired", [])
            )

        # Filter by app if specified
        if filters.get("app"):
            items = [
                i for i in items if filters["app"].lower() in (i.get("app_name") or "").lower()
            ]

        # Format output
        output = f"Found {len(items)} items"
        if items:
            output += ":\n\n"
            for item in items[: filters.get("limit", 20)]:
                output += (
                    f"- [{item.get('id')}] {item.get('app_name')}: {item.get('title', '')[:50]}\n"
                )
                output += (
                    f"  From: {item.get('sender_hint', 'Unknown')} | "
                    f"Score: {item.get('relevance_score', 'N/A')}\n"
                )
                if item.get("rationale"):
                    output += f"  Rationale: {item.get('rationale')[:80]}...\n"
                output += "\n"

        return {"success": True, "output": output, "items": items}

    async def _get_item(self, item_id: str | None) -> dict[str, Any]:
        """Get a single triage item by ID."""
        if not item_id:
            return {"success": False, "error": "Item ID required"}

        response = await self._client.get(
            f"{self.server_url}/notifications/{item_id}",
            headers=self._headers(),
        )
        response.raise_for_status()
        item = response.json()

        return {"success": True, "output": json.dumps(item, indent=2), "item": item}

    async def _update_item(
        self, item_id: str | None, action: str | None, feedback: str | None
    ) -> dict[str, Any]:
        """Update a single triage item."""
        if not item_id:
            return {"success": False, "error": "Item ID required"}
        if not action:
            return {"success": False, "error": "Action required"}

        payload: dict[str, Any] = {"action": action}
        if feedback:
            payload["feedback_text"] = feedback

        response = await self._client.post(
            f"{self.server_url}/triage/items/{item_id}/action",
            headers=self._headers(),
            json=payload,
        )
        response.raise_for_status()

        return {
            "success": True,
            "output": f"Updated item {item_id} with action: {action}",
        }

    async def _bulk_update(
        self, ids: list[str], action: str | None, feedback: str | None
    ) -> dict[str, Any]:
        """Update multiple triage items."""
        if not ids:
            return {"success": False, "error": "Item IDs required"}
        if not action:
            return {"success": False, "error": "Action required"}

        results = []
        for item_id in ids:
            try:
                payload: dict[str, Any] = {"action": action}
                if feedback:
                    payload["feedback_text"] = feedback

                response = await self._client.post(
                    f"{self.server_url}/triage/items/{item_id}/action",
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                results.append(f"+ {item_id}")
            except Exception as e:
                results.append(f"x {item_id}: {e}")

        return {
            "success": True,
            "output": f"Bulk update complete ({len(ids)} items):\n" + "\n".join(results),
        }

    async def _get_stats(self) -> dict[str, Any]:
        """Get notification statistics."""
        response = await self._client.get(
            f"{self.server_url}/triage/items",
            headers=self._headers(),
        )
        response.raise_for_status()
        data = response.json()

        stats = {
            "surfaced": len(data.get("surfaced", [])),
            "expiring_soon": len(data.get("expiring_soon", [])),
            "pending": len(data.get("pending", [])),
            "expired": len(data.get("expired", [])),
            "total_actionable": data.get("total_count", 0),
        }

        output = f"""Notification Statistics:
- Surfaced (pushed through): {stats["surfaced"]}
- Expiring soon: {stats["expiring_soon"]}
- Pending triage: {stats["pending"]}
- Expired (for review): {stats["expired"]}
- Total needing action: {stats["total_actionable"]}"""

        return {"success": True, "output": output, "stats": stats}

    async def _get_summary(self) -> dict[str, Any]:
        """Get a summary of recent notification activity."""
        response = await self._client.get(
            f"{self.server_url}/triage/items",
            headers=self._headers(),
            params={"limit": 50},
        )
        response.raise_for_status()
        data = response.json()

        # Aggregate by app
        apps: dict[str, dict[str, int]] = {}
        all_items = (
            data.get("surfaced", []) + data.get("expiring_soon", []) + data.get("pending", [])
        )

        for item in all_items:
            app = item.get("app_name", "Unknown")
            if app not in apps:
                apps[app] = {"count": 0, "high_priority": 0}
            apps[app]["count"] += 1
            if (item.get("relevance_score") or 0) > 0.7:
                apps[app]["high_priority"] += 1

        output = f"Notification Summary ({len(all_items)} pending items):\n\n"
        for app, info in sorted(apps.items(), key=lambda x: x[1]["count"], reverse=True):
            output += f"- {app}: {info['count']} items"
            if info["high_priority"]:
                output += f" ({info['high_priority']} high priority)"
            output += "\n"

        return {"success": True, "output": output, "apps": apps}


def create_tool() -> NotificationsTool:
    """Factory function to create the notifications tool."""
    return NotificationsTool(
        server_url=os.environ.get("CORTEX_SERVER_URL", "http://localhost:19420"),
        api_key=os.environ.get("CORTEX_API_KEY"),
    )

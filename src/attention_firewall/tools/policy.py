"""Policy management tool for Amplifier.

Allows the agent to manage VIPs, keywords, app muting, and other policies
through conversational commands.
"""

from datetime import datetime, timedelta
from typing import Any


class PolicyTool:
    """Tool for managing notification filtering policies.
    
    Supports operations like:
    - Adding/removing VIP senders
    - Adding/removing priority keywords
    - Muting/unmuting apps
    - Viewing current policies
    """
    
    def __init__(self, state_manager):
        """Initialize with shared state manager.
        
        Args:
            state_manager: NotificationStateManager instance
        """
        self.state = state_manager
    
    @property
    def name(self) -> str:
        return "manage_policy"
    
    @property
    def description(self) -> str:
        return """Manage notification filtering policies.

Operations:
- add_vip: Add a sender to VIP list (their messages always get through)
- remove_vip: Remove a sender from VIP list
- list_vips: Show all VIP senders
- add_keyword: Add a priority keyword (triggers surfacing)
- remove_keyword: Remove a priority keyword
- list_keywords: Show all priority keywords
- mute_app: Temporarily mute an app's notifications
- unmute_app: Unmute an app
- list_muted: Show muted apps
- list_all: Show all current policies
- get_stats: Get notification statistics

For mute_app, use 'value' to specify duration:
- "1h", "2h" for hours
- "30m", "45m" for minutes
- "until 2pm", "until 14:00" for specific time
- Empty or omit for indefinite mute"""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "add_vip", "remove_vip", "list_vips",
                        "add_keyword", "remove_keyword", "list_keywords",
                        "mute_app", "unmute_app", "list_muted",
                        "list_all", "get_stats"
                    ],
                    "description": "The policy operation to perform"
                },
                "target": {
                    "type": "string",
                    "description": "The target of the operation (sender name, keyword, or app name)"
                },
                "value": {
                    "type": "string",
                    "description": "Additional value (e.g., duration for mute_app, notes for add_vip)"
                }
            },
            "required": ["operation"]
        }
    
    async def execute(self, **kwargs) -> dict[str, Any]:
        """Execute policy operation."""
        operation = kwargs.get("operation", "")
        target = kwargs.get("target", "")
        value = kwargs.get("value", "")
        
        # Dispatch to appropriate handler
        handlers = {
            "add_vip": self._add_vip,
            "remove_vip": self._remove_vip,
            "list_vips": self._list_vips,
            "add_keyword": self._add_keyword,
            "remove_keyword": self._remove_keyword,
            "list_keywords": self._list_keywords,
            "mute_app": self._mute_app,
            "unmute_app": self._unmute_app,
            "list_muted": self._list_muted,
            "list_all": self._list_all,
            "get_stats": self._get_stats,
        }
        
        handler = handlers.get(operation)
        if not handler:
            return {
                "success": False,
                "error": f"Unknown operation: {operation}",
                "valid_operations": list(handlers.keys()),
            }
        
        return await handler(target, value)
    
    async def _add_vip(self, target: str, value: str) -> dict[str, Any]:
        """Add sender to VIP list."""
        if not target:
            return {"success": False, "error": "Must specify sender name as 'target'"}
        
        self.state.add_vip(target, notes=value)
        return {
            "success": True,
            "message": f"Added '{target}' to VIP list",
            "notes": value or None,
        }
    
    async def _remove_vip(self, target: str, value: str) -> dict[str, Any]:
        """Remove sender from VIP list."""
        if not target:
            return {"success": False, "error": "Must specify sender name as 'target'"}
        
        existed = self.state.remove_vip(target)
        if existed:
            return {"success": True, "message": f"Removed '{target}' from VIP list"}
        else:
            return {"success": True, "message": f"'{target}' was not in VIP list"}
    
    async def _list_vips(self, target: str, value: str) -> dict[str, Any]:
        """List all VIPs."""
        vips = self.state.get_vips()
        return {
            "success": True,
            "count": len(vips),
            "vips": vips,
        }
    
    async def _add_keyword(self, target: str, value: str) -> dict[str, Any]:
        """Add priority keyword."""
        if not target:
            return {"success": False, "error": "Must specify keyword as 'target'"}
        
        self.state.add_keyword(target)
        return {"success": True, "message": f"Added '{target}' as priority keyword"}
    
    async def _remove_keyword(self, target: str, value: str) -> dict[str, Any]:
        """Remove priority keyword."""
        if not target:
            return {"success": False, "error": "Must specify keyword as 'target'"}
        
        existed = self.state.remove_keyword(target)
        if existed:
            return {"success": True, "message": f"Removed '{target}' from priority keywords"}
        else:
            return {"success": True, "message": f"'{target}' was not a priority keyword"}
    
    async def _list_keywords(self, target: str, value: str) -> dict[str, Any]:
        """List all priority keywords."""
        keywords = self.state.get_keywords()
        return {
            "success": True,
            "count": len(keywords),
            "keywords": sorted(keywords),
        }
    
    async def _mute_app(self, target: str, value: str) -> dict[str, Any]:
        """Mute an app's notifications."""
        if not target:
            return {"success": False, "error": "Must specify app name as 'target'"}
        
        until = self._parse_duration(value)
        self.state.mute_app(target, until=until)
        
        if until:
            return {
                "success": True,
                "message": f"Muted '{target}' until {until.strftime('%I:%M %p')}",
            }
        else:
            return {
                "success": True,
                "message": f"Muted '{target}' indefinitely",
            }
    
    async def _unmute_app(self, target: str, value: str) -> dict[str, Any]:
        """Unmute an app."""
        if not target:
            return {"success": False, "error": "Must specify app name as 'target'"}
        
        was_muted = self.state.unmute_app(target)
        if was_muted:
            return {"success": True, "message": f"Unmuted '{target}'"}
        else:
            return {"success": True, "message": f"'{target}' was not muted"}
    
    async def _list_muted(self, target: str, value: str) -> dict[str, Any]:
        """List muted apps."""
        muted = self.state.get_muted_apps()
        formatted = {}
        for app, until in muted.items():
            if until:
                formatted[app] = f"until {until.strftime('%I:%M %p')}"
            else:
                formatted[app] = "indefinite"
        
        return {
            "success": True,
            "count": len(muted),
            "muted_apps": formatted,
        }
    
    async def _list_all(self, target: str, value: str) -> dict[str, Any]:
        """List all policies."""
        policies = self.state.get_all_policies()
        return {
            "success": True,
            "policies": policies,
        }
    
    async def _get_stats(self, target: str, value: str) -> dict[str, Any]:
        """Get notification statistics."""
        # Default to 24 hours, but allow override
        hours = 24
        if value:
            try:
                hours = int(value)
            except ValueError:
                pass
        
        stats = self.state.get_statistics(hours=hours)
        return {
            "success": True,
            "statistics": stats,
        }
    
    def _parse_duration(self, duration_str: str) -> datetime | None:
        """Parse duration string to datetime."""
        if not duration_str:
            return None
        
        duration_str = duration_str.strip().lower()
        now = datetime.now()
        
        # Handle "Xh" format (hours)
        if duration_str.endswith("h"):
            try:
                hours = int(duration_str[:-1])
                return now + timedelta(hours=hours)
            except ValueError:
                pass
        
        # Handle "Xm" format (minutes)
        if duration_str.endswith("m"):
            try:
                minutes = int(duration_str[:-1])
                return now + timedelta(minutes=minutes)
            except ValueError:
                pass
        
        # Handle "until HH:MM" or "until H:MMpm" format
        if duration_str.startswith("until "):
            time_str = duration_str[6:].strip()
            return self._parse_time(time_str)
        
        # Try parsing as time directly
        return self._parse_time(duration_str)
    
    def _parse_time(self, time_str: str) -> datetime | None:
        """Parse time string to datetime (today or tomorrow)."""
        now = datetime.now()
        
        # Try various time formats
        formats = [
            "%I:%M%p",   # 2:00pm
            "%I:%M %p",  # 2:00 pm
            "%I%p",      # 2pm
            "%I %p",     # 2 pm
            "%H:%M",     # 14:00
        ]
        
        for fmt in formats:
            try:
                parsed = datetime.strptime(time_str.upper(), fmt)
                result = now.replace(
                    hour=parsed.hour,
                    minute=parsed.minute,
                    second=0,
                    microsecond=0,
                )
                # If time is in the past, assume tomorrow
                if result < now:
                    result += timedelta(days=1)
                return result
            except ValueError:
                continue
        
        return None

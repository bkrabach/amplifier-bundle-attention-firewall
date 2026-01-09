"""Summary generation tool for Amplifier.

Generates notification digests from pending/filtered notifications.
"""

from typing import Any


class SummaryTool:
    """Tool for generating notification summaries.
    
    Creates digests of filtered notifications for periodic review.
    """
    
    def __init__(self, state_manager):
        """Initialize with shared state manager.
        
        Args:
            state_manager: NotificationStateManager instance
        """
        self.state = state_manager
    
    @property
    def name(self) -> str:
        return "generate_summary"
    
    @property
    def description(self) -> str:
        return """Generate a summary of pending/filtered notifications.

Use this to:
1. Create periodic digests (hourly, daily)
2. Answer "what did I miss?" questions
3. Review what's been filtered

Options:
- timeframe: How far back to look (in hours, default 24)
- include_surfaced: Whether to include notifications that were surfaced (default false)
- clear_pending: Whether to mark pending notifications as processed (default false)
- group_by: How to group results - "app", "sender", or "time" (default "app")"""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "timeframe": {
                    "type": "integer",
                    "description": "How many hours back to look (default: 24)"
                },
                "include_surfaced": {
                    "type": "boolean",
                    "description": "Include notifications that were already surfaced (default: false)"
                },
                "clear_pending": {
                    "type": "boolean",
                    "description": "Mark pending notifications as processed after generating summary (default: false)"
                },
                "group_by": {
                    "type": "string",
                    "enum": ["app", "sender", "time"],
                    "description": "How to group the results (default: app)"
                }
            }
        }
    
    async def execute(self, **kwargs) -> dict[str, Any]:
        """Generate notification summary."""
        timeframe = kwargs.get("timeframe", 24)
        include_surfaced = kwargs.get("include_surfaced", False)
        clear_pending = kwargs.get("clear_pending", False)
        group_by = kwargs.get("group_by", "app")
        
        # Get pending notifications
        pending = self.state.get_pending_notifications(hours=timeframe)
        
        # Get statistics
        stats = self.state.get_statistics(hours=timeframe)
        
        # Group notifications
        grouped = self._group_notifications(pending, group_by)
        
        # Build summary
        summary = {
            "success": True,
            "timeframe_hours": timeframe,
            "total_pending": len(pending),
            "statistics": {
                "total_received": stats["total"],
                "surfaced": stats["surfaced"],
                "suppressed": stats["suppressed"],
                "in_digest": stats["digest"],
            },
            "grouped": grouped,
            "notifications": pending if len(pending) <= 20 else pending[:20],
            "truncated": len(pending) > 20,
        }
        
        # Generate human-readable summary text
        summary["summary_text"] = self._generate_summary_text(stats, grouped)
        
        # Clear pending if requested
        if clear_pending:
            cleared = self.state.clear_pending_notifications()
            summary["cleared_count"] = cleared
        
        return summary
    
    def _group_notifications(
        self, 
        notifications: list[dict], 
        group_by: str
    ) -> dict[str, list[dict]]:
        """Group notifications by specified field."""
        groups: dict[str, list[dict]] = {}
        
        for notif in notifications:
            if group_by == "app":
                key = notif.get("app_id", "Unknown")
            elif group_by == "sender":
                key = notif.get("sender") or "Unknown sender"
            elif group_by == "time":
                # Group by hour
                timestamp = notif.get("timestamp", "")
                if timestamp and len(timestamp) >= 13:
                    key = timestamp[:13] + ":00"  # YYYY-MM-DDTHH:00
                else:
                    key = "Unknown time"
            else:
                key = "all"
            
            if key not in groups:
                groups[key] = []
            groups[key].append(notif)
        
        return groups
    
    def _generate_summary_text(
        self, 
        stats: dict, 
        grouped: dict[str, list[dict]]
    ) -> str:
        """Generate human-readable summary."""
        lines = []
        
        # Overall stats
        total = stats["total"]
        surfaced = stats["surfaced"]
        suppressed = stats["suppressed"]
        digest = stats["digest"]
        
        if total == 0:
            return "No notifications in this timeframe."
        
        lines.append(f"Received {total} notifications:")
        lines.append(f"  - {surfaced} surfaced to you")
        lines.append(f"  - {suppressed} suppressed (noise)")
        lines.append(f"  - {digest} held for this digest")
        lines.append("")
        
        # By app breakdown
        if grouped:
            lines.append("Breakdown by app:")
            for app, notifs in sorted(grouped.items(), key=lambda x: -len(x[1])):
                count = len(notifs)
                # Get unique senders
                senders = set(n.get("sender") for n in notifs if n.get("sender"))
                if senders:
                    sender_str = f" from {', '.join(list(senders)[:3])}"
                    if len(senders) > 3:
                        sender_str += f" and {len(senders) - 3} others"
                else:
                    sender_str = ""
                lines.append(f"  - {app}: {count} notification(s){sender_str}")
        
        return "\n".join(lines)

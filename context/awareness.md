# Attention Firewall Capabilities

You have access to notification attention management via the Attention Firewall behavior.

## Available Agent

**`attention-firewall:triage-manager`** - Specialized agent for notification triage

Delegate to this agent for:
- Reviewing and triaging pending notifications
- Bulk cleanup of old/expired items
- Adjusting notification policies (VIPs, keywords, app rules)
- Getting notification statistics and summaries
- Processing user feedback to improve scoring

## Quick Operations

For simple queries, you can use tools directly:
- `notifications(operation="stats")` - Quick statistics
- `notifications(operation="summary")` - Recent activity summary

For complex operations (cleanup proposals, rule changes, analysis), delegate to the triage-manager agent.

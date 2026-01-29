---
behavior:
  name: attention-firewall
  version: 1.0.0
  description: Notification attention management with AI-powered triage

context:
  - context/awareness.md
  - context/delegation-policy.md

agents:
  triage-manager:
    source: agents/triage-manager.md
    description: Manages notification triage, cleanup, and rule adjustments

tools:
  - source: src/attention_firewall/tools/notifications_tool.py
  - source: src/attention_firewall/tools/policies_tool.py
---

# Attention Firewall Behavior

Provides notification attention management capabilities:
- Triage pending notifications
- Review and provide feedback on past decisions
- Manage VIP lists and notification policies
- Get summaries and statistics

## Usage

Compose this behavior into your main bundle to enable notification management.
Delegate triage operations to `attention-firewall:triage-manager`.

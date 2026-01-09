# Attention Firewall

**AI-powered Windows notification controller** - Take back control of your attention.

Attention Firewall intercepts Windows notifications from apps like Teams, WhatsApp, and Outlook, filters them using AI-powered relevance scoring, and only surfaces what truly matters. Everything else goes into periodic digests.

## Features

- **Universal capture** - Listens to ALL Windows toast notifications
- **Smart filtering** - VIP senders, priority keywords, time-sensitive detection
- **Noise suppression** - Automatically filters "liked your message", reactions, etc.
- **Periodic digests** - Hourly/daily summaries of filtered notifications
- **Policy management** - Add VIPs, keywords, mute apps via CLI or conversation
- **Agent-branded toasts** - Clear rationale for why something was surfaced

## Requirements

- **Windows 10** (Anniversary Update or later) or **Windows 11**
- **Python 3.11+**
- Notifications enabled in Windows Settings for target apps

## Quick Start

### 1. Install

```bash
# Clone the repository
git clone https://github.com/yourusername/attention-firewall.git
cd attention-firewall

# Install with uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .
```

### 2. Configure Windows

For the system to work, you need to disable notification banners for apps you want to filter (while keeping notifications enabled):

1. Open **Settings → System → Notifications**
2. For each app (Teams, WhatsApp, Outlook):
   - Click the app name
   - Turn **OFF** "Show notification banners"
   - Keep **ON** "Show notifications in notification center"

This allows Attention Firewall to capture notifications without you seeing the native popups.

### 3. Run

```bash
# Check if your system is ready
attention-firewall check

# Run the daemon
attention-firewall run

# Run with custom config
attention-firewall run --config my-policy.yaml
```

### 4. Manage Policies

```bash
# Add a VIP (their messages always get through)
attention-firewall add-vip "Alice Chen"

# View current policies
attention-firewall policies

# View notification summary
attention-firewall summary --hours 24

# Send a test notification
attention-firewall test --title "Hello" --body "Test message"
```

## Configuration

Create a policy file (YAML) to customize filtering:

```yaml
# ~/.attention-firewall/config.yaml

apps:
  Microsoft Teams:
    ingest: true
    default_action: evaluate  # Let AI decide
    
  WhatsApp:
    ingest: true
    default_action: summarize  # Batch for digest
    
  Microsoft Outlook:
    ingest: true
    default_action: evaluate
    escalate_keywords:
      - "deadline"
      - "urgent"

global:
  # VIP senders - always surface their messages
  vip_senders:
    - "Your Boss"
    - "Important Client"
    
  # Keywords that trigger surfacing
  priority_keywords:
    - "deadline"
    - "urgent"
    - "blocked"
    - "meeting in"
    
  # Times for automatic digests
  digest_schedule:
    - time: "09:00"
      type: "morning"
    - time: "17:00"
      type: "eod"
      
  # Patterns to always suppress (noise)
  suppress_patterns:
    - "liked your message"
    - "is typing"
    - "reacted with"
```

## How It Works

```
1. App sends notification (Teams, WhatsApp, etc.)
   │
   ▼
2. Windows receives notification
   │
   ├──▶ [Native banner suppressed via Settings]
   │
   ▼
3. Attention Firewall captures via UserNotificationListener API
   │
   ▼
4. Filtering pipeline:
   │  • Check VIP list → SURFACE immediately
   │  • Check keywords → SURFACE with rationale
   │  • Check suppress patterns → SUPPRESS (noise)
   │  • Otherwise → ADD TO DIGEST
   │
   ▼
5. If SURFACE: Send agent-branded toast with rationale
   │
   ▼
6. User sees filtered notification: "Teams | Alice: Review needed (deadline)"
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `run` | Start the standalone daemon service |
| `client` | Connect to amplifier-app-server (recommended) |
| `server-status` | Check amplifier-app-server status |
| `check` | Verify system requirements |
| `summary` | Show notification statistics |
| `policies` | Show current policies |
| `add-vip <name>` | Add sender to VIP list |
| `remove-vip <name>` | Remove sender from VIP list |
| `test` | Send a test notification |

## Client Mode (Recommended)

For the best experience, run Attention Firewall in **client mode** connected to an [amplifier-app-server](https://github.com/bkrabach/amplifier-app-server):

```bash
# On your always-on server (Linux/WSL/Mac)
amplifier-server run --bundle attention-firewall --port 8420

# On your Windows machine(s)
attention-firewall client --server http://your-server:8420
```

**Benefits of client mode:**
- AI-powered filtering via full Amplifier sessions
- Multi-device support (all your Windows machines report to one hub)
- Remote access via Tailscale or similar
- Persistent conversation context across sessions
- Chat with your personal assistant about notifications

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CLIENT MODE ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Windows Device 1          Windows Device 2          Windows Device 3│
│  ┌───────────────┐         ┌───────────────┐         ┌───────────────┐│
│  │ attention-    │         │ attention-    │         │ attention-    ││
│  │ firewall      │         │ firewall      │         │ firewall      ││
│  │ client        │         │ client        │         │ client        ││
│  └───────┬───────┘         └───────┬───────┘         └───────┬───────┘│
│          │                         │                         │       │
│          │     HTTP/WebSocket      │                         │       │
│          └─────────────────────────┼─────────────────────────┘       │
│                                    │                                 │
│                                    ▼                                 │
│                    ┌───────────────────────────────┐                │
│                    │    amplifier-app-server       │                │
│                    │    (always-on hub)            │                │
│                    │                               │                │
│                    │  • AI-powered filtering       │                │
│                    │  • Conversation context       │                │
│                    │  • Policy management          │                │
│                    │  • Multi-device sync          │                │
│                    └───────────────────────────────┘                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Data Storage

All data is stored locally in `~/.attention-firewall/`:

```
~/.attention-firewall/
├── notifications.db    # SQLite database
├── config.yaml         # Your policy configuration
└── logs/               # Log files (if enabled)
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    ATTENTION FIREWALL                        │
├─────────────────────────────────────────────────────────────┤
│  Notification Listener (pywinrt)                             │
│  └──▶ AsyncIO Queue ──▶ Filtering Pipeline                  │
│                              │                               │
│                              ▼                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  State Manager (SQLite + In-Memory Cache)           │    │
│  │  • VIP senders     • Priority keywords              │    │
│  │  • Muted apps      • Suppress patterns              │    │
│  └─────────────────────────────────────────────────────┘    │
│                              │                               │
│                              ▼                               │
│  Toast Sender ──▶ Agent-branded notifications                │
│                                                              │
│  Scheduler (APScheduler) ──▶ Periodic digests               │
└─────────────────────────────────────────────────────────────┘
```

## Amplifier Integration (Future)

The system is designed to integrate with [Amplifier](https://github.com/microsoft/amplifier) for AI-powered decision making. The bundle definition (`bundle.md`) and custom tools are ready for Amplifier session integration.

With Amplifier:
- Natural language policy updates: "Add Alice to my VIP list"
- Context-aware filtering: Understands conversation threads
- Learning from feedback: Improves over time

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Type checking
pyright

# Linting
ruff check .
```

## Troubleshooting

### "Notification access denied"

1. Open **Settings → Privacy → Notifications**
2. Enable notification access for your terminal/Python

### Notifications not being captured

1. Run `attention-firewall check` to verify setup
2. Ensure the app's notifications are enabled in Windows Settings
3. Make sure you're running on Windows 10 Anniversary Update or later

### Running on non-Windows

The notification listener will run in "mock mode" on non-Windows platforms. You can still test the filtering logic and tools, but no real notifications will be captured.

## License

MIT

## Acknowledgments

Built with:
- [pywinrt](https://github.com/pywinrt/pywinrt) - Windows Runtime bindings for Python
- [APScheduler](https://github.com/agronholm/apscheduler) - Advanced Python Scheduler
- [Click](https://github.com/pallets/click) - CLI framework
- [Amplifier](https://github.com/microsoft/amplifier) - AI agent framework (optional integration)

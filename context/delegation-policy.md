# Attention Firewall Delegation Policy

## MUST Delegate to `attention-firewall:triage-manager`

- "Clean up my notifications" - requires judgment, bulk operations
- "Review my triage queue" - requires analysis, recommendations
- "Add X as a VIP" / "Change notification rules" - requires policy understanding
- "Why was this notification scored this way?" - requires analysis
- "Propose VIP rules based on my activity" - requires pattern analysis
- Any request involving multiple notification operations
- Any request involving feedback or learning

## MAY Use Tools Directly

- "How many notifications do I have?" -> `notifications(operation="stats")`
- "Show me notification summary" -> `notifications(operation="summary")`
- Quick single-item lookups

## Passthrough Delegation

When delegating, pass the user's request verbatim. Do NOT pre-process or analyze.
The triage-manager agent has deeper context and specialized tools.

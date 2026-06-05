"""English catalog (DEFAULT locale). Slash-command descriptions live in okami/commands.py (the source of
truth), so they are NOT repeated here — only framework strings that need a localizable key.
"""

MESSAGES: dict[str, str] = {
    # chat / gateway help
    "chat.help": "I'm the agent '{agent}'. Send me a task.\nEssentials: {ess}\n/commands lists ALL by category.",
    "chat.commands_header": "📜 commands by category:",
    # TUI help table
    "tui.help.title": "Commands",
    "tui.help.col.category": "category",
    "tui.help.col.command": "command",
    "tui.help.col.does": "what it does",
}

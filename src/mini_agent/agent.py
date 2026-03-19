from anthropic.types import MessageParam, ToolUseBlock

from .config import MODEL, WORKDIR, client
from .tools import TOOL_HANDLERS, TOOLS

TOOLS_LIST = "\n".join(f"- {tool['name']}: {tool['description']}" for tool in TOOLS)

SYSTEM = f"""
You are an expert coding assistant at {WORKDIR}. You help users by reading files, executing commands, editing code, and writing new files.

Available tools:
{TOOLS_LIST}
"""


def agent_loop(messages: list[MessageParam]) -> None:
    rounds_since_todo = 0

    while True:
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return

        used_todo = False
        results = []
        for block in response.content:
            if isinstance(block, ToolUseBlock):
                handler = TOOL_HANDLERS.get(block.name)
                output = (
                    handler(**block.input) if handler else f"Unknown tool: {block.name}"
                )
                print(f"> {block.name} - {block.input}\n{output[:200]}\n")
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": output}
                )
                if block.name == "todo":
                    used_todo = True

        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            results.insert(
                0,
                {"type": "text", "text": "<reminder>Update your todos.</reminder>"},
            )

        messages.append({"role": "user", "content": results})

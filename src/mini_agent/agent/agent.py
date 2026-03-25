import anthropic
from anthropic.types import MessageParam, ThinkingBlock, ToolUseBlock

from ..cli.display import print_tool_result
from ..config import WORKDIR, client, get_model
from ..errors import APIKeyMissingError
from .skills import SKILL_LOADER
from .tools import TOOL_HANDLERS, TOOLS

TOOLS_LIST = "\n".join(f"- {tool['name']}: {tool['description']}" for tool in TOOLS)

SYSTEM = f"""
You are an expert coding assistant at {WORKDIR}. You help users by reading files, executing commands, editing code, and writing new files.

Available tools:
{TOOLS_LIST}

Available skills:
{SKILL_LOADER.get_descriptions()}
"""


def agent_loop(messages: list[MessageParam]) -> None:
    rounds_since_todo = 0

    while True:
        try:
            response = client.messages.create(
                model=get_model(),
                system=SYSTEM,
                messages=messages,
                tools=TOOLS,
                max_tokens=8000,
                thinking={"type": "enabled", "budget_tokens": 6000},
            )
        except TypeError as e:
            if "Could not resolve authentication method" in str(e):
                print(f"Error: {APIKeyMissingError()}\n")
            else:
                print(f"Error: {e}\n")
            messages.pop()
            return
        except anthropic.APIStatusError as e:
            print(f"Error: {e}\n")
            messages.pop()
            return
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
                print_tool_result(block.name, block.input, output)
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": output}
                )
                if block.name == "todo":
                    used_todo = True

            if isinstance(block, ThinkingBlock):
                if block.type == "thinking":
                    if block.thinking:
                        print(f"{block.thinking}")
                    else:
                        print("Thinking: [omitted]")

        rounds_since_todo = 0 if used_todo else rounds_since_todo + 1
        if rounds_since_todo >= 3:
            results.insert(
                0,
                {"type": "text", "text": "<reminder>Update your todos.</reminder>"},
            )

        messages.append({"role": "user", "content": results})

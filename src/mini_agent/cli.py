from anthropic.types import MessageParam
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings

from .agent import agent_loop


def build_session() -> PromptSession:
    bindings = KeyBindings()

    @bindings.add("c-c")
    def clear_buffer(event) -> None:
        event.current_buffer.reset()

    @bindings.add("enter")
    def submit(event) -> None:
        event.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def insert_newline(event) -> None:
        event.current_buffer.insert_text("\n")

    return PromptSession(
        HTML('<style color="#87CEEB">> </style>'),
        multiline=True,
        key_bindings=bindings,
    )


def main() -> None:
    history: list[MessageParam] = []
    session = build_session()

    while True:
        try:
            query = session.prompt()
            print()
        except KeyboardInterrupt:
            continue
        except EOFError:
            break

        if query.strip().lower() in {"", "q", "exit"}:
            break

        history.append({"role": "user", "content": query})
        agent_loop(history)

        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(f"> {block.text}\n")

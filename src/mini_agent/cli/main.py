from prompt_toolkit.patch_stdout import patch_stdout

from .display import clear_terminal, print_welcome_banner
from .models import prompt_model
from .prompting import SessionSignal, build_session
from .runtime import BackgroundAgentRunner, ConversationState, new_session_id
from .sessions import prompt_resume


def should_defer_session_command(
    command: str,
    runner: BackgroundAgentRunner,
) -> bool:
    if not runner.is_busy():
        return False

    print(f"Interrupt queued or running work before using {command}.\n")
    return True


def main() -> None:
    print_welcome_banner()
    conversation = ConversationState()
    runner = BackgroundAgentRunner(conversation)
    session, ctrl_c_behavior = build_session(
        agent_running=runner.running_event,
        cancel=runner.cancel_event,
    )
    runner.attach_session(session)
    runner.start()

    try:
        with patch_stdout(raw=True):
            while True:
                try:
                    query = session.prompt()
                    print()
                except KeyboardInterrupt:
                    continue
                except EOFError:
                    break

                if query is SessionSignal.EXIT:
                    break

                command = query.strip().lower()
                if command in {"", "q", "exit"}:
                    break
                if command == "/new":
                    if should_defer_session_command(command, runner):
                        continue

                    conversation.history.clear()
                    conversation.session_id = new_session_id()
                    clear_terminal()
                    continue
                if command == "/resume":
                    if should_defer_session_command(command, runner):
                        continue

                    (
                        conversation.session_id,
                        conversation.history,
                    ) = prompt_resume(
                        conversation.session_id,
                        conversation.history,
                    )
                    continue
                if command == "/model":
                    if should_defer_session_command(command, runner):
                        continue

                    prompt_model()
                    continue

                runner.submit(query)
    finally:
        ctrl_c_behavior.dispose()
        runner.stop()

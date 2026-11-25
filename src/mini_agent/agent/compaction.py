from anthropic.types import MessageParam, TextBlock
from rich.console import Console

from ..cli.models import get_max_context_tokens, get_max_output_tokens
from ..cli.token import Usage, token_tracker
from ..config import config, get_client

_console = Console()

_DEFAULT_OUTPUT_RESERVE = 32768
_SUMMARY_MAX_TOKENS = 16384

_SUMMARY_SYSTEM = (
    "You summarize conversations between a user and a coding agent. "
    "The summary replaces the earlier messages, so it must contain everything "
    "the agent needs to continue the work."
)

_SUMMARY_PROMPT = """\
Create a detailed summary of the conversation so far. Respond with the summary only, using these sections:

1. Primary Request and Intent: what the user asked for, including refinements and constraints.
2. Key Technical Concepts: technologies, patterns, and decisions that matter for the work.
3. Files and Code Sections: files read or modified, why each matters, and the important snippets or signatures.
4. Errors and Fixes: errors encountered, how they were resolved, and any user feedback.
5. Problem Solving: what was investigated and what was concluded.
6. All User Messages: every user message verbatim, excluding tool results.
7. Pending Tasks: work that remains.
8. Current Work: the exact state of the task at the point of summarization.
9. Next Step: the single next step, tied to the most recent user intent.

Be specific: include file paths, function names, commands, and values instead of vague descriptions.
"""

_CONTINUATION = """\
This session is being continued from a previous conversation that ran out of context. The summary below covers the earlier portion of the conversation.

<summary>
{summary}
</summary>

Continue from where the conversation left off without asking the user to repeat themselves.
"""


def _context_tokens(usage: Usage) -> int:
    return usage.total_input_tokens + usage.output_tokens


def should_compact(usage: Usage | None) -> bool:
    if usage is None:
        return False
    limit = get_max_context_tokens(config.get_model())
    if limit is None:
        return False
    output_reserve = (
        get_max_output_tokens(config.get_model()) or _DEFAULT_OUTPUT_RESERVE
    )
    reserve = max(output_reserve, _summary_max_tokens())
    return _context_tokens(usage) + reserve >= limit


def _summary_max_tokens() -> int:
    model = config.get_model()
    budget = _SUMMARY_MAX_TOKENS
    limit = get_max_context_tokens(model)
    if limit is not None:
        budget = min(budget, limit // 4)
    output_limit = get_max_output_tokens(model)
    if output_limit is not None:
        budget = min(budget, output_limit)
    return max(1024, budget)


def compact(
    messages: list[MessageParam], focus: str | None = None
) -> list[MessageParam] | None:
    if not messages:
        return None

    prompt = _SUMMARY_PROMPT
    if focus:
        prompt = f"{prompt}\nFocus especially on: {focus}"

    status = _console.status("Compacting conversation")
    status.start()
    try:
        response = get_client().messages.create(
            model=config.get_model(),
            max_tokens=_summary_max_tokens(),
            system=_SUMMARY_SYSTEM,
            messages=[*messages, {"role": "user", "content": prompt}],
        )
    except Exception as e:
        status.stop()
        _console.print(f"{type(e).__name__}: {e}", style="bold red")
        _console.print()
        return None
    status.stop()

    summary = "".join(
        block.text for block in response.content if isinstance(block, TextBlock)
    ).strip()
    if not summary:
        _console.print("Compaction produced an empty summary.", style="bold red")
        _console.print()
        return None

    token_tracker.begin_new_context_segment()
    return [{"role": "user", "content": _CONTINUATION.format(summary=summary)}]


def auto_compact(messages: list[MessageParam]) -> bool:
    if len(messages) < 2 or not should_compact(token_tracker.get_last_round()):
        return False
    compacted = compact(messages)
    if compacted is None:
        return False
    messages[:] = compacted
    _console.print("Context nearly full: compacted the conversation.", style="yellow")
    return True

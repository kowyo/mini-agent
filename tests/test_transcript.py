from mini_agent.agent.transcript import (
    AssistantMessage,
    ImageBlock,
    TextBlock,
    ThinkingBlock,
    ToolCall,
    ToolResultMessage,
    UserMessage,
    content_to_blocks,
    message_from_dict,
    message_to_dict,
    text_content,
    usage_from_dict,
    usage_to_dict,
)
from mini_agent.cli.token import Usage


def test_message_round_trip_preserves_provider_metadata_and_blocks() -> None:
    message = AssistantMessage(
        content=(
            ThinkingBlock(
                thinking="reasoning",
                signature='{"id":"rs_1","encrypted_content":"secret"}',
            ),
            TextBlock(text="answer", signature='{"id":"msg_1","phase":"final_answer"}'),
            ToolCall(
                id="call_1",
                name="bash",
                arguments={"command": "ls"},
                item_id="fc_1",
                namespace="functions",
            ),
        ),
        provider="openai",
        api_type="response",
        model="gpt-5.4",
        usage=Usage(10, 0, 2, 3),
        stop_reason="tool_use",
        thinking_level="high",
    )

    restored = message_from_dict(message_to_dict(message))

    assert restored == message


def test_tool_result_and_image_round_trip() -> None:
    message = ToolResultMessage(
        tool_call_id="call_1",
        name="read_file",
        content=(
            TextBlock(text="image"),
            ImageBlock(data="aGk=", mime_type="image/png"),
        ),
        is_error=False,
    )

    restored = message_from_dict(message_to_dict(message))

    assert restored == message


def test_user_message_round_trip() -> None:
    message = UserMessage(
        content=(
            TextBlock(text="look"),
            ImageBlock(data="aGk=", mime_type="image/webp"),
        )
    )

    restored = message_from_dict(message_to_dict(message))

    assert restored == message


def test_content_to_blocks_accepts_legacy_dicts() -> None:
    blocks = content_to_blocks(
        [
            {"type": "text", "text": "hello"},
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": "aGk="},
            },
        ]
    )

    assert blocks == (
        TextBlock(text="hello"),
        ImageBlock(data="aGk=", mime_type="image/png"),
    )


def test_text_content_only_reads_text_blocks() -> None:
    assert text_content("plain") == "plain"
    assert (
        text_content(
            (
                TextBlock(text="one"),
                ImageBlock(data="aGk=", mime_type="image/png"),
                TextBlock(text="two"),
            )
        )
        == "one\ntwo"
    )


def test_usage_round_trip() -> None:
    usage = Usage(1, 2, 3, 4)

    assert usage_from_dict(usage_to_dict(usage)) == usage

from ..agent.transcript import ImageBlock, Message, TextBlock, UserMessage
from .clipboard import format_image_indicator


def count_images_in_history(history: list[Message]) -> int:
    image_count = 0
    for message in history:
        if not isinstance(message, UserMessage) or isinstance(message.content, str):
            continue
        image_count += sum(
            1 for block in message.content if isinstance(block, ImageBlock)
        )
    return image_count


def _prune_attached_images(
    query: str,
    attached_images: list[tuple[str, ImageBlock]],
) -> None:
    attached_images[:] = [
        (path, image_block)
        for path, image_block in attached_images
        if format_image_indicator(path) in query
    ]


def build_user_content(
    query: str,
    attached_images: list[tuple[str, ImageBlock]],
    sent_image_count: list[int],
) -> str | tuple[ImageBlock | TextBlock, ...]:
    if attached_images:
        _prune_attached_images(query, attached_images)

    if not attached_images:
        return query

    content: list[ImageBlock | TextBlock] = [
        image_block for _, image_block in attached_images
    ]
    if query.strip():
        content.append(TextBlock(text=query))

    sent_image_count[0] += len(attached_images)
    attached_images.clear()
    return tuple(content)

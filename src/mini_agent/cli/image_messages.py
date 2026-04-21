from anthropic.types import ImageBlockParam, MessageParam, TextBlockParam

from .clipboard import format_image_indicator


def count_images_in_history(history: list[MessageParam]) -> int:
    image_count = 0
    for message in history:
        if message["role"] != "user" or not isinstance(message["content"], list):
            continue
        for block in message["content"]:
            if isinstance(block, dict) and block.get("type") == "image":
                image_count += 1
    return image_count


def prune_attached_images(
    query: str,
    attached_images: list[ImageBlockParam],
    sent_image_count: int,
) -> None:
    attached_images[:] = [
        image_block
        for i, image_block in enumerate(attached_images, start=1)
        if format_image_indicator(sent_image_count + i) in query
    ]


def build_user_content(
    query: str,
    attached_images: list[ImageBlockParam],
    sent_image_count: list[int],
) -> str | list[ImageBlockParam | TextBlockParam]:
    if attached_images:
        prune_attached_images(query, attached_images, sent_image_count[0])

    if not attached_images:
        return query

    content: list[ImageBlockParam | TextBlockParam] = []
    content.extend(attached_images)
    if query.strip():
        text_block: TextBlockParam = {"type": "text", "text": query}
        content.append(text_block)

    sent_image_count[0] += len(attached_images)
    attached_images.clear()
    return content

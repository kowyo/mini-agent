from ..config import Provider, config
from .display.picker import select_from_list


def _format_provider(provider: Provider) -> str:
    return f"{provider.name}  {provider.base_url}"


def prompt_provider() -> None:
    providers = config.get_providers()
    current = config.get_provider()
    provider = select_from_list(
        providers,
        "Select provider",
        _format_provider,
        selected_index=providers.index(current),
        clear_after=True,
    )
    if provider is None:
        return
    config.save_provider(provider.id)
    print(f"Provider set to {provider.name}\n")

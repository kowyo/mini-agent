from ..config import DEFAULT_CHATGPT_MODEL, config


def _notify(verification_uri: str, code: str) -> None:
    print(f"Open {verification_uri} in your browser and enter code: {code}")
    print("Waiting for authorization. Press Ctrl+C to cancel.\n")


def prompt_login() -> None:
    from ..oauth import OAuthError, login

    try:
        login(_notify)
    except KeyboardInterrupt, EOFError:
        print("\nLogin cancelled; provider and model unchanged.\n")
        return
    except OAuthError as e:
        print(f"ChatGPT login failed: {e}; provider and model unchanged.\n")
        return
    except Exception:
        # Unexpected exceptions can contain credentials or response bodies.
        print("ChatGPT login failed; provider and model unchanged. Try /login again.\n")
        return
    try:
        config.save_provider_and_model("chatgpt", DEFAULT_CHATGPT_MODEL)
    except Exception:
        print("Login succeeded, but the provider selection could not be saved.\n")
        return
    print(f"Logged in to ChatGPT. Model set to {DEFAULT_CHATGPT_MODEL}.\n")


def prompt_logout() -> None:
    from ..oauth import logout

    try:
        logout()
    except Exception:
        print("Could not remove mini-agent's local ChatGPT credentials.\n")
        return
    print("Removed mini-agent's local ChatGPT credentials. Other apps are unchanged.\n")

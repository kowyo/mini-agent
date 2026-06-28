from mini_agent.config import Config


def test_get_model() -> None:
    config = Config()
    config.save_model(model_id="deepseek-v4-flash")
    assert config.get_model() == "deepseek-v4-flash"

import importlib


def test_app_import_does_not_connect_to_database():
    module = importlib.import_module("app")
    assert callable(module.build_demo)


def test_app_contains_hybrid_search_and_agent_tabs():
    module = importlib.import_module("app")
    config = module.build_demo(repository=object()).get_config_file()
    labels = {component.get("props", {}).get("label") for component in config["components"]}
    assert "하이브리드 검색" in labels
    assert "CRM SQL 에이전트" in labels

"""Import-only smoke tests — verify module wiring without touching DB or network."""
import importlib


def test_cli_imports():
    mod = importlib.import_module("src.__main__")
    assert hasattr(mod, "cli")


def test_connectors_import():
    importlib.import_module("src.connectors.gleif")
    importlib.import_module("src.connectors.sec_edgar")
    importlib.import_module("src.connectors.un_comtrade")


def test_normalizers_import():
    importlib.import_module("src.normalize.gleif")
    importlib.import_module("src.normalize.sec_edgar")


def test_stubs_import():
    for name in ("companies_house", "opencorporates", "egrul_ru",
                 "egov_kz", "wikidata", "opensanctions"):
        importlib.import_module(f"src.stubs.{name}")

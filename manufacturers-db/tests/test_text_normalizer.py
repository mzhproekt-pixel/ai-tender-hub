from src.normalize.text import normalize_country, normalize_name


def test_strips_legal_form_suffix():
    assert normalize_name("Acme Robotics, Inc.") == "acme robotics"
    assert normalize_name("Acme Robotics LLC") == "acme robotics"


def test_cyrillic_transliterated_and_folded():
    # Same company spelled in Cyrillic and Latin should produce the same key.
    assert normalize_name("ООО \"Газпром\"") == normalize_name("Gazprom LLC")


def test_unicode_folds_to_ascii():
    # NFKD decomposes accents and ligatures; '№' decomposes to 'No'.
    assert normalize_name("Café Müller № 1") == "cafe muller no 1"


def test_handles_none_and_empty():
    assert normalize_name(None) == ""
    assert normalize_name("") == ""
    assert normalize_name("   ") == ""


def test_kazakh_letters_normalised():
    # Cyrillic Kazakh-specific letters (Ә, Қ, Ң, Ө, Ұ, Ү, Һ, І) handled.
    assert normalize_name("Қазақстан Темір Жолы") == "kazakstan temir zholy"


def test_normalize_country():
    assert normalize_country("us") == "US"
    assert normalize_country("USA") is None  # not 2-letter
    assert normalize_country(None) is None
    assert normalize_country("  De ") == "DE"

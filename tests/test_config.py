from src.config import extract_config_block, load_config, parse_simple_yaml

PREFS = '''# Tercihler

Some text with ```yaml``` mention.

```yaml
# name: config
search_queries:
  - ".net developer"
  - 'c# developer'   # trailing comment
exclude_title_keywords:
  - "java"        # whole-word only
  - "jr "
  - junior
min_score_notify: 55
min_score_cover_letter: 75
note: "has # inside"
```
'''


def test_parse_simple_yaml():
    data = parse_simple_yaml(extract_config_block(PREFS))
    assert data["search_queries"] == [".net developer", "c# developer"]
    assert data["exclude_title_keywords"] == ["java", "jr ", "junior"]
    assert data["min_score_notify"] == 55
    assert data["note"] == "has # inside"


def test_load_config_from_prefs_and_env(tmp_path):
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "preferences.md").write_text(PREFS, encoding="utf-8")
    cfg = load_config(root=tmp_path, env={
        "GROQ_API_KEY": "g", "AI_PROVIDERS": "Gemini, groq", "TELEGRAM_ENABLED": "TRUE",
    })
    assert cfg.min_score_notify == 55 and cfg.min_score_cover_letter == 75
    assert cfg.exclude_title_keywords[0] == "java"
    assert cfg.max_age_days == 1  # default kept
    assert cfg.ai_providers == ["gemini", "groq"]
    assert cfg.groq_api_key == "g" and cfg.groq_model == "llama-3.1-8b-instant"
    assert cfg.groq_model_strong == "llama-3.3-70b-versatile"
    assert cfg.telegram_enabled is True
    assert cfg.extra == {"note": "has # inside"}
    assert cfg.db_path == tmp_path / "data" / "jobs.db"


def test_defaults_when_file_or_block_missing(tmp_path):
    cfg = load_config(root=tmp_path, env={})
    assert cfg.min_score_notify == 50 and cfg.min_score_cover_letter == 70
    assert "java" in cfg.exclude_title_keywords
    assert cfg.ai_providers == ["groq", "gemini"] and cfg.telegram_enabled is False

    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "preferences.md").write_text("# no block here\n", encoding="utf-8")
    assert load_config(root=tmp_path, env={}).min_score_notify == 50


def test_bad_int_keeps_default(tmp_path):
    (tmp_path / "p.md").write_text("```yaml\nmin_score_notify: lots\n```\n", encoding="utf-8")
    assert load_config(root=tmp_path, env={}, prefs_path=tmp_path / "p.md").min_score_notify == 50


def test_real_preferences_file_parses():
    """The Analyst's real profile/preferences.md (if present) must yield a usable config."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    cfg = load_config(root=root, env={})
    assert isinstance(cfg.min_score_notify, int)
    assert all(isinstance(k, str) for k in cfg.exclude_title_keywords)


def test_cv_from_env_overrides_file(tmp_path):
    import base64
    (tmp_path / "profile").mkdir()
    (tmp_path / "profile" / "cv.md").write_text("FILE CV", encoding="utf-8")
    assert load_config(root=tmp_path, env={}).read_cv() == "FILE CV"
    assert load_config(root=tmp_path, env={"CV_MD": "ENV CV"}).read_cv() == "ENV CV"
    b64 = base64.b64encode("Çağrı CV".encode()).decode()
    assert load_config(root=tmp_path, env={"CV_MD_B64": b64}).read_cv() == "Çağrı CV"
    assert load_config(root=tmp_path, env={"CV_MD_B64": "%%%bad"}).read_cv() == "FILE CV"
    assert load_config(root=tmp_path / "nope", env={}).read_cv() == ""

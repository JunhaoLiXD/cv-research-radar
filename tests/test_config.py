from pathlib import Path

import pytest

from cv_radar.config import load_project_config


ROOT = Path(__file__).resolve().parents[1]


def test_load_default_config() -> None:
    config = load_project_config(ROOT / "config")

    assert config.sources.arxiv.categories == ["cs.CV", "eess.IV"]
    assert "cell tracking" in config.interests.high_priority
    assert config.interests.daily_max_recommendations == 15
    assert config.ranking.weights.relevance == 0.35


def test_invalid_weight_total_is_rejected(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "interests.yaml").write_text(
        "high_priority: [vision]\nmedium_priority: []\nexploration: []\n",
        encoding="utf-8",
    )
    (config_dir / "sources.yaml").write_text("{}\n", encoding="utf-8")
    (config_dir / "ranking.yaml").write_text(
        "weights:\n  relevance: 0.9\n  novelty: 0.9\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="sum to 1.0"):
        load_project_config(config_dir)

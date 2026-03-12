from __future__ import annotations

from pathlib import Path

from podcast_anything_local.storage.artifacts import LocalArtifactStore


def test_write_text_replaces_unpaired_surrogates_and_preserves_valid_unicode(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "jobs")

    artifact_path = store.write_text(
        "job-123",
        "source.txt",
        "bad surrogate: \ud83c and valid emoji: 😀",
    )

    written = Path(artifact_path).read_text(encoding="utf-8")

    assert written == "bad surrogate: � and valid emoji: 😀"

from pathlib import Path

from fastapi.testclient import TestClient


def test_files_browses_one_level_read_only(
    authenticated: tuple[TestClient, str], tmp_path: Path
) -> None:
    client, _ = authenticated
    root = tmp_path / "docs"
    (root / "a.txt").write_text("a")
    (root / "sub").mkdir()
    (root / "sub" / "deep.txt").write_text("deep")
    response = client.get("/files")
    assert response.status_code == 200
    assert [item["name"] for item in response.json()["items"]] == ["a.txt", "sub"]


def test_files_rejects_traversal(authenticated: tuple[TestClient, str]) -> None:
    client, _ = authenticated
    response = client.get("/files", params={"path": "../"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "path_outside_root"

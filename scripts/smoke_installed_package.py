"""Exercise the installed wheel without importing application code from a checkout."""

from contextlib import chdir
from importlib.metadata import distribution
import os
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> None:
    installed = distribution("recallops")
    assert installed.metadata["License-Expression"] == "MIT"
    assert installed.metadata.get_payload().strip(), "Package description is missing"
    packaged_files = {str(path) for path in installed.files or []}
    assert "app/static/index.html" in packaged_files, "Operator console is not packaged"
    assert any(path.endswith("/licenses/LICENSE") for path in packaged_files)

    import app as package

    expected_package = Path(installed.locate_file("app")).resolve()
    assert Path(package.__file__).resolve().parent == expected_package, (
        "Application was not imported from the installed distribution"
    )

    with TemporaryDirectory(prefix="recallops-wheel-smoke-") as directory, chdir(directory):
        os.environ.update(
            DATABASE_URL=f"sqlite:///{(Path(directory) / 'smoke.db').as_posix()}",
            USE_BEDROCK="false",
            REQUIRE_COCKROACHDB="false",
            USE_COCKROACH_MCP="false",
            COMPETITION_MODE="false",
            API_KEY="",
            AWS_EC2_METADATA_DISABLED="true",
        )

        from fastapi.testclient import TestClient
        from app.main import app, engine

        try:
            with TestClient(app) as client:
                console = client.get("/")
                assert console.status_code == 200
                assert "RecallOps" in console.text
                assert client.get("/health").json()["status"] == "ok"
                assert client.get("/ready").json()["status"] == "ready"
                assert client.get("/system").json()["database"] == "sqlite-local"

                incident = {
                    "title": "Checkout connection saturation",
                    "service": "wheel-smoke",
                    "symptoms": "Checkout requests time out after database connection saturation",
                }
                prior = client.post("/incidents", json=incident)
                assert prior.status_code == 201
                prior_id = prior.json()["id"]
                resolved = client.post(
                    f"/incidents/{prior_id}/resolve",
                    json={
                        "resolution": "Reduced worker concurrency",
                        "outcome": "Database utilization returned to baseline",
                    },
                )
                assert resolved.status_code == 200
                current = client.post("/incidents", json=incident)
                assert current.status_code == 201
                response = client.post(f"/incidents/{current.json()['id']}/investigate")
                assert response.status_code == 200
                result = response.json()
                assert result["provider"] == "local-retrieval"
                recommendation = result["recommendations"][0]
                assert recommendation["incident_id"] == prior_id
                assert {item["kind"] for item in recommendation["evidence"]} == {
                    "symptoms", "resolution", "outcome"
                }
        finally:
            engine.dispose()

    print(f"Installed RecallOps {installed.version} passed the offline wheel smoke test.")


if __name__ == "__main__":
    main()

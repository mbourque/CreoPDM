"""Add shows "Packing N of M" while the agent zips picked files (before the upload starts)."""

import logging
from pathlib import Path

from fastapi.testclient import TestClient

from creopdm.services.zip_import_jobs import ZipImportJobs
from creopdm_agent.config import AgentConfig
from creopdm_agent.server import _PackingProgress, create_agent_app
from tests.conftest import requires_git

ROOT = Path(__file__).resolve().parents[2]


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_packing_progress_posts_start_then_throttled_ticks_then_final(caplog):
    posts: list[tuple[str, dict, dict]] = []
    clock = _Clock()
    progress = _PackingProgress(
        total=300,
        report_url="http://pdm.test/api/products/p/zip-import/jobs/j/progress",
        headers={"Authorization": "Bearer token"},
        clock=clock,
        post=lambda url, body, headers: posts.append((url, body, headers)),
    )
    progress.start()
    # Regression: the overlay sat on "Starting compressed import…" until packing ended.
    assert posts[-1][1] == {"files_done": 0, "files_total": 300, "bytes_done": 0}
    assert posts[-1][2] == {"Authorization": "Bearer token"}
    for done in range(1, 50):
        progress.tick(done, done * 1000)
    assert len(posts) == 1  # same second: throttled
    clock.now = 1.5
    progress.tick(50, 50_000_000)
    assert posts[-1][1] == {"files_done": 50, "files_total": 300, "bytes_done": 50_000_000}
    with caplog.at_level(logging.INFO, logger="creopdm_agent"):
        for done in range(51, 301):
            clock.now += 0.01
            progress.tick(done, done * 1_000_000)
        progress.finish(300, 300_000_000)
    lines = [record.getMessage() for record in caplog.records]
    assert any("packed 100 of 300 files" in line for line in lines)
    assert any("packed 200 of 300 files" in line for line in lines)
    assert any("packed 300 of 300 files" in line and "packing done" in line for line in lines)
    assert posts[-1][1]["files_done"] == 300


def test_agent_log_and_overlay_use_the_same_megabytes():
    from creopdm.services.zip_import_jobs import _format_bytes
    from creopdm_agent.server import _format_megabytes

    # 534 MB in the overlay must also read 534 MB in the agent log.
    assert _format_bytes(559_600_000) == "534 MB"
    assert _format_megabytes(559_600_000) == "534 MB"


def test_packing_progress_without_a_job_only_logs(caplog):
    posts: list = []
    progress = _PackingProgress(
        total=3, report_url="", post=lambda *args: posts.append(args), clock=_Clock()
    )
    with caplog.at_level(logging.INFO, logger="creopdm_agent"):
        progress.start()
        progress.tick(1, 10)
        progress.finish(3, 30)
    assert posts == []
    assert any("starting to pack 3 file(s)" in record.getMessage() for record in caplog.records)


def test_packing_progress_post_failure_never_raises(caplog):
    def boom(*_args):
        raise OSError("CreoPDM unreachable")

    clock = _Clock()
    progress = _PackingProgress(total=2, report_url="http://pdm.test/x", post=boom, clock=clock)
    with caplog.at_level(logging.WARNING, logger="creopdm_agent"):
        progress.start()
        clock.now = 5.0
        progress.tick(1, 1)
        progress.finish(2, 2)
    warnings = [r for r in caplog.records if "not reported" in r.getMessage()]
    assert len(warnings) == 1  # warned once, never stops the Add


def test_add_paths_zip_reports_packing_progress_to_the_job(tmp_path, monkeypatch):
    settings = AgentConfig(host="127.0.0.1", port=8766, local_root=str(tmp_path / "cache"))
    app = create_agent_app(settings)
    source = tmp_path / "src"
    source.mkdir()
    paths = []
    for index in range(55):  # >= ADD_PATHS_ZIP_MIN_FILES → pack + from-zip
        part = source / f"part{index:03d}.prt"
        part.write_bytes(b"x" * 10)
        paths.append(str(part))
    posted: list[tuple[str, dict | None]] = []

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self):
            return {"ok": [], "failed": []}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def close(self):
            pass

        def post(self, url, headers=None, json=None, data=None, files=None):
            posted.append((url, json))
            return FakeResponse()

    monkeypatch.setattr("creopdm_agent.server.httpx.Client", FakeClient)
    with TestClient(app) as client:
        response = client.post(
            "/add-paths",
            json={
                "pdm_url": "http://pdm.test",
                "product_id": "prod-1",
                "absolute_paths": paths,
                "job_id": "job-1",
                "client_total": 55,
            },
        )
    assert response.status_code == 200, response.text
    progress = [
        body
        for url, body in posted
        if url == "http://pdm.test/api/products/prod-1/zip-import/jobs/job-1/progress"
    ]
    assert progress, posted
    assert progress[0] == {"files_done": 0, "files_total": 55, "bytes_done": 0}
    assert progress[-1] == {"files_done": 55, "files_total": 55, "bytes_done": 550}
    # The zip upload still happens after packing.
    assert any(url.endswith("/api/products/prod-1/objects/from-zip") for url, _ in posted)


def test_job_set_packing_message_and_never_overrides_a_later_phase():
    jobs = ZipImportJobs()
    job = jobs.create("prod-1")
    assert job.message == "Starting compressed import…"
    jobs.set_packing(job.job_id, files_done=0, files_total=936)
    assert jobs.get(job.job_id).message == "Packing files on this PC… 0 of 936"
    jobs.set_packing(job.job_id, files_done=655, files_total=936, bytes_done=559_600_000)
    packed = jobs.get(job.job_id)
    # Same binary units as the upload text (1 MB = 1024 * 1024 bytes).
    assert packed.message == "Packing files on this PC… 655 of 936 (534 MB)"
    assert (packed.phase, packed.state, packed.done) == ("packing", "packing", False)
    assert (packed.files_done, packed.files_total) == (655, 936)
    jobs.set_uploading(job.job_id, bytes_done=1, bytes_total=10)
    # A late progress post after the upload started must not move the text backwards.
    jobs.set_packing(job.job_id, files_done=900, files_total=936)
    assert jobs.get(job.job_id).phase == "uploading"
    assert jobs.get(job.job_id).message.startswith("Uploading zip")


@requires_git
def test_progress_endpoint_updates_the_job_the_overlay_polls(client):
    product = client.post("/api/products", json={"name": "Pack Arm"}).json()
    job = client.post(f"/api/products/{product['uuid']}/zip-import/jobs").json()
    posted = client.post(
        f"/api/products/{product['uuid']}/zip-import/jobs/{job['job_id']}/progress",
        json={"files_done": 12, "files_total": 936, "bytes_done": 5_000_000},
    )
    assert posted.status_code == 200, posted.text
    polled = client.get(f"/api/products/{product['uuid']}/zip-import/jobs/{job['job_id']}")
    body = polled.json()
    assert body["message"] == "Packing files on this PC… 12 of 936 (4.8 MB)"
    assert body["phase"] == "packing"
    assert body["done"] is False


@requires_git
def test_progress_endpoint_rejects_unknown_job_and_other_products_job(client):
    first = client.post("/api/products", json={"name": "Pack One"}).json()
    second = client.post("/api/products", json={"name": "Pack Two"}).json()
    job = client.post(f"/api/products/{first['uuid']}/zip-import/jobs").json()
    body = {"files_done": 1, "files_total": 2}
    unknown = client.post(
        f"/api/products/{first['uuid']}/zip-import/jobs/not-a-job/progress", json=body
    )
    assert unknown.status_code == 400, unknown.text
    other = client.post(
        f"/api/products/{second['uuid']}/zip-import/jobs/{job['job_id']}/progress", json=body
    )
    assert other.status_code == 400, other.text


def test_add_flow_still_polls_the_job_message_for_the_overlay():
    js = (ROOT / "src" / "creopdm" / "static" / "js" / "add.js").read_text(encoding="utf-8")
    poll = js.split("async function pollZipImportJob(", 1)[1].split("onPage(compressedForm", 1)[0]
    assert "if (message) setBusyMessage(message)" in poll
    # Large Adds pass the job to the agent so its packing progress reaches that poll.
    assert "postAddPaths(list, 0, jobId ? { job_id: jobId } : {})" in js

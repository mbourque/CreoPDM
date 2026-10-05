"""Compressed data… zip import progress jobs."""

from __future__ import annotations

from creopdm.services.zip_import_jobs import ZipImportJobs


def test_zip_import_job_phase_messages():
    jobs = ZipImportJobs()
    status = jobs.create("product-1")
    job_id = status.job_id
    assert status.state == "queued"
    assert "Starting" in status.message

    jobs.set_uploading(job_id, bytes_done=100 * 1024 * 1024, bytes_total=905 * 1024 * 1024)
    uploading = jobs.get(job_id)
    assert uploading is not None
    assert uploading.phase == "uploading"
    assert "Uploading zip…" in uploading.message
    assert "MB" in uploading.message

    jobs.set_extracting(job_id)
    assert jobs.get(job_id).message == "Extracting zip…"

    jobs.set_importing(job_id, files_done=3900, files_total=4024)
    assert jobs.get(job_id).message == "Importing files… 3900 of 4024"

    jobs.set_committing(job_id, files_total=4024)
    assert "Committing" in jobs.get(job_id).message

    jobs.set_recording(job_id, files_done=0, files_total=4024)
    assert "database" in jobs.get(job_id).message.lower()
    jobs.set_recording(job_id, files_done=100, files_total=4024)
    assert jobs.get(job_id).message == "Finishing vault files… 100 of 4024"

    jobs.set_done(job_id, files_total=4024)
    done = jobs.get(job_id)
    assert done.done is True
    assert done.state == "done"


def test_zip_import_job_error():
    jobs = ZipImportJobs()
    job_id = jobs.create("product-1").job_id
    jobs.set_error(job_id, "Disk full")
    status = jobs.get(job_id)
    assert status.state == "error"
    assert status.done is True
    assert status.error == "Disk full"

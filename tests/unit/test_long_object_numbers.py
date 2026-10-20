"""A long file name (SolidWorks part names, copied PDM names) must not make Add fail."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from creopdm.app import build_context, create_app
from creopdm.config import ConfigManager
from creopdm.models.object import EngineeringObject
from tests.conftest import requires_git
from tests.unit.test_baselines import _signed_in_admin


@pytest.fixture()
def auth_ctx(data_dir):
    return build_context(ConfigManager())


@pytest.fixture()
def auth_client(auth_ctx):
    with TestClient(create_app(auth_ctx)) as client:
        yield client


def test_object_number_column_holds_a_whole_file_name():
    assert EngineeringObject.__table__.c.number.type.length == 255


@requires_git
def test_adding_files_with_long_names_works_and_keeps_the_whole_number(auth_client, auth_ctx):
    _signed_in_admin(auth_client, auth_ctx)
    product = auth_client.post("/api/products", json={"name": "Long names"}).json()
    names = [
        "WINDCHILL-509 Square Head Pipe Plug 0.5in. Mcmaster PN4464K234.SLDPRT",
        "WINDCHILL-509 Square Head Pipe Plug 0.5in. Mcmaster PN4464K234.SLDPRT.creo",
        ("x" * 120) + ".prt",
    ]
    for name in names:
        added = auth_client.post(
            f"/api/products/{product['uuid']}/objects",
            files={"file": (name, b"bytes", "application/octet-stream")},
            data={"comment": "long"},
        )
        assert added.status_code == 201, (name, added.text)
    with auth_ctx.session_factory() as db:
        numbers = {o.filename: o.number for o in db.scalars(select(EngineeringObject))}
    assert len(numbers) == 3
    assert any(len(n) > 64 for n in numbers.values())
    for filename, number in numbers.items():
        assert number == Path(filename).stem.upper(), filename  # the whole name, never cut short

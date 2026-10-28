"""OCR 執行次數包含局部重辨識，發布後仍須原值讀回。"""

from copy import deepcopy
from io import BytesIO
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from product_fixtures import (
    ORIGIN, _app, closed_loop, publish_fixture_structure, seed_pdf, seed_run,
)
from runtime import material_processing as processing
from runtime.storage.database import database_session
from runtime.storage.tables import MaterialProcessingRun
from test_material_pipeline_v1 import Client, _request, _settings




@pytest.mark.parametrize("count", [0, 2, -1, True, 1.5, "2"])
def test_completed_run_accepts_only_nonnegative_integer_ocr_counts(closed_loop, count):
    learner, _, _, document, dsn, _ = closed_loop
    with database_session(dsn) as db:
        row = db.get(MaterialProcessingRun, UUID(document["run_id"]))
        row.output_binding = {**deepcopy(row.output_binding), "ocr_calls": count}
        if type(count) is int and count >= 0:
            assert processing._row(row).output_binding["ocr_calls"] == count
        else:
            with pytest.raises(processing.MaterialProcessingError, match="^MATERIAL_RUN_INVALID$"):
                processing._row(row)
        db.rollback()

import hashlib
from pathlib import Path

import pymupdf
import pytest

from knowledge_map.structure import (
    SemanticState, apply_semantic_response, build_document_context,
    build_semantic_bundles, semantic_request, semantic_response_schema,
)
from pdf_evidence.ocr_page_evidence import (
    _native_text_blocks,
    build_native_page_evidence,
    extract_page,
    route_page,
)


def test_wrapped_statement_crosses_pdf_blocks_but_not_columns_or_new_items():
    """PDF 物件邊界不等於句界；跨欄與新條列不能被拼成同一陳述。"""
    def block(text, x, y):
        return {"type": 0, "lines": [{"bbox": [x, y, x + 180, y + 15],
                                     "spans": [{"text": text, "size": 12}]}]}
    page = {"geometry": {"unrotated_points": [0, 0, 612, 792]},
            "native_evidence": {"raw_text": {"blocks": [
                block("The sensor returns", 72, 100),
                block("three samples.", 84, 119),
                block("• The interval is 17 ms.", 72, 138),
                block("Left column", 72, 180),
                block("Right column", 330, 180),
            ]}}}
    texts = [b["text"] for b in _native_text_blocks(page)]
    assert texts == ["The sensor returns\nthree samples.", "• The interval is 17 ms.",
                     "Left column", "Right column"]


def test_formal_definition_keeps_indented_body_and_separates_next_definition():
    """定義分隔符與縮排共同定界，不依函式名稱或 PDF 物件邊界切句。"""
    def line(text, x, y):
        return {"bbox": [x, y, x + 220, y + 15], "spans": [{"text": text, "size": 12}]}
    page = {"geometry": {"unrotated_points": [0, 0, 612, 792]},
            "native_evidence": {"raw_text": {"blocks": [
                {"type": 0, "lines": [line("For any buffer", 72, 100), line("Buffer Allocate(limit) ::=", 72, 119)]},
                {"type": 0, "lines": [line("create an empty buffer", 144, 138), line("Boolean Available(buffer) ::=", 72, 157)]},
                {"type": 0, "lines": [line("if buffer has room", 144, 176), line("return TRUE", 144, 195), line("Boolean Ready(buffer) ::= TRUE", 72, 214)]},
            ]}}}
    assert [b["text"] for b in _native_text_blocks(page)] == [
        "For any buffer",
        "Buffer Allocate(limit) ::=\ncreate an empty buffer",
        "Boolean Available(buffer) ::=\nif buffer has room\nreturn TRUE",
        "Boolean Ready(buffer) ::= TRUE",
    ]


def _pdf(path: Path, *, rotated=False):
    document = pymupdf.open()
    page = document.new_page(width=144, height=216)
    page.insert_text((18, 30), "Public native text")
    if rotated:
        page.set_rotation(90)
    document.save(path)
    document.close()


def _extract(path: Path):
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    with pymupdf.open(path) as document:
        return extract_page(document, source_sha256, 1)


def test_native_text_routes_without_ocr_and_keeps_pdf_bbox_order(tmp_path):
    path = tmp_path / "native.pdf"
    _pdf(path)
    page = _extract(path)
    assert route_page(page) == "native_sufficient"
    artifact = build_native_page_evidence(
        page,
        input_binding={"route": "native_sufficient"},
        produced_at="x",
    )
    assert artifact["route"] == "native_sufficient"
    assert artifact["evidence_blocks"][0]["source"] == "native_text"
    assert artifact["evidence_blocks"][0]["reading_order"] == 0
    assert artifact["evidence_blocks"][0]["locator"]["page"] == 1


def test_non_centered_native_heading_starts_stable_following_page_section(
    tmp_path,
):
    path = tmp_path / "native-heading.pdf"
    document = pymupdf.open()
    first = document.new_page(width=612, height=792)
    first.insert_text((72, 72), "Public Learning Objective", fontsize=20)
    first.insert_text(
        (72, 120),
        "This ordinary body sentence provides enough native text for routing.",
        fontsize=12,
    )
    second = document.new_page(width=612, height=792)
    second.insert_text(
        (72, 90),
        "The following page continues the same public learning section.",
        fontsize=12,
    )
    document.save(path)
    document.close()
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    with pymupdf.open(path) as document:
        pages = [
            extract_page(document, source_sha256, page_number)
            for page_number in (1, 2)
        ]
    assert [route_page(page) for page in pages] == [
        "native_sufficient",
        "native_sufficient",
    ]
    artifacts = [
        build_native_page_evidence(
            page,
            input_binding={"route": "native_sufficient"},
            produced_at="2026-08-29T00:00:00Z",
        )
        for page in pages
    ]

    assert [
        block["kind"] for block in artifacts[0]["evidence_blocks"]
    ] == ["heading", "paragraph"]
    assert [
        block["reading_order"] for block in artifacts[0]["evidence_blocks"]
    ] == [0, 1]
    assert all(
        block["block_id"] == block["locator"]["block_id"]
        and block["locator"]["page"] == 1
        for block in artifacts[0]["evidence_blocks"]
    )
    replay = build_native_page_evidence(
        pages[0],
        input_binding={"route": "native_sufficient"},
        produced_at="2026-08-29T00:00:00Z",
    )
    assert replay == artifacts[0]

    context = build_document_context(artifacts, page_count=2)
    heading_evidence_id = artifacts[0]["evidence_blocks"][0]["evidence_id"]
    assert len(context["sections"]) == 1
    assert context["sections"][0]["heading_evidence_id"] == heading_evidence_id
    assert {item["section_id"] for item in context["evidence"]} == {
        context["sections"][0]["section_id"]
    }


def test_native_body_and_small_emphasis_do_not_become_headings(tmp_path):
    path = tmp_path / "native-emphasis.pdf"
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text(
        (72, 72),
        "Ordinary body text establishes the dominant public font size.",
        fontsize=12,
    )
    page.insert_text(
        (72, 105),
        "Important emphasized phrase",
        fontsize=13,
        fontname="hebo",
    )
    page.insert_text(
        (72, 138),
        "Another ordinary sentence confirms this is body content.",
        fontsize=12,
    )
    document.save(path)
    document.close()

    extracted = _extract(path)
    assert route_page(extracted) == "native_sufficient"
    artifact = build_native_page_evidence(
        extracted,
        input_binding={"route": "native_sufficient"},
        produced_at="x",
    )

    assert all(
        block["kind"] == "paragraph"
        for block in artifact["evidence_blocks"]
    )


def test_empty_and_garbled_native_text_is_unavailable(tmp_path):
    path = tmp_path / "scan.pdf"
    document = pymupdf.open()
    document.new_page(width=144, height=216)
    document.save(path)
    document.close()
    assert route_page(_extract(path)) == "native_unavailable"

    page = _extract(path)
    page["native_evidence"]["raw_text"] = {
        "blocks": [{"type": 0, "lines": [{"bbox": [1, 1, 20, 20], "spans": [{"text": "��������"}]}]}]
    }
    assert route_page(page) == "native_unavailable"


def test_running_metadata_is_preserved_but_not_a_claim_source(tmp_path):
    """頁尾先寫入 PDF 也不能成為 Claim；正文、頁底程式及固定數值保留。"""
    path = tmp_path / "public-layout.pdf"
    document = pymupdf.open()
    for number in range(1, 4):
        page = document.new_page(width=612, height=792)
        page.insert_text((300, 782), str(number), fontsize=8)
        page.insert_text((400, 782), "Publisher Copyright 2025", fontsize=8)
        page.insert_text((72, 70), "Sensors", fontsize=22)
        page.insert_text((72, 120), "A sensor sends readings\nto the controller.", fontsize=12)
        page.insert_text((72, 210), "Copyright protects this text.", fontsize=12)
        page.insert_text((72, 745), "int capacity[17];", fontsize=12)
        page.insert_text((300, 745), 'char label[] = "Copyright 2025";', fontsize=8)
        page.insert_text((72, 765), "42", fontsize=12)
    document.save(path)
    document.close()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with pymupdf.open(path) as document:
        pages = [build_native_page_evidence(
            extract_page(document, sha, n), input_binding={}, produced_at="x",
        ) for n in range(1, 4)]
    context = build_document_context(pages, page_count=3)
    state = SemanticState()
    bundle = next(build_semantic_bundles(context, state=state, fits=lambda _: True))
    request = semantic_request(context, bundle, state)
    rows = [row for section in request["sections"] for row in section["evidence"]]
    assert any("Publisher Copyright" in e["exact_text"] for e in context["evidence"])
    assert all("Publisher Copyright" not in row[3] for row in rows)
    assert not any(row[3] in {"1", "2", "3"} for row in rows)
    assert any(row[3] == "A sensor sends readings\nto the controller." for row in rows)
    assert any(row[3] == "Copyright protects this text." for row in rows)
    assert any(row[3] == "int capacity[17];" for row in rows)
    assert any(row[3] == 'char label[] = "Copyright 2025";' for row in rows)
    assert any(row[3] == "42" for row in rows)
    allowed = semantic_response_schema([row[0] for row in rows])["properties"]["concepts"]["items"]["properties"]["c"]["items"]["properties"]["s"]["items"]["enum"]
    footer = next(i for i, e in enumerate(context["evidence"]) if "Publisher Copyright" in e["exact_text"])
    body = next(row[0] for row in rows if row[3].startswith("A sensor sends"))
    assert footer not in allowed
    assert context["evidence"][body]["exact_text"].startswith("A sensor sends")
    apply_semantic_response({"concepts": [{"k": "sensor", "l": "Sensor", "a": [], "c": [
        {"m": "A sensor sends readings to a controller.", "s": [footer]},
        {"m": None, "s": [footer]},
        {"m": None, "s": [body]},
    ]}], "relations": []}, context=context, bundle=bundle, state=state)
    assert state.rejected_claims == 2
    assert len(state.concepts["sensor"]["claims"]) == 1
    assert "controller" in state.concepts["sensor"]["claims"][0]["text"]


def test_render_guard_rejects_geometry_before_page_content_or_pixmap_reads():
    class OversizedPage:
        number = 0
        rotation = 0
        rect = pymupdf.Rect(0, 0, 20_000, 20_000)

        def get_text(self, *_args, **_kwargs):
            raise AssertionError("page content must not be read")

        def get_pixmap(self, *_args, **_kwargs):
            raise AssertionError("pixmap must not be rendered")

    class Document:
        def load_page(self, _index):
            return OversizedPage()

    with pytest.raises(ValueError, match="PROTOCOL_LIMIT_EXCEEDED"):
        extract_page(Document(), "0" * 64, 1)


def test_small_logo_does_not_trigger_ocr(tmp_path):
    path = tmp_path / "logo.pdf"
    _pdf(path)
    page = _extract(path)
    page["images"] = [{"bbox": [130, 0, 140, 10]}]
    assert route_page(page) == "native_sufficient"

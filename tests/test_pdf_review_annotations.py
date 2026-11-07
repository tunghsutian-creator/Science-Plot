"""PDF markings remain local reference facts, separate from scientific commands."""

from hashlib import sha256
import json

import pymupdf
import pytest

from sciplot_core.visual_review.pdf_annotations import inspect_pdf_annotations


def marked_pdf():
    with pymupdf.open() as document:
        page = document.new_page(width=300, height=400)
        page.insert_text((20, 20), "Original measurements: 1.25, 2.5, 3.75")
        note = page.add_text_annot((25, 35), "Increase tick labels to 9 pt; preserve all original values.")
        note.set_info(title="Reviewer", subject="Typography")
        arrow = page.add_line_annot((35.25, 85.5), (150.5, 95.25))
        arrow.set_line_ends(pymupdf.PDF_ANNOT_LE_NONE, pymupdf.PDF_ANNOT_LE_CLOSED_ARROW)
        page.add_rect_annot((30, 120, 150, 150))
        page.add_highlight_annot((30, 180, 150, 210))
        page.add_ink_annot([[(20.25, 240), (80.5, 250.25), (140, 240.5)],
                           [(165, 245), (185.5, 260)]])
        page.add_freetext_annot((30, 280, 220, 310), "Move legend upward")
        return document.tobytes()


def test_reads_actual_note_freetext_arrow_square_highlight_and_ink_without_changing_bytes():
    data = marked_pdf()
    original = bytes(data)
    result = inspect_pdf_annotations(data)
    assert data == original and result["sha256"] == sha256(original).hexdigest()
    assert result["size_bytes"] == len(original) and result["annotation_count"] == 6
    page = result["pages"][0]
    assert page["page_index"] == 0 and page["rect_pt"] == [0.0, 0.0, 300.0, 400.0]
    assert page["media_box_pt"] == page["crop_box_pt"] == page["rect_pt"]
    assert page["rotation"] == 0 and page["pdf_annots_entry_type"] == "array"
    annotations = {annotation["type_name"]: annotation for annotation in page["annotations"]}
    assert set(annotations) == {"Text", "FreeText", "Line", "Square", "Highlight", "Ink"}
    assert annotations["Text"]["info"]["content"] == "Increase tick labels to 9 pt; preserve all original values."
    assert annotations["Text"]["info"]["title"] == "Reviewer"
    assert annotations["Text"]["info"]["subject"] == "Typography"
    assert annotations["FreeText"]["info"]["content"] == "Move legend upward"
    assert annotations["Line"]["vertices_pt"] == [[35.25, 85.5], [150.5, 95.25]]
    assert annotations["Line"]["line_ends"] == [0, 5]
    assert annotations["Highlight"]["vertices_pt"] == [[30.0, 180.0], [150.0, 180.0],
                                                        [30.0, 210.0], [150.0, 210.0]]
    assert annotations["Ink"]["vertices_pt"] == [[[20.25, 240.0], [80.5, 250.25], [140.0, 240.5]],
                                                  [[165.0, 245.0], [185.5, 260.0]]]
    assert "vertices_pt" not in annotations["Text"] and "line_ends" not in annotations["Square"]
    # No path, project/revision/target or command authority is created from marks.
    assert not {"project_id", "revision", "scientific_hash", "command", "path"} & result.keys()
    assert result["annotation_coordinate_space"] == "pymupdf_unrotated_page_points"
    assert result["page_rect_coordinate_space"] == "pymupdf_rotated_visible_page_points"
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    # Returned dictionaries cannot affect another read or the original PDF.
    annotations["Text"]["info"]["content"] = "caller modified its own result"
    assert inspect_pdf_annotations(data)["pages"][0]["annotations"][0]["info"]["content"].startswith("Increase tick")
    with pymupdf.open(stream=data, filetype="pdf") as original_document:
        assert "Original measurements: 1.25, 2.5, 3.75" in original_document[0].get_text()


def test_page_location_crop_rotation_and_original_unrotated_vertices_are_not_conflated():
    with pymupdf.open() as document:
        document.new_page(width=200, height=200)
        page = document.new_page(width=300, height=400)
        page.set_cropbox(pymupdf.Rect(30, 40, 270, 360))
        page.add_line_annot((15.25, 25.5), (120.5, 130.25))
        page.set_rotation(90)
        data = document.tobytes()
    result = inspect_pdf_annotations(data)
    assert result["page_count"] == 2 and result["annotation_count"] == 1
    first, rotated = result["pages"]
    assert first["page_index"] == 0 and first["annotations"] == []
    assert rotated["page_index"] == 1 and rotated["rotation"] == 90
    assert rotated["rect_pt"] == [0.0, 0.0, 320.0, 240.0]
    assert rotated["media_box_pt"] == [0.0, 0.0, 300.0, 400.0]
    assert rotated["crop_box_pt"] == [30.0, 40.0, 270.0, 360.0]
    assert rotated["annotations"][0]["vertices_pt"] == [[15.25, 25.5], [120.5, 130.25]]


def test_no_structured_annotations_does_not_claim_absence_of_flattened_visual_marks(monkeypatch):
    with pymupdf.open() as document:
        page = document.new_page()
        page.draw_rect((20, 20, 100, 100), color=(1, 0, 0))
        page.insert_text((20, 130), "Flattened review text is page content, not an annotation.")
        data = document.tobytes()
    def no_raster_or_ocr(*_args, **_kwargs):
        pytest.fail("Reference annotation reading must not rasterize or extract page text.")
    with monkeypatch.context() as patcher:
        patcher.setattr(pymupdf.Page, "get_pixmap", no_raster_or_ocr)
        patcher.setattr(pymupdf.Page, "get_text", no_raster_or_ocr)
        result = inspect_pdf_annotations(data)
    assert result["annotation_count"] == 0 and result["pages"][0]["annotations"] == []
    assert result["visual_marks_evaluated"] is False
    assert result["all_pdf_annotation_types_enumerated"] is False
    assert result["scope"] == "pymupdf_enumerated_review_annotations"


def test_uninterpreted_standard_types_preserve_metadata_without_reading_attachments(monkeypatch):
    with pymupdf.open() as document:
        page = document.new_page()
        page.add_stamp_annot((20, 20, 150, 60))
        attached = page.add_file_annot((25, 85), b"do not extract or execute", "not-for-reading.txt")
        attached.set_info(content="Reference attachment marker only")
        document.embfile_add("document-attachment", b"must not be read")
        data = document.tobytes()
    def no_payload(*_args, **_kwargs):
        pytest.fail("PDF attachment payloads are outside annotation-reference reading.")
    with monkeypatch.context() as patcher:
        patcher.setattr(pymupdf.Annot, "get_file", no_payload)
        patcher.setattr(pymupdf.Document, "embfile_get", no_payload)
        result = inspect_pdf_annotations(data)
    annotations = {item["type_name"]: item for item in result["pages"][0]["annotations"]}
    assert annotations["Stamp"]["type_code"] == pymupdf.PDF_ANNOT_STAMP
    assert annotations["FileAttachment"]["type_code"] == pymupdf.PDF_ANNOT_FILE_ATTACHMENT
    assert annotations["FileAttachment"]["info"]["content"] == "Reference attachment marker only"
    assert not {"payload", "attachment", "javascript", "action"} & result.keys()


def test_library_omission_of_a_future_subtype_stays_an_explicit_coverage_limit():
    with pymupdf.open() as document:
        page = document.new_page()
        annotation = page.add_rect_annot((20, 20, 80, 80))
        document.xref_set_key(annotation.xref, "Subtype", "/FutureMarkup")
        data = document.tobytes()
    result = inspect_pdf_annotations(data)
    assert result["pages"][0]["pdf_annots_entry_type"] == "array"
    assert result["annotation_count"] == 0  # MuPDF omits this unknown subtype.
    assert result["all_pdf_annotation_types_enumerated"] is False
    assert result["visual_marks_evaluated"] is False


@pytest.mark.parametrize("data", [b"", b"not a PDF", b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\n"])
def test_malformed_bytes_fail_with_a_clear_pdf_reference_error(data):
    with pytest.raises(ValueError, match="PDF reference"):
        inspect_pdf_annotations(data)


@pytest.mark.parametrize("password", ["secret", ""])
def test_encrypted_pdfs_are_refused_even_with_an_empty_user_password(password):
    with pymupdf.open() as document:
        document.new_page()
        data = document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                                owner_pw="owner-password", user_pw=password)
    with pytest.raises(ValueError, match="Encrypted PDF references"):
        inspect_pdf_annotations(data)


@pytest.mark.parametrize("data", ["not bytes", bytearray(b"%PDF"), memoryview(b"%PDF")])
def test_accepts_immutable_bytes_only(data):
    with pytest.raises(TypeError, match="immutable bytes"):
        inspect_pdf_annotations(data)

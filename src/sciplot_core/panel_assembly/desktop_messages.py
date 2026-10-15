"""User-facing choices for bounded assembly diagnostics; full detail is a tooltip."""


def display_message(message):
    for code, text in (
        ("assembly_native_qa_failed", "A panel would clip at this size. Adjust its source or choose a supported layout before exporting."),
        ("assembly_reflow_unsupported", "This source cannot use the selected panel layout. Choose another source or layout."),
        ("assembly_source_stale", "A source has changed. Check sources and choose the current source version before exporting."),
        ("assembly_output_exists", "This export folder already exists. Choose a new folder."),
    ):
        if code in message:
            return text
    return message

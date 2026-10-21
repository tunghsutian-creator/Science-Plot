"""CLI semantic flags and MCP requests share one ordinary task contract."""
from sciplot_core.cli.parsers.builder import build_parser


def test_semantic_flags_are_available_without_a_template_or_schema_round_trip():
    parser = build_parser()
    args = parser.parse_args(["task", "create", "--source", "/one.xlsx", "--source", "/two.xlsx",
                              "--x", "time", "--x-unit", "min", "--y", "mass", "--y-min", "95",
                              "--secondary-y", "temperature", "--stages", "concatenate",
                              "--marker-every", "120", "--interpolation", "pchip", "--json"])
    assert [str(path) for path in args.sources] == ["/one.xlsx", "/two.xlsx"]
    assert args.y_min == 95 and args.marker_every == 120
    assert args.interpolation == "pchip" and args.stages == "concatenate"


def test_table_query_help_calls_out_json_file_path(capsys):
    import pytest

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["task", "table-region", "--help"])
    help_text = capsys.readouterr().out
    assert "JSON_FILE" in help_text and "inline" in help_text

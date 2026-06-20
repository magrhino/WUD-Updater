from wudup.web_metadata import json_list, json_object, json_object_or_empty


def test_json_object_uses_compact_sorted_encoding():
    assert json_object({"beta": 2, "alpha": 1}) == '{"alpha":1,"beta":2}'


def test_json_list_encodes_sequence_without_sorting():
    assert json_list(("wed", "mon")) == '["wed","mon"]'


def test_json_object_or_empty_parses_objects():
    assert json_object_or_empty('{"status":"queued"}') == {"status": "queued"}


def test_json_object_or_empty_returns_empty_for_invalid_metadata():
    assert json_object_or_empty("[1,2]") == {}
    assert json_object_or_empty("{") == {}
    assert json_object_or_empty(None) == {}

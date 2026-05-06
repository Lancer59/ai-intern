"""Tests for tools/custom_tools.py"""
import pytest
from tools.custom_tools import think, read_package_source


class TestThink:
    def test_returns_input_unchanged(self):
        result = think.invoke({"thought": "hello world"})
        assert result == "hello world"

    def test_empty_string(self):
        result = think.invoke({"thought": ""})
        assert result == ""

    def test_multiline_thought(self):
        thought = "line one\nline two\nline three"
        result = think.invoke({"thought": thought})
        assert result == thought


class TestReadPackageSource:
    def test_valid_stdlib_module(self):
        result = read_package_source.invoke({"module_path": "json"})
        assert "# Source:" in result
        assert not result.startswith("Error")
        assert not result.startswith("Could not")

    def test_valid_class_in_module(self):
        result = read_package_source.invoke({"module_path": "json.decoder.JSONDecoder"})
        assert "JSONDecoder" in result
        assert not result.startswith("Error")
        assert not result.startswith("Could not")

    def test_invalid_module_returns_error(self):
        result = read_package_source.invoke({"module_path": "totally.fake.module.xyz"})
        assert result.startswith("Could not import") or result.startswith("Error")

    def test_valid_pure_python_function(self):
        # json.dumps is pure Python and inspectable
        result = read_package_source.invoke({"module_path": "json.encoder.JSONEncoder.encode"})
        assert "# Source:" in result or "encode" in result

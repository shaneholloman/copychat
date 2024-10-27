from pathlib import Path
import pytest
from copychat.format import (
    guess_language,
    format_file,
    create_header,
    estimate_tokens,
    format_files,
)


@pytest.fixture
def temp_files(tmp_path):
    """Create temporary test files."""
    # Create a python file
    py_file = tmp_path / "test.py"
    py_file.write_text("def hello():\n    print('world')")

    # Create a javascript file
    js_file = tmp_path / "test.js"
    js_file.write_text("function hello() {\n    console.log('world');\n}")

    return tmp_path, [py_file, js_file]


def test_guess_language():
    """Test language detection from file extensions."""
    assert guess_language(Path("test.py")) == "python"
    assert guess_language(Path("test.js")) == "javascript"
    assert guess_language(Path("test.tsx")) == "tsx"
    assert guess_language(Path("test.unknown")) is None


def test_format_file(temp_files):
    """Test single file formatting."""
    root_path, (py_file, _) = temp_files

    result = format_file(py_file, root_path)

    assert "<file" in result
    assert 'path="test.py"' in result
    assert 'language="python"' in result
    assert "def hello():" in result
    assert "print('world')" in result


def test_create_header(temp_files):
    """Test header creation."""
    root_path, files = temp_files

    header = create_header(files, root_path)

    assert "Generated by copychat on" in header
    assert "Root path:" in header
    assert "Files: 2" in header
    assert "- test.py" in header
    assert "- test.js" in header


def test_estimate_tokens():
    """Test token estimation."""
    text = "Hello, world! This is a test."
    tokens = estimate_tokens(text)
    assert tokens > 0
    assert isinstance(tokens, int)


def test_format_files(temp_files):
    """Test formatting multiple files."""
    root_path, files = temp_files

    result = format_files(files)

    # Check header
    assert "Generated by copychat" in result

    # Check both files are included
    assert 'path="test.py"' in result
    assert 'path="test.js"' in result

    # Check content
    assert "def hello():" in result
    assert "console.log('world');" in result


def test_format_files_empty():
    """Test formatting with no files."""
    result = format_files([])
    assert "No files found" in result


def test_format_file_error(tmp_path):
    """Test handling of file read errors."""
    non_existent = tmp_path / "does_not_exist.py"
    result = format_file(non_existent, tmp_path)
    assert "Error processing" in result

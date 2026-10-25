"""Bounded OOXML ZIP/XML preflight; never extract files or resolve entities."""
from __future__ import annotations

import io
import re
import stat
import zipfile
from typing import BinaryIO, NoReturn
from xml.parsers import expat

from core.config import ImportConfig


class OfficeValidationError(ValueError):
    """Only fixed, document-independent messages may cross the parser boundary."""


def _cell(value: str, config: ImportConfig) -> tuple[int, int]:
    match = re.fullmatch(r'([A-Za-z]{1,3})([1-9][0-9]{0,6})', value)
    if match is None:
        raise OfficeValidationError('Invalid worksheet cell reference; obtain a valid spreadsheet export.')
    column = 0
    for char in match[1].upper():
        column = column * 26 + ord(char) - ord('A') + 1
    row = int(match[2])
    if column > config.max_spreadsheet_columns or row > min(config.max_records + 1, 1048576):
        raise OfficeValidationError('Worksheet dimensions exceed import limits; split or trim the spreadsheet.')
    return row, column


def _check_xml(stream: BinaryIO, config: ImportConfig, *, worksheet: bool,
               expected_root: str | None) -> int:
    parser = expat.ParserCreate(namespace_separator='}')
    depth = size = rows = columns = 0

    def reject_declaration(*args: object) -> NoReturn:
        raise OfficeValidationError('XML DTD declarations and entities are not supported; obtain a plain Office export.')

    def start(name: str, attributes: dict[str, str]) -> None:
        nonlocal depth, rows, columns
        depth += 1
        if depth > config.max_xml_depth:
            raise OfficeValidationError('XML nesting exceeds import.max_xml_depth; simplify the document.')
        if depth == 1 and expected_root is not None and name != expected_root:
            raise OfficeValidationError('Unexpected Office XML structure; obtain a valid original-format export.')
        # Check coordinates before openpyxl can allocate padded row arrays or
        # iterate sparse gaps. Check actual cells as well as declared dimensions.
        if not worksheet or not name.startswith('http://schemas.openxmlformats.org/spreadsheetml/2006/main}'):
            return
        tag = name.rsplit('}', 1)[-1]
        if tag == 'dimension' and 'ref' in attributes:
            refs = attributes['ref'].split(':')
            if len(refs) not in (1, 2):
                raise OfficeValidationError('Invalid worksheet dimensions; obtain a valid spreadsheet export.')
            coordinates = [_cell(ref, config) for ref in refs]
            if len(coordinates) == 2 and any(a > b for a, b in zip(*coordinates)):
                raise OfficeValidationError('Invalid worksheet dimensions; obtain a valid spreadsheet export.')
        elif tag == 'row':
            rows += 1
            columns = 0
            value = attributes.get('r', str(rows))
            if (not re.fullmatch(r'[1-9][0-9]{0,6}', value)
                    or int(value) > min(config.max_records + 1, 1048576)
                    or rows > config.max_records + 1):
                raise OfficeValidationError('Worksheet rows exceed import limits; split or trim the spreadsheet.')
        elif tag == 'c':
            columns += 1
            if columns > config.max_spreadsheet_columns:
                raise OfficeValidationError('Worksheet columns exceed import.max_spreadsheet_columns.')
            if 'r' in attributes:
                _cell(attributes['r'], config)

    def end(name: str) -> None:
        nonlocal depth
        depth -= 1

    parser.StartDoctypeDeclHandler = reject_declaration
    parser.EntityDeclHandler = reject_declaration
    parser.ExternalEntityRefHandler = reject_declaration
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        while chunk := stream.read(65536):
            size += len(chunk)
            if size > config.max_expanded_bytes:
                raise OfficeValidationError('Expanded document exceeds the configured size limit.')
            parser.Parse(chunk, False)
        parser.Parse(b'', True)
    except expat.ExpatError:
        raise OfficeValidationError('Malformed Office XML; obtain a valid original-format export.') from None
    return size


def validate_office_archive(data: bytes, config: ImportConfig) -> None:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) > config.max_archive_members:
            raise OfficeValidationError('Archive contains too many members.')
        if sum(item.file_size for item in members) > config.max_expanded_bytes:
            raise OfficeValidationError('Expanded document exceeds the configured size limit.')
        seen: set[str] = set()
        for item in members:
            name = item.orig_filename
            parts = (name[:-1] if name.endswith('/') else name).split('/')
            if (not name or name.startswith('/') or any(part in {'', '.', '..'} for part in parts)
                    or any(char in name for char in ('\\', ':', '\x00'))):
                raise OfficeValidationError('Unsafe archive member path; obtain a valid Office export.')
            if name.casefold() in seen:
                raise OfficeValidationError('Duplicate archive members are not supported; obtain a clean export.')
            seen.add(name.casefold())
            if stat.S_ISLNK(item.external_attr >> 16):
                raise OfficeValidationError('Archive symlink members are not supported.')
            if item.flag_bits & 1:
                raise OfficeValidationError('Encrypted documents require an authorized unencrypted export.')
            if item.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise OfficeValidationError('Unsupported Office compression; obtain a standard Office export.')
            if 'vbaproject' in name.casefold():
                raise OfficeValidationError('Macro-bearing documents are not supported; export a macro-free copy.')
        expanded = 0
        for item in members:
            if item.filename.lower().endswith(('.xml', '.rels')) and not item.is_dir():
                worksheet = item.filename.lower().startswith('xl/worksheets/')
                expected_root = None
                if worksheet:
                    expected_root = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main}worksheet'
                elif item.filename == 'word/document.xml':
                    expected_root = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main}document'
                with archive.open(item) as stream:
                    expanded += _check_xml(stream, config, worksheet=worksheet, expected_root=expected_root)
                if expanded > config.max_expanded_bytes:
                    raise OfficeValidationError('Expanded document exceeds the configured size limit.')

"""Local proposal checks against supplied JSON schemas; no SDK or app state.

These helpers do not execute or validate a call against a ToolEnv. The mounted
organizer ToolEnv remains the authority for actual calls. Compatibility includes
the frozen policy's permissive seconds/offset handling and error ordering.
"""
import datetime
import math
import re


def format_ok(value, fmt):
    if not isinstance(value, str):
        return False
    patterns = {
        'date': r'^(\d{4})-(\d{2})-(\d{2})$',
        'date-time': r'^(\d{4})-(\d{2})-(\d{2})T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$',
        'time': r'^\d{1,2}:\d{2}(:\d{2})?$',
    }
    if fmt not in patterns:
        return True
    match = re.match(patterns[fmt], value)
    if match is None:
        return False
    if fmt == 'time':
        hour, minute = value.split(':')[:2]
    else:
        try:
            datetime.date(*[int(match.group(i)) for i in (1, 2, 3)])
        except ValueError:
            return False
        if fmt == 'date':
            return True
        hour, minute = value[11:13], value[14:16]
    return int(hour) < 24 and int(minute) < 60


def _empty(value):
    return value in (None, '', [], {})


def _error(key, value, spec):
    kind = spec.get('type')
    types = {'string': str, 'integer': int, 'number': (int, float),
             'boolean': bool, 'array': list, 'object': dict}
    valid = kind not in types or isinstance(value, types[kind])
    if kind in ('integer', 'number') and isinstance(value, bool):
        valid = False
    if not valid:
        return f'{key} phải là {kind}'
    choices = spec.get('enum')
    if choices and not any(value == x and isinstance(value, bool) == isinstance(x, bool) for x in choices):
        return f'{key} phải là một trong {choices}'
    if kind in ('integer', 'number'):
        if isinstance(value, float) and not math.isfinite(value):
            return f'{key} phải là số hữu hạn'
        for bound, symbol, fails in (
            ('minimum', '>=', lambda x: value < x),
            ('exclusiveMinimum', '>', lambda x: value <= x),
            ('maximum', '<=', lambda x: value > x),
            ('exclusiveMaximum', '<', lambda x: value >= x),
        ):
            if bound in spec and fails(spec[bound]):
                return f'{key} phải {symbol} {spec[bound]}'
    fmt = spec.get('format')
    if fmt and not format_ok(value, fmt):
        suffix = {'date': ' (YYYY-MM-DD)', 'time': ' (HH:MM)',
                  'date-time': ' (ISO-8601, ví dụ 2026-11-16T17:00:00+07:00)'}.get(fmt, '')
        return f'{key} phải có dạng {fmt}' + suffix
    if kind == 'array' and isinstance(spec.get('items'), dict):
        for element in value:
            error = _error(key + '[]', element, spec['items'])
            if error:
                return error
    return None


def schema_error(name, arguments, catalog, allowed=None):
    if catalog is None:
        tools = {}
    elif isinstance(catalog, list):
        tools = {entry['name']: entry for entry in catalog}
    elif 'tools' in catalog:
        tools = {entry['name']: entry for entry in catalog['tools']}
    elif 'apps' in catalog:
        tools = {entry['name']: entry for app in catalog['apps'] for entry in app.get('tools', [])}
    else:
        tools = catalog
    if not isinstance(name, str) or (tools and name not in tools):
        return f"tool '{name}' không có trong catalog"
    if allowed is not None and name not in allowed:
        return f"tool '{name}' không thuộc app đã cài"
    arguments = arguments if isinstance(arguments, dict) else {}
    params = (tools.get(name) or {}).get('parameters') or {}
    missing = [key for key in params.get('required', []) if _empty(arguments.get(key))]
    if missing:
        return 'thiếu tham số bắt buộc: ' + ', '.join(missing)
    alternatives = params.get('x-one-of') or []
    if alternatives and not any(all(not _empty(arguments.get(key)) for key in group) for group in alternatives):
        return 'cần một trong: ' + ' / '.join(' + '.join(group) for group in alternatives)
    errors = []
    for key, spec in (params.get('properties') or {}).items():
        if not _empty(arguments.get(key)):
            error = _error(key, arguments[key], spec)
            if error:
                errors.append(error)
    return 'sai tham số: ' + '; '.join(errors) if errors else None

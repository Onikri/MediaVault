"""MangaDot's flattened route response, ported from the Keiyoushi decoder."""

from manga_dot_nami_http import json_data
from source_parser import SourceError


def route_data(raw, route):
    lines = raw.split('\n')
    if not lines:
        raise SourceError('MangaDot вернул пустой ответ маршрута.')
    flat = json_data(lines[0])
    if not isinstance(flat, list) or not flat:
        raise SourceError('MangaDot изменил формат ответа маршрута.')
    promises = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        prefix, separator, body = line.partition(':')
        if not separator:
            raise SourceError('MangaDot вернул повреждённую строку маршрута.')
        value = json_data(body)
        if isinstance(value, list):
            offset = len(flat)
            flat.extend(value)
        elif type(value) is int:
            offset = value
        else:
            raise SourceError('MangaDot вернул некорректную ссылку маршрута.')
        if prefix.startswith('P') and prefix[1:].isascii() and prefix[1:].isdigit() and len(prefix) <= 9:
            promises[int(prefix[1:])] = offset
        if len(flat) > 120_000:
            raise SourceError('Ответ маршрута MangaDot слишком велик.')
    if len(flat) > 120_000:
        raise SourceError('Ответ маршрута MangaDot слишком велик.')

    resolved, visiting = {}, set()

    def raw_slot(index):
        if type(index) is not int or not 0 <= index < len(flat):
            raise SourceError('MangaDot вернул ссылку за границами ответа.')
        return flat[index]

    def decode(index, depth=0):
        if type(index) is not int:
            raise SourceError('MangaDot вернул некорректную ссылку маршрута.')
        if index < 0:
            return None
        if depth > 125 or index in visiting:
            raise SourceError('MangaDot вернул циклическую ссылку маршрута.')
        if index in resolved:
            return resolved[index]
        value = raw_slot(index)
        visiting.add(index)
        if isinstance(value, list):
            if value and value[0] in ('P', 'Z'):
                if len(value) != 2 or type(value[1]) is not int:
                    raise SourceError('MangaDot вернул некорректную ссылку маршрута.')
                target = promises.get(value[1], -1) if value[0] == 'P' else value[1]
                result = decode(target, depth + 1)
            else:
                result = [decode(item, depth + 1) for item in value]
        elif isinstance(value, dict):
            result = {}
            for name, pointer in value.items():
                key = name.removeprefix('_')
                if not key.isascii() or not key.isdigit() or len(key) > 7:
                    raise SourceError('MangaDot вернул некорректный ключ маршрута.')
                label = raw_slot(int(key))
                if not isinstance(label, str):
                    raise SourceError('MangaDot вернул некорректный ключ маршрута.')
                result[label] = decode(pointer, depth + 1)
        else:
            result = value
        visiting.remove(index)
        resolved[index] = result
        return result

    result = decode(0)
    if isinstance(result, dict) and isinstance(result.get(route), dict):
        return result[route]
    raise SourceError('Ответ MangaDot не содержит запрошенный маршрут.')

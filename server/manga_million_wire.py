"""Fields of the public Manga Million API at Keiyoushi revision 6f345a8."""

from collections import defaultdict

from source_parser import SourceError


def varint(data, start):
    result = 0
    for shift in range(0, 70, 7):
        if start >= len(data):
            break
        byte = data[start]
        start += 1
        if shift == 63 and byte > 1:
            break
        result |= (byte & 127) << shift
        if byte < 128:
            return result, start
    raise SourceError('Manga Million вернул повреждённый ответ Protobuf.')


class Message:
    def __init__(self, data):
        fields = defaultdict(list)
        position = 0
        for _ in range(250_000):
            if position == len(data):
                self.fields = fields
                return
            tag, position = varint(data, position)
            number, wire = tag >> 3, tag & 7
            if not 0 < number < 2**29 or wire not in {0, 1, 2, 5}:
                break
            if wire == 0:
                value, position = varint(data, position)
            else:
                if wire == 2:
                    width, position = varint(data, position)
                else:
                    width = 8 if wire == 1 else 4
                end = position + width
                if end > len(data):
                    break
                value = data[position:end]
                position = end
            fields[number].append((wire, value))
        raise SourceError('Manga Million вернул повреждённый ответ Protobuf.')

    def values(self, number, wire):
        for actual, value in self.fields.get(number, ()):
            if actual != wire:
                raise SourceError('Manga Million изменил формат Protobuf.')
            yield value

    def integer(self, number):
        return next(self.values(number, 0), 0)

    def strings(self, number):
        try:
            for value in self.values(number, 2):
                yield value.decode('utf-8')
        except UnicodeDecodeError:
            raise SourceError('Manga Million вернул некорректный текст.') from None

    def string(self, number):
        return next(self.strings(number), '')

    def messages(self, number):
        for data in self.values(number, 2):
            yield Message(data)

    def message(self, number):
        value = next(self.messages(number), None)
        if value is None:
            raise SourceError('Manga Million не предоставил необходимые данные.')
        return value

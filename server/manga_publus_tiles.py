"""Publus image coordinates, based on the Apache-2.0 Keiyoushi library."""

from functools import reduce
from operator import xor

from source_parser import SourceError

MASK32 = (1 << 32) - 1
SHIFTS = (
    (1, 3, 10), (1, 5, 16), (1, 5, 19), (1, 9, 29), (1, 11, 6), (1, 11, 16), (1, 19, 3), (1, 21, 20), (1, 27, 27),
    (2, 5, 15), (2, 5, 21), (2, 7, 7), (2, 7, 9), (2, 7, 25), (2, 9, 15), (2, 15, 17), (2, 15, 25), (2, 21, 9),
    (3, 1, 14), (3, 3, 26), (3, 3, 28), (3, 3, 29), (3, 5, 20), (3, 5, 22), (3, 5, 25), (3, 7, 29),
    (3, 13, 7), (3, 23, 25), (3, 25, 24), (3, 27, 11), (4, 3, 17), (4, 3, 27), (4, 5, 15),
    (5, 3, 21), (5, 7, 22), (5, 9, 7), (5, 9, 28), (5, 9, 31), (5, 13, 6), (5, 15, 17), (5, 17, 13),
    (5, 21, 12), (5, 27, 8), (5, 27, 21), (5, 27, 25), (5, 27, 28),
    (6, 1, 11), (6, 3, 17), (6, 17, 9), (6, 21, 7), (6, 21, 13), (7, 1, 9), (7, 1, 18), (7, 1, 25),
    (7, 13, 25), (7, 17, 21), (7, 25, 12), (7, 25, 20), (8, 7, 23), (8, 9, 23),
    (9, 5, 14), (9, 5, 25), (9, 11, 19), (9, 21, 16), (10, 9, 21), (10, 9, 25), (11, 7, 12),
    (11, 7, 16), (11, 17, 13), (11, 21, 13), (12, 9, 23), (13, 3, 17), (13, 3, 27), (13, 5, 19),
    (13, 17, 15), (14, 1, 15), (14, 13, 15), (15, 1, 29), (17, 15, 20), (17, 15, 23), (17, 15, 26),
)


class TileRandom:
    fallback = 2463534242

    def __init__(self, mode, seed):
        group, variant = divmod(mode, 6)
        x, y, z = SHIFTS[group % len(SHIFTS)]
        self.shifts = ((x, -y, z), (z, -y, x), (-x, y, -z), (-z, y, -x), (x, z, -y), (-x, -z, y))[variant]
        self.reset(seed)

    def reset(self, seed):
        self.value = (seed & MASK32) or self.fallback

    def choose(self, size):
        if size <= 1:
            return 0
        while True:
            for shift in self.shifts:
                if shift > 0:
                    self.value ^= (self.value << shift) & MASK32
                else:
                    self.value ^= self.value >> -shift
            value = (self.value - 1) & MASK32
            result = value % size
            if value - result <= MASK32 - size:
                return result


def permutation(random, count):
    result = [0] * count
    for i in range(count):
        offset = random.choose(i + 1)
        result[i] = result[offset]
        result[offset] = i
    return result


def edge_positions(random, cols, rows, x, y):
    """Place the two partial-width strips without overlapping the partial-height strips."""
    x_positions, y_positions = [0] * rows, [0] * cols
    cols_left, rows_left = cols, rows
    col_start = row_start = 0
    while cols_left + rows_left:
        choice = random.choose(cols_left + rows_left)
        if choice < cols_left:
            column = col_start if choice < x else col_start + cols_left - 1
            before, after = row_start, row_start + rows_left
            if choice < x:
                while before > 0 and column < x_positions[before - 1]:
                    before -= 1
                while after < rows and column < x_positions[after]:
                    after += 1
                col_start += 1
                x -= 1
            else:
                while before > 0 and column + 1 > x_positions[before - 1]:
                    before -= 1
                while after < rows and column + 1 > x_positions[after]:
                    after += 1
            y_positions[column] = random.choose(after - before) + before
            cols_left -= 1
        else:
            from_start = choice - cols_left < y
            row = row_start if from_start else row_start + rows_left - 1
            before, after = col_start, col_start + cols_left
            if from_start:
                while before > 0 and row < y_positions[before - 1]:
                    before -= 1
                while after < cols and row < y_positions[after]:
                    after += 1
                row_start += 1
                y -= 1
            else:
                while before > 0 and row + 1 > y_positions[before - 1]:
                    before -= 1
                while after < cols and row + 1 > y_positions[after]:
                    after += 1
            x_positions[row] = random.choose(after - before) + before
            rows_left -= 1
    return x_positions, y_positions


def choose_edge(random, length):
    return random.choose(length + 1) if length < 4 else random.choose(length - 1) + 1


def alternate_edge(random, pos, length):
    if length <= 0:
        return 0
    after = random.choose(length)
    return after + (after >= pos)


def mix_words(key):
    return reduce(xor, (int.from_bytes(key[i:i + 4], 'big') for i in range(0, 32, 4)), 0)


def keyed_cells(page_id, number, cols, rows, keys, seeds):
    total = 47 + sum(ord(c) for c in page_id + str(number)) + sum(map(sum, keys))
    group = total % (len(SHIFTS) * 6)
    common = (total & 255) * 0x01010101
    first, second, third = ((common ^ mix_words(key) ^ seed) & MASK32 for key, seed in zip(keys, seeds))

    # The upstream two-stage initializer starts identical generators for both salts.
    # Their output cancels when XORed before the permutation.
    random = TileRandom(group, first)
    core = permutation(random, cols * rows)
    random.reset(second)
    left, upper = choose_edge(random, cols), choose_edge(random, rows)
    right, lower = alternate_edge(random, left, cols), alternate_edge(random, upper, rows)
    random.reset(third)
    row_edge, col_edge = edge_positions(random, cols, rows, left, upper)
    across, down = permutation(random, cols), permutation(random, rows)
    target_row, target_col = edge_positions(random, cols, rows, right, lower)

    def edge_coordinate(value, edge, size):
        return value if value < edge else value + size + 1

    for col in range(cols):
        for row in range(rows):
            dest_row, dest_col = divmod(core[col + row * cols], cols)
            yield (edge_coordinate(col, row_edge[row], cols), edge_coordinate(row, col_edge[col], rows),
                   edge_coordinate(dest_col, target_row[dest_row], cols),
                   edge_coordinate(dest_row, target_col[dest_col], rows), 'full')
    yield left, upper, right, lower, 'corner'
    for col, dest_col in enumerate(across):
        yield (edge_coordinate(col, left, cols), col_edge[col],
               edge_coordinate(dest_col, right, cols), target_col[dest_col], 'bottom')
    for row, dest_row in enumerate(down):
        yield (row_edge[row], edge_coordinate(row, upper, rows),
               target_row[dest_row], edge_coordinate(dest_row, lower, rows), 'right')


def keyed_moves(page_id, number, width, height, block_w, block_h, keys, seeds):
    cols, last_w = divmod(width, block_w)
    rows, last_h = divmod(height, block_h)
    if cols > 128 or rows > 128 or (cols + 1) * (rows + 1) > 4096:
        raise SourceError('Publus вернул слишком много плиток страницы.')
    shapes = {'full': (block_w, block_h), 'corner': (last_w, last_h),
              'bottom': (block_w, last_h), 'right': (last_w, block_h)}

    def pixels(cell, length, rest, count):
        if cell > count:
            return (cell - count - 1) * length + rest
        return cell * length

    for x, y, dst_x, dst_y, shape in keyed_cells(page_id, number, cols, rows, keys, seeds):
        w, h = shapes[shape]
        if w and h:
            yield (pixels(dst_x, block_w, last_w, cols), pixels(dst_y, block_h, last_h, rows),
                   pixels(x, block_w, last_w, cols), pixels(y, block_h, last_h, rows), w, h)


def plain_moves(width, height, pattern):
    size = 64
    cols, rest_x = divmod(width, size)
    rows, rest_y = divmod(height, size)

    def edge(n, multiplier):
        if not n:
            return 0
        value = n - multiplier * pattern % n
        if value == n:
            value = (n - 4) % n
        return value or n - 1

    left, upper = edge(cols, 43), edge(rows, 47)
    odd = bool(pattern % 2)

    def target_x(index):
        choose_right = (index < upper) == odd
        length, bias = (cols - left, left) if choose_right else (left, 0)
        return (index + 67 * pattern + left + 71) % length + bias if length else 0

    def target_y(index):
        choose_top = (index < left) == odd
        length, bias = (upper, 0) if choose_top else (rows - upper, upper)
        return (index + 53 * pattern + 59 * upper) % length + bias if length else 0

    def position(cell, boundary, rest):
        return cell * size + (rest if cell >= boundary else 0)

    if rest_x and rest_y:
        yield left * size, upper * size, left * size, upper * size, rest_x, rest_y
    if rest_y:
        for col in range(cols):
            x = (col + 61 * pattern) % cols
            yield position(x, left, rest_x), target_y(x) * size, position(col, left, rest_x), upper * size, size, rest_y
    if rest_x:
        for row in range(rows):
            y = (row + 73 * pattern) % rows
            yield target_x(y) * size, position(y, upper, rest_y), left * size, position(row, upper, rest_y), rest_x, size
    for col in range(cols):
        for row in range(rows):
            x = (col + 29 * pattern + 31 * row) % cols
            y = (row + 37 * pattern + 41 * x) % rows
            yield (position(x, target_x(y), rest_x), position(y, target_y(x), rest_y),
                   position(col, left, rest_x), position(row, upper, rest_y), size, size)

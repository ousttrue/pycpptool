import re
from typing import Dict, List


class Declare:
    def __init__(self):
        pass


class Void(Declare):
    def __init__(self, src=''):
        self.is_const = False
        self.type = 'void'
        if src:
            splitted = src.split()
            count = len(splitted)
            if count == 1:
                pass
            elif count == 2:
                if splitted[0] == 'const':
                    self.is_const = True
                else:
                    raise NotImplementedError()
            else:
                raise NotImplementedError()

    def __str__(self) -> str:
        if self.is_const:
            return '(const void)'
        else:
            return '(void)'


class BaseType(Declare):
    def __init__(self, src: str) -> None:
        splitted = src.split()
        self.is_const = False
        self.struct = ''
        if splitted[0] in ['struct', 'union']:
            # inner declaration
            self.type = src
            self.struct = splitted[0]
        elif splitted[0] == 'enum':
            self.type = splitted[1]
        else:
            count = len(splitted)
            if count == 1:
                self.type = splitted[0]
            elif count == 2:
                if splitted[0] == 'const':
                    self.is_const = True
                    self.type = splitted[1]
                else:
                    raise RuntimeError(f'unknown type: {splitted}')
            else:
                raise RuntimeError(f'unknown type: {splitted}')

    def __str__(self) -> str:
        if self.is_const:
            return f'(const {self.type})'
        else:
            return f'({self.type})'


class Pointer(Declare):
    def __init__(self, src: str, target: Declare) -> None:
        if src[0] not in ['*', '&']:
            raise RuntimeError('arienai')
        self.ref_type = src[0]
        self.is_const = 'const' in src[1:]
        self.target = target

    def __str__(self) -> str:
        if self.is_const:
            return f'(const {self.ref_type}{self.target})'
        else:
            return f'({self.ref_type}{self.target})'


class Array(Declare):
    def __init__(self, src: str, target: Declare) -> None:
        if src[0] == '[' and src[-1] == ']':
            self.length = int(src[1:-1])
        else:
            raise RuntimeError('arienai')
        self.target = target

    def __str__(self) -> str:
        return f'{self.target}[{self.length}]'


used: Dict[str, Declare] = {}


def parse_declare(src: str) -> Declare:
    found = used.get(src)
    if found:
        return found

    d = _parse_declare(src.strip())
    # print(f'{src} => {d}')
    used[src] = d
    return d


SPLIT_PATTERN = re.compile(r'[*&]')


def _parse_declare(src: str) -> Declare:

    if src[-1] == ']':
        # is array
        start = src.rfind('[')
        return Array(src[start:], _parse_declare(src[0:start].strip()))

    else:
        found = [x for x in SPLIT_PATTERN.finditer(src)]

        count = len(found)
        if count == 0:
            if 'void' in src:
                return Void(src)
            else:
                return BaseType(src)
        else:
            last = found[-1].start()
            return Pointer(src[last:], _parse_declare(src[0:last].strip()))

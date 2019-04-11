import sys
import platform
import pathlib
from typing import Set
from clang import cindex


HERE = pathlib.Path(__file__).absolute().parent

DEFAULT_CLANG_DLL = pathlib.Path(
    "C:/Program Files (x86)/LLVM/bin/libclang.dll")


class Parser:
    def __init__(self, dll: pathlib.Path=None) -> None:
        if not dll:
            if platform.architecture()[0] == '32bit':
                dll = DEFAULT_CLANG_DLL
        self.dll = dll
        self.used: Set[int] = set()

    def parse(self, path: pathlib.Path) -> None:
        if not path.exists():
            raise FileNotFoundError(str(path))

        if self.dll:
            cindex.Config.set_library_file(str(self.dll))
        index = cindex.Index.create()
        translation_unit = index.parse(str(path),
                                       ['-x', 'c++'],
                                       options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)

        self.traverse(translation_unit.cursor)

    def traverse(self, cursor: cindex.Cursor, level: int = 0) -> None:
        if cursor.hash in self.used:
            # already processed. skip
            return

        self.used.add(cursor.hash)

        # skip
        if cursor.kind == cindex.CursorKind.TRANSLATION_UNIT:
            filename = ''
        else:
            if not cursor.location.file:
                # skip
                return
            filename = cursor.location.file.name

            # process
            print(f'{"  "*level}{cursor.kind}: {filename}')

        # children...
        for child in cursor.get_children():
            self.traverse(child, level+1)


def main() -> None:
    parser = Parser()
    parser.parse(HERE / sys.argv[1])


if __name__ == '__main__':
    main()

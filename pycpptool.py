import sys
import os
import platform
import pathlib
from typing import Dict, List, Optional, Any
from jinja2 import Template
from clang import cindex


HERE = pathlib.Path(__file__).absolute().parent

DEFAULT_CLANG_DLL = pathlib.Path(
    "C:/Program Files (x86)/LLVM/bin/libclang.dll")


class Item_TypeDef:
    def __init__(self, name: str, value: Any) -> None:
        self.name = name
        self.value = value

    def __str__(self) -> str:
        return f'{self.name}: {self.value}'


class Item_Field:
    def __init__(self, name: str, field_type: Any) -> None:
        self.name = name
        self.type = field_type

    def __str__(self) -> str:
        return str(self.type)


class Item_Struct:
    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.fields: List[Item_Field] = []
        self.struct = 'struct'

    def __str__(self) -> str:
        template = Template('''{{ struct }} {{ tag }} {
{% for f in values -%}
    {{ f.type }} {{ f.name }};
{% endfor -%}
}
''')

        return template.render(struct=self.struct,
                               tag=self.tag,
                               values=self.fields)


class Item_Union(Item_Struct):
    def __init__(self, tag: str) -> None:
        super().__init__(tag)
        self.struct = 'union'


class ParsedItem:
    def __init__(self, key: int, path: str) -> None:
        if platform.system() == 'Windows':
            path = path.lower()

        self.key = key
        self.path = path
        self.filename = os.path.basename(self.path)
        self.content: Any = None

    def __str__(self) -> str:
        if self.content:
            return f'{self.key}: {self.content}'
        else:
            return f'{self.key}'


class Parser:
    def __init__(self, dll: pathlib.Path = None) -> None:
        if not dll:
            if platform.architecture()[0] == '32bit':
                dll = DEFAULT_CLANG_DLL
        self.dll = dll
        self.item_map: Dict[int, ParsedItem] = {}
        self.parsed_items: List[ParsedItem] = []

    def parse(self, path: pathlib.Path) -> None:
        if not path.exists():
            raise FileNotFoundError(str(path))

        if self.dll:
            cindex.Config.set_library_file(str(self.dll))
        index = cindex.Index.create()
        translation_unit = index.parse(
            str(path),
            ['-x', 'c++'],
            options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)

        # skip root translation_unit
        for child in translation_unit.cursor.get_children():
            self.traverse(child)

    def traverse(self,
                 cursor: cindex.Cursor, level: int = 0) -> Optional[ParsedItem]:
        used = self.item_map.get(cursor.hash)
        if used:
            # already processed. skip
            return used

        if not cursor.location.file:
            # skip
            return None

        # new item
        item = ParsedItem(cursor.hash, cursor.location.file.name)
        self.item_map[cursor.hash] = item
        self.parsed_items.append(item)

        # process
        if cursor.kind == cindex.CursorKind.TYPEDEF_DECL:
            tokens = [x.spelling for x in cursor.get_tokens()]
            if len(tokens) == 3:
                # typedef float FLOAT
                item.content = Item_TypeDef(tokens[2], tokens[1])
            elif len(tokens) < 3:
                raise Exception(str(tokens))
            else:
                children = [x for x in cursor.get_children()]
                count = len(children)
                if count != 1:
                    raise Exception(str(children))

                item.content = Item_TypeDef(
                    tokens[-1], children[0].hash)

        elif cursor.kind == cindex.CursorKind.STRUCT_DECL:
            item.content = self._traverse_struct(cursor)

        # children...
        if item.content:
            print(f'{item.filename}: {"  "*level}{item}')
        else:
            print(f'{item.filename}: {"  "*level}{cursor.kind}')
            for child in cursor.get_children():
                self.traverse(child, level+1)

        return item

    def _traverse_struct(self,
                         cursor: cindex.Cursor, level: int = 0) -> Item_Struct:
        if cursor.kind == cindex.CursorKind.STRUCT_DECL:
            struct = Item_Struct(cursor.spelling)
        elif cursor.kind == cindex.CursorKind.UNION_DECL:
            struct = Item_Union(cursor.spelling)
        else:
            print(cursor.kind)
            raise Exception()
        for f in cursor.get_children():
            if (f.kind == cindex.CursorKind.UNION_DECL
                    or f.kind == cindex.CursorKind.STRUCT_DECL):
                field = Item_Field(
                    f.spelling, self._traverse_struct(f, level+1))
            elif f.kind == cindex.CursorKind.FIELD_DECL:
                field = Item_Field(f.spelling, f.type.spelling)
            else:
                raise Exception()
            struct.fields.append(field)
        return struct


def main() -> None:
    parser = Parser()
    parser.parse(HERE / sys.argv[1])


if __name__ == '__main__':
    main()

import sys
import os
import platform
import pathlib
from typing import Dict, List, Optional, Any, Set, Tuple
from jinja2 import Template
from clang import cindex


HERE = pathlib.Path(__file__).absolute().parent

DEFAULT_CLANG_DLL = pathlib.Path(
    "C:/Program Files (x86)/LLVM/bin/libclang.dll")


class ItemBase:
    def __init__(self, name: str) -> None:
        self.name = name


class Item_TypeDef(ItemBase):
    def __init__(self, name: str, value: Any) -> None:
        super().__init__(name)
        self.value = value

    def __str__(self) -> str:
        return f'typedef {self.name} = {self.value}'


class Item_Field(ItemBase):
    def __init__(self, name: str, field_type: Any) -> None:
        super().__init__(name)
        self.type = field_type

    def __str__(self) -> str:
        return str(self.type)


class Item_Struct(ItemBase):
    def __init__(self, tag: str) -> None:
        super().__init__(tag)
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
                               tag=self.name,
                               values=self.fields)


class Item_Union(Item_Struct):
    def __init__(self, tag: str) -> None:
        super().__init__(tag)
        self.struct = 'union'


class Item_MacroDefine(ItemBase):
    def __init__(self, name: str, value: str) -> None:
        super().__init__(name)
        self.value = value

    def __str__(self) -> str:
        return f'#define {self.name} = {self.value}'


class Item_Include(ItemBase):
    def __init__(self, include: str) -> None:
        super().__init__('#include')
        self.include = include

    def __str__(self) -> str:
        return f'#include {self.include}'


class ParsedItem:
    def __init__(self, key: int, path: str) -> None:
        if platform.system() == 'Windows':
            path = path.lower()

        self.key = key
        self.path = path
        self.filename = os.path.basename(self.path)
        self.content: Optional[ItemBase] = None

    def __str__(self) -> str:
        if self.content:
            return f'{self.key}: {self.filename}: {self.content}'
        else:
            return f'{self.key}: {self.filename}'


class Parser:
    def __init__(self, dll: pathlib.Path = None) -> None:
        if not dll:
            if platform.architecture()[0] == '32bit':
                dll = DEFAULT_CLANG_DLL
        self.dll = dll
        self.item_map: Dict[int, ParsedItem] = {}
        self.parsed_items: List[ParsedItem] = []
        self.include_headers: Set[str] = set()

    def add_include_header(self, path: pathlib.Path) -> None:
        name = path.name
        if platform.system() == 'Windows':
            name = name.lower()
        self.include_headers.add(name)

    def _is_target(self, file: str) -> bool:
        name = pathlib.Path(file).name
        if platform.system() == 'Windows':
            name = name.lower()
        return name in self.include_headers

    def _process_item(self,
                      cursor) -> Tuple[bool, Optional[ItemBase]]:
        if cursor.kind == cindex.CursorKind.INCLUSION_DIRECTIVE:
            tokens = [x.spelling for x in cursor.get_tokens()]
            if '<' in tokens:
                open = tokens.index('<')
                return False, Item_Include(''.join(tokens[open+1:-1]))
            else:
                return False, Item_Include(tokens[-1][1:-1])

        elif cursor.kind == cindex.CursorKind.MACRO_DEFINITION:
            tokens = [x for x in cursor.get_tokens()]
            if len(tokens) == 1:
                # ex. #define __header__
                return False, None
            else:
                return False, Item_MacroDefine(
                    cursor.spelling, ' '.join(x.spelling for x in tokens[1:]))

        elif cursor.kind == cindex.CursorKind.MACRO_INSTANTIATION:
            tokens = [x.spelling for x in cursor.get_tokens()]
            if tokens[0] == 'MIDL_INTERFACE':
                # com interface
                # todo
                print(tokens)
                return False, None
            if len(tokens) == 1:
                return False, None
            # print(tokens)
            # sys.exit(1)
            return False, None

        elif cursor.kind == cindex.CursorKind.TYPEDEF_DECL:
            tokens = [x.spelling for x in cursor.get_tokens()]
            if len(tokens) == 3:
                # ex. typedef float FLOAT
                return False, Item_TypeDef(tokens[2], tokens[1])
            elif len(tokens) < 3:
                raise Exception(str(tokens))
            else:
                children = [x for x in cursor.get_children()]
                count = len(children)
                if count != 1:
                    raise Exception(str(children))
                if children[0].kind not in [
                    cindex.CursorKind.TYPE_REF,
                    cindex.CursorKind.STRUCT_DECL,
                    cindex.CursorKind.ENUM_DECL,
                ]:
                    print(children[0].kind)
                    raise Exception(str(children))
                return False, Item_TypeDef(
                    tokens[-1], children[0].hash)

        elif cursor.kind == cindex.CursorKind.STRUCT_DECL:
            return False, self._process_struct(cursor)

        elif cursor.kind == cindex.CursorKind.ENUM_DECL:
            # todo
            return False, None

        elif cursor.kind == cindex.CursorKind.FUNCTION_DECL:
            # todo
            return False, None

        elif cursor.kind == cindex.CursorKind.VAR_DECL:
            tokens = [x.spelling for x in cursor.get_tokens()]
            if tokens[0] == 'extern':
                return False, None
            print(cursor.kind, tokens)
            sys.exit(1)
            return False, None

        elif cursor.kind == cindex.CursorKind.UNEXPOSED_DECL:
            tokens = [x.spelling for x in cursor.get_tokens()]
            if not tokens:
                return False, None
            if tokens[0] == 'extern':
                return True, None
            print(cursor.kind, tokens)
            sys.exit(1)
            return False, None

        tokens = [x.spelling for x in cursor.get_tokens()]
        print(cursor.kind, tokens)
        sys.exit(1)
        return False, None

    def _process_struct(self,
                        cursor: cindex.Cursor,
                        level=0) -> Item_Struct:
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
            elif f.kind == cindex.CursorKind.UNEXPOSED_ATTR:
                # todo
                continue
            elif f.kind == cindex.CursorKind.CXX_BASE_SPECIFIER:
                # todo
                continue
            elif f.kind == cindex.CursorKind.CXX_ACCESS_SPEC_DECL:
                continue
            elif f.kind == cindex.CursorKind.CXX_METHOD:
                # todo
                continue
            else:
                print(f.kind)
                raise Exception()
            struct.fields.append(field)
        return struct

    def _traverse(self,
                  cursor: cindex.Cursor, level: int = 0) -> Optional[ParsedItem]:
        used = self.item_map.get(cursor.hash)
        if used:
            # already processed. skip
            return used

        if not cursor.location.file:
            # skip
            return None

        if not self._is_target(cursor.location.file.name):
            # skip
            return None

        # new item
        item = ParsedItem(cursor.hash, cursor.location.file.name)
        self.item_map[cursor.hash] = item
        self.parsed_items.append(item)

        # process
        next_child, content = self._process_item(cursor)
        if content:
            item.content = content
            if isinstance(item.content, (Item_Include, Item_MacroDefine)):
                pass
            else:
                print(f'{"  "*level}{item}')

        if next_child:
            for child in cursor.get_children():
                self._traverse(child, level+1)

        return item

    def parse(self, path: pathlib.Path) -> None:
        '''
        parser entry point
        '''
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
            self._traverse(child)


def main() -> None:
    parser = Parser()
    path = HERE / sys.argv[1]

    parser.add_include_header(path)
    parser.parse(path)


if __name__ == '__main__':
    main()

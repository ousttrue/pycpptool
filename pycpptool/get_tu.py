import pathlib
from typing import List, Optional
from clang import cindex

# helper {{{
DEFAULT_CLANG_DLL = pathlib.Path("C:/Program Files/LLVM/bin/libclang.dll")
SET_DLL = False


def get_tu(path: pathlib.Path,
           include_path_list: List[pathlib.Path] = None,
           use_macro: bool = False,
           dll: Optional[pathlib.Path] = None) -> cindex.TranslationUnit:
    '''
    parse cpp source
    '''
    global SET_DLL

    if not path.exists():
        raise FileNotFoundError(str(path))

    if not dll and DEFAULT_CLANG_DLL.exists():
        dll = DEFAULT_CLANG_DLL
    if not SET_DLL and dll:
        cindex.Config.set_library_file(str(dll))
        SET_DLL = True

    index = cindex.Index.create()

    kw = {}
    if use_macro:
        kw['options'] = cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD

    cpp_args = ['-x', 'c++', '-DUNICODE=1', '-DNOMINMAX=1']
    if include_path_list is not None:
        for i in include_path_list:
            value = f'-I{str(i)}'
            if value not in cpp_args:
                cpp_args.append(value)

    return index.parse(str(path), cpp_args, **kw)


# def get_token(cursor: cindex.Cursor) -> int:
#     if cursor.kind != cindex.CursorKind.INTEGER_LITERAL:
#         raise Exception('not int')
#     tokens = [x.spelling for x in cursor.get_tokens()]
#     if len(tokens) != 1:
#         raise Exception('not 1')
#     return int(tokens[0])

# }}}

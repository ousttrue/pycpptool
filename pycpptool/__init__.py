import os
import argparse
import tempfile
import sys
import pathlib
import logging
from typing import List, Optional, Set, TextIO
from clang import cindex
from . import csharp, dlang, header_parser
logger = logging.getLogger(__name__)

HERE = pathlib.Path(__file__).resolve().parent

DEFAULT_CLANG_DLL = pathlib.Path("C:/Program Files/LLVM/bin/libclang.dll")

SET_DLL = False


# helper {{{
def get_tu(path: pathlib.Path,
           include_path_list: List[pathlib.Path],
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

    cpp_args = ['-x', 'c++']
    for i in include_path_list:
        value = f'-I{str(i)}'
        if value not in cpp_args:
            cpp_args.append(value)

    return index.parse(str(path), cpp_args, **kw)


def get_token(cursor: cindex.Cursor) -> int:
    if cursor.kind != cindex.CursorKind.INTEGER_LITERAL:
        raise Exception('not int')
    tokens = [x.spelling for x in cursor.get_tokens()]
    if len(tokens) != 1:
        raise Exception('not 1')
    return int(tokens[0])


# }}}


def show(f: TextIO, path: pathlib.Path, tu: cindex.TranslationUnit) -> None:

    used: Set[int] = set()

    def traverse(c: cindex.Cursor, indent='') -> None:
        # skip
        if c.location.file.name != str(path):
            # exclude included file
            return
        if c.hash in used:
            # avoid show twice
            return
        used.add(c.hash)

        ref = ''
        if c.referenced and c.referenced.hash != c.hash:
            ref = f' => {c.referenced.hash:#010x}'

        canonical = ''
        if c.canonical and c.canonical.hash != c.hash:
            canonical = f' => {c.canonical.hash:#010x} (forward decl)'

        value = f'{c.hash:#010x}:{indent} {c.kind}: {c.spelling}{ref}{canonical}'
        print(value)

        if c.kind == cindex.CursorKind.UNEXPOSED_DECL:
            tokens = [t for t in c.get_tokens()]
            if tokens and tokens[0].spelling == 'extern':
                # extern "C" block
                for child in c.get_children():
                    traverse(child)
                return

        for child in c.get_children():
            traverse(child, indent + '  ')

    for c in tu.cursor.get_children():
        traverse(c)


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        datefmt='%H:%M:%S',
        format='%(asctime)s[%(levelname)s][%(name)s.%(funcName)s] %(message)s')

    parser = argparse.ArgumentParser(description='Process cpp header.')

    sub = parser.add_subparsers()

    # debug
    sub_debug = sub.add_parser('debug')
    sub_debug.set_defaults(action='debug')
    sub_debug.add_argument('entrypoint', help='parse target', nargs='+')
    sub_debug.add_argument('-i', '--include', action='append')

    # parse
    sub_parse = sub.add_parser('parse')
    sub_parse.set_defaults(action='parse')
    sub_parse.add_argument('entrypoint', help='parse target', nargs='+')
    sub_parse.add_argument('-i', '--include', action='append')

    # generator
    sub_gen = sub.add_parser('gen')
    sub_gen.set_defaults(action='gen')
    sub_gen.add_argument('entrypoint', help='parse target', nargs='+')
    sub_gen.add_argument('-o', '--outfolder', required=True)
    sub_gen.add_argument('-i', '--include', action='append')
    sub_gen.add_argument('-g',
                         '--generator',
                         help='code generator',
                         choices=['dlang', 'csharp'],
                         required=True)

    # execute
    args = parser.parse_args()

    tmp_name = None
    try:
        include = []
        if args.include:
            include += [header_parser.normalize(x) for x in args.include]

        kit_name = ''
        include_path_list: List[str] = []
        if isinstance(args.entrypoint, list):
            fd, tmp_name = tempfile.mkstemp(prefix='tmpheader_', suffix='.h')
            os.close(fd)
            with open(tmp_name, 'w', encoding='utf-8') as f:
                for e in args.entrypoint:
                    e_path = pathlib.Path(e)
                    f.write(f'#include "{e_path.name}"\n')
                    include_path_list.append(e_path.parent)
                    include.append(header_parser.normalize(e_path.name))
                    kit_name = e_path.parent.parent.name

            path = pathlib.Path(tmp_name)
        else:
            path = (HERE / args.entrypoint).resolve()
            kit_name = path.parent.parent.name
        include.append(path.name)

        if args.action == 'debug':
            tu = get_tu(path, include_path_list)
            show(sys.stdout, tu, include_path_list)
        elif args.action == 'parse':
            headers = header_parser.parse(get_tu(path, include_path_list),
                                          include)
            header_parser.parse_macro(headers,
                                      get_tu(path, include_path_list, True),
                                      include)
            headers[path].print_nodes()
        elif args.action == 'gen':
            logger.debug('parse...')
            headers = header_parser.parse(get_tu(path, include_path_list),
                                          include)
            # for k, v in headers.items():
            #    print(k, len(v.nodes))
            logger.debug('parse_macro...')
            header_parser.parse_macro(headers,
                                      get_tu(path, include_path_list, True),
                                      include)

            logger.debug('generate...')
            if args.generator == 'dlang':
                gen = dlang.DlangGenerator()
                dlang_root = pathlib.Path(str(args.outfolder)).resolve()
                gen.generate(headers[path], dlang_root, kit_name)

            elif args.generator == 'csharp':
                gen = csharp.CSharpGenerator()
                csharp_root = pathlib.Path(str(args.outfolder)).resolve()
                gen.generate(headers[path], csharp_root, kit_name)

        else:
            raise Exception()
    finally:
        if tmp_name:
            os.unlink(tmp_name)


if __name__ == '__main__':
    main()

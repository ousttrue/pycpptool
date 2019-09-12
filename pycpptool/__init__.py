import os
import argparse
import tempfile
import sys
import pathlib
import logging
from typing import List, Optional, Set, TextIO, NamedTuple
from clang import cindex
from . import struct_alignment, csharp, dlang, cindex_parser
logger = logging.getLogger(__name__)

HERE = pathlib.Path(__file__).resolve().parent


def show(f: TextIO, tu: cindex.TranslationUnit, path: pathlib.Path) -> None:

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


generators = {
    'csharp': csharp.generate,
    'dlang': dlang.generate,
    'struct': struct_alignment.generate,
}


def setup_parser() -> argparse.ArgumentParser:
    arg_parser = argparse.ArgumentParser(description='Process cpp header.')
    sub = arg_parser.add_subparsers()

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
    sub_gen.add_argument('-n', '--namespace')

    sub_gen.add_argument('-g',
                         '--generator',
                         help='code generator',
                         choices=generators.keys(),
                         required=True)

    return arg_parser


class Parsed(NamedTuple):
    path: pathlib.Path
    multi_header: bool
    include: List[str]
    include_path_list: List[str]
    tmp_name: str
    kit_name: str
    action: str
    namespace: str
    outfolder: str
    generator: str

    def clean_tmp(self):
        if self.tmp_name:
            os.unlink(self.tmp_name)

    def process(self):
        if self.action == 'debug':
            self._debug()
        elif self.action == 'parse':
            self._parse()
        elif self.action == 'gen':
            self._gen()
        else:
            raise Exception()

    def _debug(self):
        tu = cindex_parser.get_tu(self.path, self.include_path_list)
        show(sys.stdout, tu, self.path)

    def _parse(self):
        headers = cindex_parser.parse(
            cindex_parser.get_tu(self.path, self.include_path_list),
            self.include)
        cindex_parser.parse_macro(
            headers, cindex_parser.get_tu(path, self.include_path_list, True),
            self.include)
        headers[self.path].print_nodes()

    def _gen(self):
        generator = generators.get(self.generator)
        if not generator:
            raise RuntimeError(f'no such genrator: {self.generator}')

        header_name = self.path if not self.multi_header else self.include[0] 

        logger.debug(f'parse1 headers... {header_name}')
        headers = cindex_parser.parse(
            cindex_parser.get_tu(self.path, self.include_path_list),
            self.include)

        logger.debug(f'parse2 macros... {header_name}')
        cindex_parser.parse_macro(
            headers,
            cindex_parser.get_tu(self.path, self.include_path_list, True),
            self.include)

        logger.debug(f'generate... {self.generator} => {self.outfolder}')
        root = pathlib.Path(self.outfolder).resolve()
        entry_point = headers[self.path]
        generator(entry_point, root, self.kit_name, self.namespace,
                  self.multi_header)


def parse(args: argparse.Namespace) -> Parsed:
    include = []
    include_path_list = []
    kit_name = ''
    if hasattr(args, 'include'):
        include += [cindex_parser.normalize(x) for x in args.include]

    # entrypoint
    multi_header = len(args.entrypoint) > 1
    if multi_header:
        fd, tmp_name = tempfile.mkstemp(prefix='tmpheader_', suffix='.h')
        os.close(fd)
        with open(tmp_name, 'w', encoding='utf-8') as f:
            for e in args.entrypoint:
                e_path = pathlib.Path(e)
                f.write(f'#include "{e_path.name}"\n')
                include_path_list.append(e_path.parent)
                include.append(cindex_parser.normalize(e_path.name))
                kit_name = e_path.parent.parent.name

        path = pathlib.Path(tmp_name)
    else:
        path = pathlib.Path(args.entrypoint[0]).resolve()
        kit_name = path.parent.parent.name
    include.append(path.name)

    obj = {
        'include': include,
        'include_path_list': include_path_list,
        'tmp_name': tmp_name,
        'kit_name': kit_name,
        'path': path,
        'action': args.action,
        'outfolder': str(args.outfolder),
        'namespace': args.namespace,
        'generator': args.generator,
        'multi_header': multi_header,
    }
    return Parsed(**obj)


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG,
        datefmt='%H:%M:%S',
        format='%(asctime)s[%(levelname)s][%(name)s.%(funcName)s] %(message)s')

    parser = setup_parser()
    params = parse(parser.parse_args())

    try:
        params.process()
    finally:
        params.clean_tmp()


if __name__ == '__main__':
    main()

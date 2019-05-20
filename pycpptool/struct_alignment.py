import pathlib
from .cindex_parser import Header
from .cindex_node import StructNode


def generate(header: Header, out_path: pathlib.Path, package_name: str,
             multi_header: bool):

    for node in header.nodes:
        if isinstance(node, StructNode):
            if node.field_type == 'struct':
                for f in node.fields:
                    print(f)

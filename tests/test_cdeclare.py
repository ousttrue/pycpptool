import unittest
from pycpptool import cdeclare


class CDeclareTest(unittest.TestCase):
    def test_int(self) -> None:
        decl = cdeclare.parse_declare('int')
        self.assertEquals(decl.type, 'int')

    def test_ptr(self) -> None:
        decl = cdeclare.parse_declare('int*')
        self.assertIsInstance(decl, cdeclare.Pointer)
        self.assertEquals(decl.target.type, 'int')


if __name__ == '__main__':
    unittest.main()
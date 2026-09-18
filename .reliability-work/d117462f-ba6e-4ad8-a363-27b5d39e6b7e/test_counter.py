import unittest

from counter import increment


class TestCounter(unittest.TestCase):
    def test_increment(self) -> None:
        self.assertEqual(increment(1), 2)
        self.assertEqual(increment(0), 1)


if __name__ == "__main__":
    unittest.main()

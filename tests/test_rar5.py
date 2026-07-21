import unittest

from archivekey.rar5 import Rar5FormatError, Rar5Target


class Rar5Tests(unittest.TestCase):
    SYNTHETIC_HASH = (
        "$rar5$16$00112233445566778899aabbccddeeff$15$"
        "00000000000000000000000000000000$8$39f04a13a39eafe7"
    )

    def test_independent_verifier_accepts_known_password(self):
        target = Rar5Target.from_hash(self.SYNTHETIC_HASH)
        self.assertEqual(target.iterations, 32768)
        self.assertTrue(target.matches("BlueRiver#2042!!"))
        self.assertFalse(target.matches("BlueRiver#2042!"))

    def test_rejects_non_rar5_hash(self):
        with self.assertRaises(Rar5FormatError):
            Rar5Target.from_hash("not-a-rar5-hash")


if __name__ == "__main__":
    unittest.main()

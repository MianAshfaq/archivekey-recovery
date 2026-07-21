import unittest

from archivekey.candidates import generate_candidates, generate_ranked_candidates


class CandidateTests(unittest.TestCase):
    def test_exact_candidates_are_first_and_preserved(self):
        result = generate_candidates(
            ["BlueRiver#2042!!", "NorthLake@246%"], ["Blue River"], [2042]
        )
        self.assertEqual(result[:2], ["BlueRiver#2042!!", "NorthLake@246%"])

    def test_generates_personalized_year_pattern(self):
        result = generate_candidates([], ["BlueRiver"], [2042])
        self.assertIn("BlueRiver@2042", result)

    def test_limit_and_uniqueness(self):
        result = generate_candidates(["same", "same"], ["same", "Same"], [2024], 25)
        self.assertEqual(len(result), 25)
        self.assertEqual(len(result), len(set(result)))

    def test_context_alias_and_trailing_symbol_grammar(self):
        result = generate_candidates([], ["United Kingdom"], [2042], 10_000)
        self.assertIn("UK@123%", result)
        self.assertLess(result.index("UK@123%"), 1_000)

    def test_ranked_candidate_explains_rule(self):
        result = generate_ranked_candidates([], ["UK"], [], 5_000)
        candidate = next(item for item in result if item.value == "UK@123%")
        self.assertEqual(candidate.rule, "stem+separator+number+symbol")
        self.assertGreaterEqual(candidate.score, 0)

    def test_repeated_trailing_symbol_rule(self):
        result = generate_ranked_candidates([], ["BlueRiver"], [], 10_000)
        candidate = next(item for item in result if item.value == "BlueRiver@123@@")
        self.assertEqual(candidate.rule, "stem+separator+number+repeated-symbol")
        self.assertLess(result.index(candidate), 1_000)


if __name__ == "__main__":
    unittest.main()

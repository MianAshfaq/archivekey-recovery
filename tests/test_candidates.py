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

    def test_possible_guess_is_mutated_without_separate_clues(self):
        result = generate_ranked_candidates(["BlueRiver@2042!"], [], [2041, 2042], 20_000)
        values = [candidate.value for candidate in result]
        self.assertEqual(values[0], "BlueRiver@2042!")
        self.assertIn("blueriver@2042!", values)
        self.assertIn("BlueRiver@2041!", values)
        self.assertIn("BlueRiver@2042!!", values)
        self.assertGreater(len(result), 1_000)

    def test_possible_guess_is_mixed_with_clue_words(self):
        result = generate_ranked_candidates(
            ["Orion@246%"], ["NorthLake"], [2041, 2042], 30_000
        )
        by_value = {candidate.value: candidate for candidate in result}
        self.assertEqual(by_value["Orion@2041%"].rule, "guess-number-mutation")
        self.assertEqual(by_value["Orion@246%%"].rule, "guess-ending-mutation")
        self.assertEqual(by_value["Orion@NorthLake"].rule, "stem+separator+stem")
        self.assertEqual(by_value["NorthLake@Orion"].rule, "stem+separator+stem")

    def test_community_pack_works_without_personal_hints(self):
        result = generate_ranked_candidates(
            [], [], [2042], 10_000, community=["Archive", "Welcome"]
        )
        by_value = {candidate.value: candidate for candidate in result}
        self.assertEqual(by_value["Archive"].rule, "community-seed")
        self.assertEqual(by_value["Archive@2042"].rule, "community-seed+number")
        self.assertEqual(
            by_value["Archive@2042!"].rule, "community-seed+number+symbol"
        )
        self.assertGreater(len(result), 1_000)

    def test_personal_clue_is_mixed_with_community_seed(self):
        result = generate_ranked_candidates(
            [], ["NorthLake"], [2042], 20_000, community=["Archive"]
        )
        by_value = {candidate.value: candidate for candidate in result}
        self.assertEqual(
            by_value["NorthLake@Archive"].rule, "personal+community-mix"
        )
        self.assertEqual(
            by_value["Archive@NorthLake"].rule, "community+personal-mix"
        )


if __name__ == "__main__":
    unittest.main()

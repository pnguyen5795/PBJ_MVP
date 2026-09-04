import unittest

from app.providers import PROVIDERS, PegasusAnalyzer


class ProviderRegistryTests(unittest.TestCase):
    def test_twelve_labs_is_the_only_registered_analyzer(self):
        self.assertEqual(PROVIDERS, {"pegasus": PegasusAnalyzer})


if __name__ == "__main__":
    unittest.main()

import unittest

from src.stages.parse.search_query_generator import SearchQueryGenerator


class TestSearchQueryGenerator(unittest.TestCase):
    def setUp(self):
        self.generator = SearchQueryGenerator(max_non_searched=100)

    def tearDown(self):
        self.generator.close()

    def test_generate_search_queries(self):
        queries = self.generator.generate_search_queries(count=5)
        self.assertIsInstance(queries, list)
        self.assertEqual(len(queries), 5)
        for query in queries:
            self.assertIsInstance(query, str)
            self.assertGreater(len(query), 0)
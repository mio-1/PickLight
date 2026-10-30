"""Search scopes keep the visible matches tied to the four menu choices."""

import unittest
from pathlib import Path

from picklight.filters import PhotoFilter, SEARCH_SCOPES
from picklight.library import PhotoPair


class SearchScopeTests(unittest.TestCase):
    def setUp(self):
        self.pair = PhotoPair("sample", Path("C:/photos/旅行/JPG/tower.jpg"),
                              Path("C:/photos/旅行/RAW/tower.arw"))

    def test_each_scope_matches_only_its_own_field(self):
        examples = (("name", "tower"), ("folder.name", "旅行"),
                    ("folder.description", "夜景"), ("extension", "arw"))
        for scope, query in examples:
            with self.subTest(scope=scope):
                search = PhotoFilter(path_contains=query, search_scopes={scope})
                self.assertTrue(search.matches(self.pair, 0, False,
                                               folder_description="广州夜景"))
                for other in set(SEARCH_SCOPES) - {scope}:
                    search.search_scopes = {other}
                    self.assertFalse(search.matches(self.pair, 0, False,
                                                    folder_description="广州夜景"))

    def test_no_selected_scope_hides_results_until_query_is_cleared(self):
        search = PhotoFilter(path_contains="tower", search_scopes=set())
        self.assertFalse(search.matches(self.pair, 0, False))
        search.path_contains = ""
        self.assertTrue(search.matches(self.pair, 0, False))

    def test_name_and_extension_together_accept_full_filename(self):
        search = PhotoFilter(path_contains="tower.arw", search_scopes={"name", "extension"})
        self.assertTrue(search.matches(self.pair, 0, False))
        search.search_scopes = {"name"}
        self.assertFalse(search.matches(self.pair, 0, False))


if __name__ == "__main__":
    unittest.main()

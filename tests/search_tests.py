import unittest
from search_service import SolrClient

import server


class SearchTestCase(unittest.TestCase):
    """Test case for search function"""

    def setUp(self):
        self.search = SolrClient("default", server.app.logger)

    def tearDown(self):
        pass

    def check_tokens(self, searchtext, expected):
        (filterword, tokens) = self.search.tokenize(searchtext)
        self.assertEqual(expected, tokens, "Wrong tokens")

    def check_query(self, searchtext, expected):
        (filterword, tokens) = self.search.tokenize(searchtext)
        query = self.search.query_str(tokens)
        self.assertEqual(expected, query, "Wrong Solr query")

    def test_tokenizer(self):
        self.check_tokens("SBB Areal", ['SBB', 'Areal'])
        self.check_tokens("  SBB    Areal", ['SBB', 'Areal'])
        self.check_tokens("SBB Areal, Olten", ['SBB', 'Areal', 'Olten'])
        self.check_tokens("Winz,Moos:5", ['Winz', 'Moos', '5'])
        self.check_tokens("Karte: SBB Areal", ['SBB', 'Areal'])
        self.check_tokens("Karte:SBB Areal", ['SBB', 'Areal'])
        self.check_tokens("Karte:SBB Areal:5", ['SBB', 'Areal', '5'])
        self.check_tokens('SBB"Areal', ['SBB', 'Areal'])

    def test_search_queries(self):
        self.check_query("grenz", 'q=((search_1_stem:"grenz"^6 OR search_1_ngram:"grenz"^5)) OR ((search_2_stem:"grenz"^4 OR search_2_ngram:"grenz"^3)) OR ((search_3_stem:"grenz"^2 OR search_3_ngram:"grenz"^1))')
        self.check_query("grenz 4", 'q=((search_1_stem:"grenz"^6 OR search_1_ngram:"grenz"^5) AND (search_1_stem:"4"^6 OR search_1_ngram:"4"^5)) OR ((search_2_stem:"grenz"^4 OR search_2_ngram:"grenz"^3) AND (search_2_stem:"4"^4 OR search_2_ngram:"4"^3)) OR ((search_3_stem:"grenz"^2 OR search_3_ngram:"grenz"^1) AND (search_3_stem:"4"^2 OR search_3_ngram:"4"^1))')
        self.check_query("Karte:grenz 4", 'q=((search_1_stem:"grenz"^6 OR search_1_ngram:"grenz"^5) AND (search_1_stem:"4"^6 OR search_1_ngram:"4"^5)) OR ((search_2_stem:"grenz"^4 OR search_2_ngram:"grenz"^3) AND (search_2_stem:"4"^4 OR search_2_ngram:"4"^3)) OR ((search_3_stem:"grenz"^2 OR search_3_ngram:"grenz"^1) AND (search_3_stem:"4"^2 OR search_3_ngram:"4"^1))')
        self.check_query("xzy", 'q=((search_1_stem:"xzy"^6 OR search_1_ngram:"xzy"^5)) OR ((search_2_stem:"xzy"^4 OR search_2_ngram:"xzy"^3)) OR ((search_3_stem:"xzy"^2 OR search_3_ngram:"xzy"^1))')
        self.check_query("äöü", 'q=((search_1_stem:"äöü"^6 OR search_1_ngram:"äöü"^5)) OR ((search_2_stem:"äöü"^4 OR search_2_ngram:"äöü"^3)) OR ((search_3_stem:"äöü"^2 OR search_3_ngram:"äöü"^1))')
        self.check_query("OR =^:", 'q=((search_1_stem:"OR"^6 OR search_1_ngram:"OR"^5) AND (search_1_stem:"=^"^6 OR search_1_ngram:"=^"^5)) OR ((search_2_stem:"OR"^4 OR search_2_ngram:"OR"^3) AND (search_2_stem:"=^"^4 OR search_2_ngram:"=^"^3)) OR ((search_3_stem:"OR"^2 OR search_3_ngram:"OR"^1) AND (search_3_stem:"=^"^2 OR search_3_ngram:"=^"^1))')

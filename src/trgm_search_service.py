import json
import os
import re
import time

from flask import json
from jinja2 import Template
from qwc_services_core.database import DatabaseEngine
from qwc_services_core.permissions_reader import PermissionsReader
from qwc_services_core.runtime_config import RuntimeConfig
from sqlalchemy.sql import text as sql_text

from search_resources import SearchResources

FILTERWORD_CHARS = os.environ.get('FILTERWORD_CHARS', r'\w.')
FILTERWORD_RE = re.compile(f'^([{FILTERWORD_CHARS}]+):\b*')

class TrgmClient:
    """SolrClient class
    """

    def __init__(self, tenant, logger):
        """Constructor

        :param Logger logger: Application logger
        """
        self.logger = logger
        self.tenant = tenant

        config_handler = RuntimeConfig("search", logger)
        config = config_handler.tenant_config(tenant)

        self.word_split_re = re.compile(
            config.get('word_split_re', r'[\s,.:;"]+')
        )
        self.default_search_limit = config.get('search_result_limit', 50)
        self.facet_search_limit = config.get('trgm_facet_search_limit', 50)

        self.facets = dict(map(
            lambda facet: [facet['name'], facet],
            config.resources().get('facets', [])
        ))
        self.filterwords = dict(map(
            lambda facet: [facet['filter_word'], facet['name']],
            config.resources().get('facets', [])
        ))

        permissions = PermissionsReader(tenant, logger)
        self.resources = SearchResources(config, permissions)

        self.db_engine = DatabaseEngine()
        self.db_url = config.get('db_url')
        self.filter_word_query = config.get('trgm_filter_word_query')
        self.feature_query = config.get('trgm_feature_query')
        self.feature_query_template = config.get('trgm_feature_query_template')
        self.layer_query = config.get('trgm_layer_query')
        self.layer_query_template = config.get('trgm_layer_query_template')
        self.similarity_threshold = config.get('trgm_similarity_threshold', 0.3)

    def search(self, identity, searchtext, searchfilter, limit):
        (filterword, tokens) = self.tokenize(searchtext)
        if not tokens:
            return {'results': [], 'result_counts': []}
        if filterword:
            searchfilter = [self.filterwords.get(filterword)]

        # Determine permitted facets and dataproducts
        solr_facets = self.resources.solr_facets(identity)
        permitted_dataproducts = self.resources.dataproducts(identity)
        if not searchfilter:
            # use all permitted facets if filter is empty
            search_facets = list(solr_facets.keys())
        else:
            search_facets = [facet for facet in searchfilter if facet in solr_facets]

        search_ds = list(filter(lambda facet: facet not in ["foreground", "background"], search_facets))
        search_dp = list(filter(lambda facet: facet in ["foreground", "background"], search_facets))
        self.logger.debug("Searching in datasets: %s" % ",".join(search_ds))
        self.logger.debug("Search for dataproducts: %s" % ",".join(search_dp))

        if not limit:
            limit = self.default_search_limit

        # Prepare query
        layer_query = self.layer_query
        if self.layer_query_template:
            layer_query = Template(self.layer_query_template).render(
                searchtext=searchtext, words=tokens, facets=search_dp
            )
            self.logger.debug("Generated layer query from template")

        feature_query = self.feature_query
        if self.feature_query_template:
            # NOTE: facet_search_limit + 1: we limit results to facet_search_limit below, but pass + 1 here to
            # be able to detect whether there were actually more results than facet_search_limit
            feature_query = Template(self.feature_query_template).render(
                searchtext=searchtext, words=tokens, facets=search_ds, facetlimit=self.facet_search_limit + 1
            )
            self.logger.debug("Generated feature query from template")

        # Perform search
        layer_results = []
        feature_results = []
        with self.db_engine.db_engine(self.db_url).connect() as conn:

            conn.execute(sql_text("SET pg_trgm.similarity_threshold = :value"), {'value': self.similarity_threshold})

            # Search for layers
            if search_dp and layer_query:
                start = time.time()
                self.logger.debug("Searching for layers: %s" % layer_query)
                layer_results = conn.execute(sql_text(layer_query), {
                    'term': " ".join(tokens), 'terms': tokens, 'thres': self.similarity_threshold, 'facets': search_dp
                }).mappings().all()
                self.logger.debug("Done in %f s" % (time.time() - start))

            # Search for features
            if search_ds and feature_query:
                start = time.time()
                self.logger.debug("Searching for features: %s" % feature_query)
                # NOTE: facet_search_limit + 1: we limit results to facet_search_limit below, but pass + 1 here to
                # be able to detect whether there were actually more results than facet_search_limit
                feature_results = conn.execute(sql_text(feature_query), {
                    'term': " ".join(tokens), 'terms': tokens, 'thres': self.similarity_threshold, 'facets': search_ds, 'facetlimit': self.facet_search_limit + 1
                }).mappings().all()
                self.logger.debug("Done in %f s" % (time.time() - start))

        # Build results
        results = []
        result_counts = {}
        self.logger.debug("Number of layer results: %d" % len(layer_results))
        self.logger.debug("Number of feature results: %d" % len(feature_results))
        for layer_result in layer_results:
            dataproduct_id = layer_result["dataproduct_id"]
            if dataproduct_id not in permitted_dataproducts and '*' not in permitted_dataproducts:
                self.logger.debug("Skipping layer result with missing permission: %s" % dataproduct_id)
            else:
                stacktype = layer_result.get("stacktype", None)
                dataproduct = {
                    "display": layer_result["display"],
                    "dataproduct_id": dataproduct_id,
                    "dset_info": layer_result["dset_info"],
                    "type": "layergroup" if layer_result["sublayers"] else "singleactor",
                    "stacktype": stacktype
                }
                if layer_result["sublayers"]:
                    dataproduct["sublayers"] = json.loads(layer_result["sublayers"])
                results.append({"dataproduct": dataproduct})

                if stacktype:
                    if not stacktype in result_counts:
                        result_counts[stacktype] = {
                            "dataproduct_id": stacktype,
                            "filterword": self.facets.get(stacktype, {}).get('filter_word', stacktype),
                            "count": 0
                        }
                    result_counts[stacktype]["count"] += 1

        feature_result_count = 0
        for feature_result in feature_results:
            if feature_result['facet_id'] in search_ds:
                if not feature_result["facet_id"] in result_counts:
                    result_counts[feature_result["facet_id"]] = {
                        "dataproduct_id": feature_result["facet_id"],
                        "filterword": self.facets.get(feature_result["facet_id"], {}).get('filter_word', feature_result["facet_id"]),
                        "count": 0
                    }
                feature_result_count += 1
                result_counts[feature_result["facet_id"]]["count"] += 1
                if feature_result_count <= limit and result_counts[feature_result["facet_id"]]["count"] <= self.facet_search_limit:
                    results.append({
                        "feature": {
                            "display": feature_result["display"],
                            "dataproduct_id": feature_result["facet_id"],
                            "feature_id": feature_result["feature_id"],
                            "id_field_name": feature_result["id_field_name"],
                            "id_field_type": feature_result.get("id_in_quotes", None),
                            "bbox": json.loads(feature_result["bbox"]) if feature_result["bbox"] else None,
                            "srid": feature_result["srid"]
                        }
                    })

        for facet in result_counts:
            # Search query limited results, the true result count is not known
            if result_counts[facet]["count"] >= self.facet_search_limit:
                result_counts[facet]["count"] = -1

        return {"results": results, "result_counts": list(result_counts.values())}

    def tokenize(self, searchtext):
        match = FILTERWORD_RE.match(searchtext)
        if match:
            st = searchtext[match.span()[1]:]
            return (match.group(1), self.split_words(st))
        else:
            return (None, self.split_words(searchtext))

    def split_words(self, searchtext):
        return list(filter(None, re.split(self.word_split_re, searchtext)))

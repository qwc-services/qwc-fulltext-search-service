import json
import os
import re
import time

from jinja2 import Template
from qwc_services_core.database import DatabaseEngine
from qwc_services_core.permissions_reader import PermissionsReader
from qwc_services_core.runtime_config import RuntimeConfig
from sqlalchemy.sql import literal
from sqlalchemy.sql import text as sql_text

from search_resources import SearchResources

FILTERWORD_CHARS = os.environ.get("FILTERWORD_CHARS", r"\w.")
FILTERWORD_RE = re.compile(f"^([{FILTERWORD_CHARS}]+):\b*")


class PgClient:
    """SolrClient class"""

    def __init__(self, tenant, logger):
        """Constructor

        :param Logger logger: Application logger
        """
        self.logger = logger
        self.tenant = tenant

        config_handler = RuntimeConfig("search", logger)
        config = config_handler.tenant_config(tenant)

        self.word_split_re = re.compile(config.get("word_split_re", r'[\s,.:;"]+'))
        self.default_search_limit = config.get("search_result_limit", 50)
        self.facet_search_limit = config.get("facet_search_limit", 50)
        self.set_search_result_limit_per_facet = config.get("set_search_result_limit_per_facet", False)

        self.filterwords = {facet["filter_word"]: facet["name"] for facet in config.resources().get("facets", [])}

        permissions = PermissionsReader(tenant, logger)
        self.resources = SearchResources(config, permissions)

        self.db_engine = DatabaseEngine()
        self.db_url = config.get("db_url")
        self.filter_word_query = config.get("pg_filter_word_query", config.get("trgm_filter_word_query"))
        self.feature_query = config.get("pg_feature_query")
        self.feature_query_template = config.get("pg_feature_query_template")
        self.layer_query = config.get("pg_layer_query")
        self.layer_query_template = config.get("pg_layer_query_template")
        self.similarity_threshold = config.get("trgm_similarity_threshold", 0.3)

    def sql_escape(self, string):
        return str(
            literal(str(string)).compile(
                dialect=self.db_engine.db_engine(self.db_url).dialect, compile_kwargs={"literal_binds": True}
            )
        )[1:-1]

    def search(self, identity, searchtext, searchfilter, limit):
        (filterword, tokens) = self.tokenize(searchtext)
        if not tokens:
            return {"results": [], "result_counts": []}
        if filterword:
            searchfilter = [self.filterwords.get(filterword)]

        # Determine permitted facets and dataproducts
        search_facets = self.resources.solr_facets(identity)
        permitted_dataproducts = self.resources.dataproducts(identity)
        if searchfilter:
            search_facets = {facetName: facet for facetName, facet in search_facets.items() if facetName in searchfilter}

        search_ds = [facet for facet in search_facets if facet not in ["foreground", "background"]]
        search_dp = [facet for facet in search_facets if facet in ["foreground", "background"]]
        self.logger.debug(f"Searching in datasets: {','.join(search_ds)}")
        self.logger.debug(f"Search for dataproducts: {','.join(search_dp)}")

        if not limit:
            limit = self.default_search_limit

        facetlimit = self.facet_search_limit
        if self.set_search_result_limit_per_facet:
            facetlimit = limit
            limit = None

        # Prepare query
        layer_query = self.layer_query
        if self.layer_query_template:
            layer_query = Template(self.layer_query_template).render(
                searchtext=self.sql_escape(searchtext),
                words=list(map(self.sql_escape, tokens)),
                facets=search_dp,
            )
            self.logger.debug("Generated layer query from template")

        feature_query = self.feature_query
        if self.feature_query_template:
            # NOTE: facet_search_limit + 1: we limit results to facet_search_limit below, but pass + 1 here to
            # be able to detect whether there were actually more results than facet_search_limit
            feature_query = Template(self.feature_query_template).render(
                searchtext=self.sql_escape(searchtext),
                words=list(map(self.sql_escape, tokens)),
                facets=search_ds,
                facetlimit=facetlimit + 1,
            )
            self.logger.debug("Generated feature query from template")

        # Perform search
        layer_results = []
        feature_results = []
        with self.db_engine.db_engine(self.db_url).connect() as conn:
            conn.execute(sql_text("SET pg_trgm.similarity_threshold = :value"), {"value": self.similarity_threshold})

            # Search for layers
            if search_dp and layer_query:
                start = time.time()
                self.logger.debug(f"Searching for layers: {layer_query}")
                params = {
                    "term": " ".join(tokens),
                    "terms": tokens,
                    "thres": self.similarity_threshold,
                    "facets": search_dp,
                }
                layer_results = conn.execute(sql_text(layer_query), params).mappings().all()
                self.logger.debug("Done in %f s" % (time.time() - start))

            # Search for features
            if search_ds and feature_query:
                start = time.time()
                self.logger.debug(f"Searching for features: {feature_query}")
                # NOTE: facet_search_limit + 1: we limit results to facet_search_limit below, but pass + 1 here to
                # be able to detect whether there were actually more results than facet_search_limit
                params = {
                    "term": " ".join(tokens),
                    "terms": tokens,
                    "thres": self.similarity_threshold,
                    "facets": search_ds,
                    "facetlimit": facetlimit + 1,
                }
                feature_results = conn.execute(sql_text(feature_query), params).mappings().all()
                self.logger.debug("Done in %f s" % (time.time() - start))

        # Build results
        results = []
        result_counts = {}
        self.logger.debug(f"Number of layer results: {len(layer_results)}")
        self.logger.debug(f"Number of feature results: {len(feature_results)}")
        for layer_result in layer_results:
            dataproduct_id = layer_result["dataproduct_id"]
            if dataproduct_id not in permitted_dataproducts and "*" not in permitted_dataproducts:
                self.logger.debug(f"Skipping layer result with missing permission: {dataproduct_id}")
            else:
                stacktype = layer_result.get("stacktype", None)
                dataproduct = {
                    "display": layer_result["display"],
                    "dataproduct_id": dataproduct_id,
                    "dset_info": layer_result["dset_info"],
                    "type": "layergroup"
                    if layer_result["sublayers"]
                    else "singleactor",
                    "stacktype": stacktype,
                }
                if layer_result["sublayers"]:
                    dataproduct["sublayers"] = json.loads(layer_result["sublayers"])
                results.append({"dataproduct": dataproduct})

                if stacktype:
                    if stacktype not in result_counts:
                        result_counts[stacktype] = {
                            "dataproduct_id": stacktype,
                            "filterword": search_facets.get(stacktype, {}).get("filter_word", stacktype),
                            "count": 0
                        }
                    result_counts[stacktype]["count"] += 1

        feature_result_count = 0
        for feature_result in feature_results:
            if feature_result["facet_id"] in search_ds:
                if feature_result["facet_id"] not in result_counts:
                    filterword = search_facets.get(
                        feature_result["facet_id"], {}).get("filter_word", feature_result["facet_id"]
                    )
                    result_counts[feature_result["facet_id"]] = {
                        "dataproduct_id": feature_result["facet_id"],
                        "filterword": filterword,
                        "count": 0,
                    }
                feature_result_count += 1
                result_counts[feature_result["facet_id"]]["count"] += 1
                if (
                    (limit is None or feature_result_count <= limit)
                    and result_counts[feature_result["facet_id"]]["count"] <= facetlimit
                ):
                    results.append({
                        "feature": {
                            "display": feature_result["display"],
                            "dataproduct_id": feature_result["facet_id"],
                            "feature_id": feature_result["feature_id"],
                            "id_field_name": feature_result["id_field_name"],
                            "id_field_type": feature_result.get("id_in_quotes", None),
                            "bbox": json.loads(feature_result["bbox"]) if feature_result.get("bbox") else None,
                            "center": json.loads(feature_result["center"]) if feature_result.get("center") else None,
                            "srid": feature_result["srid"],
                        }
                    })

        for facet in result_counts:
            # The search query limited the results, the true result count is not known
            if result_counts[facet]["count"] >= facetlimit + 1:
                result_counts[facet]["count"] = -1

        return {"results": results, "result_counts": list(result_counts.values()), "limit": limit or facetlimit}

    def tokenize(self, searchtext):
        match = FILTERWORD_RE.match(searchtext)
        if match:
            st = searchtext[match.span()[1] :]
            return (match.group(1), self.split_words(st))
        else:
            return (None, self.split_words(searchtext))

    def split_words(self, searchtext):
        return list(filter(None, re.split(self.word_split_re, searchtext)))

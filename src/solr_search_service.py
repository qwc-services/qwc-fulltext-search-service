import os
import re

import requests
from flask import json
from qwc_services_core.permissions_reader import PermissionsReader
from qwc_services_core.runtime_config import RuntimeConfig

from search_resources import SearchResources

FILTERWORD_CHARS = os.environ.get("FILTERWORD_CHARS", r"\w.")
FILTERWORD_RE = re.compile(f"^([{FILTERWORD_CHARS}]+):\b*")

QUERY_PARTS = [
    '(search_1_stem:"{0}"^6 OR search_1_ngram:"{0}"^5)',
    '(search_2_stem:"{0}"^4 OR search_2_ngram:"{0}"^3)',
    '(search_3_stem:"{0}"^2 OR search_3_ngram:"{0}"^1)',
]


class SolrClient:
    """SolrClient class"""

    def __init__(self, tenant, logger):
        """Constructor

        :param Logger logger: Application logger
        """
        self.logger = logger
        self.tenant = tenant

        config_handler = RuntimeConfig("search", logger)
        config = config_handler.tenant_config(tenant)

        self.solr_service_url = config.get("solr_service_url", "http://localhost:8983/solr/gdi/select")

        self.solr_service_auth = config.get("solr_service_auth", None)

        if self.solr_service_auth:
            self.solr_service_auth = (self.solr_service_auth.get("username"), self.solr_service_auth.get("password"))

        self.word_split_re = re.compile(config.get("word_split_re", r'[\s,.:;"]+'))
        self.default_search_limit = config.get("search_result_limit", 50)
        self.search_result_sort = config.get("search_result_sort", "score desc, sort asc")

        permissions = PermissionsReader(tenant, logger)
        self.resources = SearchResources(config, permissions)

    def search(self, identity, searchtext, filter, limit):
        solr_facets = self.resources.solr_facets(identity)
        (filterword, tokens) = self.tokenize(searchtext)
        if not tokens:
            return {"results": [], "result_counts": []}
        filter_ids = filter
        if not filter:
            # use all permitted facets if filter is empty
            filter_ids = list(solr_facets.keys())
        if not limit:
            limit = self.default_search_limit

        response = self.query(tokens, filterword, filter_ids, limit, solr_facets)

        # Return Solr error response
        if type(response) is tuple:
            return response

        self.logger.debug(json.dumps(response, indent=2))
        permitted_dataproducts = self.resources.dataproducts(identity)
        results = []
        result_counts = {}
        tot_result_count = 0
        for doc in response["response"]["docs"]:
            facet = doc["facet"]
            if facet not in result_counts:
                result_counts[facet] = {
                    # rename dataproduct_id to facet!
                    "dataproduct_id": facet,
                    "filterword": solr_facets.get(facet, {}).get("filter_word", facet),
                    "count": 0
                }
            result = None
            if doc["facet"] == "foreground" or doc["facet"] == "background" or doc["facet"] == "dataproduct":
                result = self.layer_result(doc, permitted_dataproducts)
            else:
                result = self.feature_result(doc, filterword, solr_facets)
            if result:
                result_counts[facet]["count"] += 1
                tot_result_count += 1
                if (
                    (limit is None or tot_result_count <= limit)
                    and result_counts[facet]["count"] <= facetlimit
                ):
                    results.append(result)

        for facet in result_counts:
            # The search query limited the results, the true result count is not known
            if result_counts[facet]["count"] >= facetlimit:
                result_counts[facet]["count"] = -1

        return {"results": results, "result_counts": list(result_counts.values())}

    def query(self, tokens, filterword, filter_ids, limit, solr_facets):
        # https://lucene.apache.org/solr/guide/8_1/common-query-parameters.html
        q = self.query_str(tokens)
        fq = self.filter_query_str(filterword, filter_ids, solr_facets)
        response = requests.get(
            self.solr_service_url,
            params=f"omitHeader=true&facet=true&facet.field=facet&sort={self.search_result_sort}&rows={limit}&{q}&{fq}",
            auth=self.solr_service_auth,
            timeout=10
        )
        self.logger.debug(f"Sending Solr query {response.url}")
        self.logger.info("Search words: %s", ",".join(tokens))

        if response.status_code == 200:
            return json.loads(response.content)
        else:
            self.logger.warning(f"Solr Error:\n\n{response.text}")
            return (response.text, response.status_code)

    def tokenize(self, searchtext):
        match = FILTERWORD_RE.match(searchtext)
        if match:
            st = searchtext[match.span()[1] :]
            return match.group(1), self.split_words(st)
        else:
            return None, self.split_words(searchtext)

    def query_str(self, tokens):
        lines = (self.join_word_parts(p, tokens) for p in QUERY_PARTS)
        query = " OR ".join(lines)
        return f"q={query}"

    def filter_query_str(self, filterword, filter_ids, solr_facets):
        if filterword:
            facets = [self.filterword_to_facet(filterword, solr_facets)]
        else:
            # Remove facets without permissions
            facets = list(filter(lambda f: solr_facets.get(f), filter_ids))
            if len(facets) != len(filter_ids):
                self.logger.info("Removed filter ids with missing permissions")
                self.logger.info(f"Passed filter ids: {filter_ids}")
                self.logger.info(f"Permitted filter ids: {facets}")
            # Avoid empty fq
            if len(facets) == 0:
                facets = ["_"]
        facets = (f"facet:{f}" for f in facets)
        facet_query = " OR ".join(facets)
        fq = f"fq=tenant:{self.tenant}"
        if facet_query:
            fq += f" AND ({facet_query})"
        return fq

    def filterword_to_facet(self, filterword, solr_facets):
        for facet, entries in solr_facets.items():
            # filterword lookup table should be cached
            for entry in entries:
                if self.check_filterword(filterword, entry):
                    return facet
        self.logger.info(f"Filterword not found: {filterword}")
        return "_"

    def layer_result(self, doc, permitted_dataproducts):
        id = json.loads(doc["id"])
        dataproduct_id = id[1]

        # skip layer without permissions
        if dataproduct_id not in permitted_dataproducts and "*" not in permitted_dataproducts:
            self.logger.debug(f"Skipping layer result with missing permission: {dataproduct_id}")
            return None

        layer = {
            "display": doc["display"],
            "type": id[0],
            "stacktype": doc["facet"],
            "dataproduct_id": dataproduct_id,
            "dset_info": doc["dset_info"],
        }
        if "dset_children" in doc:
            sublayers = []
            children = json.loads(doc["dset_children"])
            for child in children:
                child_ident = child["ident"]
                if child_ident in permitted_dataproducts or "*" in permitted_dataproducts:
                    sublayers.append({
                        "display": child["display"],
                        "type": child["subclass"],
                        "dataproduct_id": child_ident,
                        "dset_info": child["dset_info"],
                    })
                else:
                    self.logger.debug(f"Skipping child layer with missing permission: {child_ident}")
            layer["sublayers"] = sublayers

        return {"dataproduct": layer}

    def feature_result(self, doc, filterword, solr_facets):
        id = json.loads(doc["id"])
        idfield_meta = json.loads(doc["idfield_meta"])
        idfield_str = idfield_meta[1].split(":")[1] == "y"
        bbox = json.loads(doc["bbox"]) if "bbox" in doc else None
        center = json.loads(doc["center"]) if "center" in doc else None
        srid = doc.get("srid", None)

        facet = id[0]  # Solr index uses dataset id as facet
        feature_id = id[1]
        if not idfield_str:
            try:
                feature_id = int(id[1])
            except Exception as e:
                self.logger.error(f"Error converting feature_id to int: {e}")
                idfield_str = True

        # Return only permitted facets
        for entry in solr_facets.get(facet, []):
            if self.check_filterword(filterword, entry):
                return self._feature_rec(doc, idfield_meta, facet, feature_id, idfield_str, bbox, center, srid)

        return {}

    def _feature_rec(self, doc, idfield_meta, facet, feature_id, idfield_str, bbox, center, srid):
        id_field_name = idfield_meta[0]
        feature = {
            "display": doc["display"],
            "dataproduct_id": facet,
            "feature_id": feature_id,
            "id_field_name": id_field_name,
            "id_field_type": idfield_str,
            "bbox": bbox,
            "center": center,
            "srid": srid,
        }
        return {"feature": feature}

    def check_filterword(self, filterword, entry):
        return not filterword or (entry["filter_word"].lower() == filterword.lower())

    def split_words(self, searchtext):
        return list(filter(None, re.split(self.word_split_re, searchtext)))

    def join_word_parts(self, part, tokens):
        parts = [part.format(t) for t in tokens]
        return f"({' AND '.join(parts)})"

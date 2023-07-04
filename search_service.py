import re
import os
import requests
from qwc_services_core.permissions_reader import PermissionsReader
from qwc_services_core.runtime_config import RuntimeConfig
from flask import json, request


FILTERWORD_CHARS = os.environ.get('FILTERWORD_CHARS', '\w.')
FILTERWORD_RE = re.compile(f'^([{FILTERWORD_CHARS}]+):\b*')

QUERY_PARTS = ['(search_1_stem:"{0}"^6 OR search_1_ngram:"{0}"^5)',
               '(search_2_stem:"{0}"^4 OR search_2_ngram:"{0}"^3)',
               '(search_3_stem:"{0}"^2 OR search_3_ngram:"{0}"^1)']


class SolrClient:
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

        self.solr_service_url = config.get(
            'solr_service_url', 'http://localhost:8983/solr/gdi/select')
        self.word_split_re = re.compile(
            config.get('word_split_re', r'[\s,.:;"]+')
        )
        self.default_search_limit = config.get('search_result_limit', 50)
        self.search_result_sort = config.get('search_result_sort', 'score desc, sort asc')

        self.resources = self.load_resources(config)
        self.permissions_handler = PermissionsReader(tenant, logger)

    def search(self, identity, searchtext, filter, limit):
        search_permissions = self.search_permissions(identity)
        (filterword, tokens) = self.tokenize(searchtext)
        filter_ids = filter
        if not filter:
            # use all permitted facets if filter is empty
            filter_ids = search_permissions.keys()
        if not limit:
            limit = self.default_search_limit

        response = self.query(tokens, filterword, filter_ids, limit,
                              search_permissions)
        # Return Solr error response
        if type(response) is tuple:
            return response

        self.logger.debug(json.dumps(response, indent=2))
        permitted_dataproducts = self.dataproduct_permissions(identity)
        results = []
        num_solr_results_dp = 0
        for doc in response['response']['docs']:
            if doc['facet'] == 'foreground' or doc['facet'] == 'background' or doc['facet'] == 'dataproduct':
                num_solr_results_dp += 1
                result = self.layer_result(doc, permitted_dataproducts)
                if result is not None:
                    results.append(result)
            else:
                results.append(
                    self.feature_result(doc, filterword, search_permissions))

        result_counts = self.result_counts(
            response, filterword, num_solr_results_dp, search_permissions)

        return {'results': results, 'result_counts': result_counts}

    def query(self, tokens, filterword, filter_ids, limit,
              search_permissions):
        # https://lucene.apache.org/solr/guide/8_1/common-query-parameters.html
        q = self.query_str(tokens)
        fq = self.filter_query_str(filterword, filter_ids,
                                   search_permissions)
        response = requests.get(
            self.solr_service_url,
            params="omitHeader=true&facet=true&facet.field=facet&sort=" +
                   self.search_result_sort + "&rows={}&{}&{}".format(limit, q, fq),
            timeout=10)
        self.logger.debug("Sending Solr query %s" % response.url)
        self.logger.info("Search words: %s", ','.join(tokens))

        if response.status_code == 200:
            return json.loads(response.content)
        else:
            self.logger.warning("Solr Error:\n\n%s" % response.text)
            return (response.text, response.status_code)

    def tokenize(self, searchtext):
        match = FILTERWORD_RE.match(searchtext)
        if match:
            st = searchtext[match.span()[1]:]
            return (match.group(1), self.split_words(st))
        else:
            return (None, self.split_words(searchtext))

    def query_str(self, tokens):
        lines = map(lambda p: self.join_word_parts(p, tokens), QUERY_PARTS)
        query = ' OR '.join(lines)
        return 'q=%s' % query

    def filter_query_str(self, filterword, filter_ids,
                         search_permissions):
        if filterword:
            facets = [self.filterword_to_facet(filterword, search_permissions)]
        elif '*' in search_permissions:
            # all allowed, facet = filterword
            facets = filter_ids
        else:
            # Remove facets without permissions
            facets = list(filter(lambda f: search_permissions.get(f), filter_ids))
            if len(facets) != len(filter_ids):
                self.logger.info("Removed filter ids with missing permissions")
                self.logger.info("Passed filter ids: %s" % filter_ids)
                self.logger.info("Permitted filter ids: %s" % facets)
            # Avoid empty fq
            if len(facets) == 0:
                facets = ['_']
        facets = map(lambda f: 'facet:%s' % f, facets)
        facet_query = ' OR '.join(facets)
        fq = 'fq=tenant:%s' % self.tenant
        if facet_query:
            fq += ' AND (%s)' % facet_query
        return fq

    def filterword_to_facet(self, filterword, search_permissions):
        if '*' in search_permissions:
            # all allowed, facet = filterword
            return filterword
        for facet, entries in search_permissions.items():
            # filterword lookup table should be cached
            for entry in entries:
                if self.check_filterword(filterword, entry):
                    return facet
        self.logger.info("Filterword not found: %s" % filterword)
        return '_'

    def layer_result(self, doc, permitted_dataproducts):
        id = json.loads(doc['id'])
        dataproduct_id = id[1]

        # skip layer without permissions
        if dataproduct_id not in permitted_dataproducts:
            self.logger.debug("Skipping layer result with "
                              "missing permission: %s" % dataproduct_id)
            return None

        layer = {
            'display': doc['display'],
            'type': id[0],
            'stacktype': doc['facet'],
            'dataproduct_id': dataproduct_id,
            'dset_info': doc['dset_info']
        }
        if 'dset_children' in doc:
            sublayers = []
            children = json.loads(doc['dset_children'])
            for child in children:
                child_ident = child['ident']
                if child_ident in permitted_dataproducts:
                    sublayers.append({
                        'display': child['display'],
                        'type': child['subclass'],
                        'dataproduct_id': child_ident,
                        'dset_info': child['dset_info']
                        })
                else:
                    self.logger.debug("Skipping child layer with "
                                      "missing permission: %s" % child_ident)
            layer['sublayers'] = sublayers

        return {'dataproduct': layer}

    def feature_result(self, doc, filterword, search_permissions):
        id = json.loads(doc['id'])
        idfield_meta = json.loads(doc['idfield_meta'])
        idfield_str = idfield_meta[1].split(':')[1] == 'y'
        bbox = json.loads(doc['bbox']) if 'bbox' in doc else None

        facet = id[0]  # Solr index uses dataset id as facet
        feature_id = id[1]
        if not idfield_str:
            try:
                feature_id = int(id[1])
            except Exception as e:
                self.logger.error("Error converting feature_id to int: %s" % e)
                idfield_str = True

        if '*' in search_permissions:
                return self._feature_rec(
                    doc, idfield_meta, facet, feature_id, idfield_str, bbox)

        # Return only permitted facets
        for entry in search_permissions.get(facet, []):
            if self.check_filterword(filterword, entry):
                return self._feature_rec(
                    doc, idfield_meta, facet, feature_id, idfield_str, bbox)
        return {}

    def _feature_rec(self, doc, idfield_meta, facet, feature_id,
                     idfield_str, bbox):
        id_field_name = idfield_meta[0]
        feature = {
            'display': doc['display'],
            'dataproduct_id': facet,
            'feature_id': feature_id,
            'id_field_name': id_field_name,
            'id_field_type': idfield_str,
            'bbox': bbox
        }
        return {'feature': feature}

    def result_counts(self, response, filterword, num_solr_results_dp,
                      search_permissions):
        result_counts = []
        facet_counts = response['facet_counts']['facet_fields']['facet']
        for i in range(0, len(facet_counts), 2):
            count = facet_counts[i+1]
            if count > 0:
                facet = facet_counts[i]
                if facet == 'foreground' or facet == 'background' or facet == 'dataproduct':
                    # dataproduct Count from Solr does not consider permissions
                    if count <= num_solr_results_dp:
                        # Don't return count if all results already included
                        continue
                    count = None
                if '*' in search_permissions:
                    result_counts.append({
                        'dataproduct_id': facet,
                        'filterword': facet,
                        'count': count
                    })
                else:
                    # Return multiple results if facet is used for multiple dataproducts
                    for entry in search_permissions.get(facet, []):
                        if self.check_filterword(filterword, entry):
                            result_counts.append({
                                'dataproduct_id': facet,
                                # rename dataproduct_id to facet!
                                'filterword': entry['filter_word'],
                                'count': count
                            })
        return result_counts

    def check_filterword(self, filterword, entry):
        return not filterword or (
               entry['filter_word'].lower() == filterword.lower())

    def load_resources(self, config):
        """Load service resources from config.

        :param RuntimeConfig config: Config handler
        """
        # collect service resources (group by facet name)
        facets = {}
        for facet in config.resources().get('facets', []):
            if facet['name'] not in facets:
                facets[facet['name']] = []
            facets[facet['name']].append(facet)

        return {
            'facets': facets
        }

    def search_permissions(self, identity):
        """Return permitted search facets.

        :param str identity: User identity
        """
        # get permitted facets
        permitted_facets = self.permissions_handler.resource_permissions(
            'solr_facets', identity
        )
        # unique set
        permitted_facets = set(permitted_facets)

        # filter by permissions
        facets = {}
        for facet in self.resources['facets']:
            if facet in permitted_facets:
                facets[facet] = self.resources['facets'][facet]

        return facets

    def dataproduct_permissions(self, identity):
        """Return permitted dataproducts.

        :param str identity: User identity
        """
        # get permitted dataproducts
        permitted_dataproducts = self.permissions_handler.resource_permissions(
            'dataproducts', identity
        )

        # return unique sorted dataproducts
        return sorted(list(set(permitted_dataproducts)))

    def split_words(self, searchtext):
        return list(filter(None, re.split(self.word_split_re, searchtext)))

    def join_word_parts(self, part, tokens):
        parts = map(lambda t: part.format(t), tokens)
        return '(%s)' % ' AND '.join(parts)

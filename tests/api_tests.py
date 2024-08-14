import json
import os
import unittest

from flask import Response, json
from flask.testing import FlaskClient
from flask_jwt_extended import JWTManager, create_access_token

import server


class ApiTestCase(unittest.TestCase):
    """Test case for server API"""

    def setUp(self):
        server.app.testing = True
        self.app = FlaskClient(server.app, Response)
        JWTManager(server.app)

    def tearDown(self):
        pass

    def jwtHeader(self):
        with server.app.test_request_context():
            access_token = create_access_token('test')
        return {'Authorization': 'Bearer {}'.format(access_token)}

    def get(self, url):
        """Send GET request and return status code and decoded JSON from
        response.
        """
        response = self.app.get(url, headers=self.jwtHeader())
        return response.status_code, response.data

    def test_search(self):
        # Test API with Trigram backend and dummy SQL queries
        os.environ["SEARCH_BACKEND"] = "trgm"
        os.environ["TRGM_FEATURE_QUERY"] = "UNION ALL".join(list(map(lambda x: """
            SELECT
                :term AS display,
                %d AS feature_id,
                'test_dataset' AS facet_id,
                'test_dataset_id' AS id_field_name,
                '[-180,-90,180,90]' AS bbox,
                'EPSG:4326' AS srid
        """ % x[0], enumerate([None] * 20))))

        os.environ["TRGM_LAYER_QUERY"] = """
            SELECT
                :term AS display,
                'test_dataproduct' AS dataproduct_id,
                True AS dset_info,
                 '[{"ident": "test_dataproduct_sublayer", "display": "Test sublayer", "dset_info": true}]' AS sublayers
        """
        os.environ["SEARCH_RESULT_LIMIT"] = "10"

        # Test result returned for matching filter
        status_code, json_data = self.get(
            '/fts/?filter=test_dataset,dataproduct&searchtext=searchstring')
        data = json.loads(json_data)
        self.assertEqual(200, status_code, "Status code is not OK")
        self.assertEqual(len(data["results"]), 11)

        self.assertEqual(data["feature_result_count"], 20)
        self.assertEqual(data["layer_result_count"], 1)

        features = list(filter(lambda result: result.get("feature", None), data["results"]))
        self.assertEqual(len(features), 10)
        feature = features[0]["feature"]
        self.assertEqual(feature['display'], 'searchstring')
        self.assertTrue(feature.get('feature_id', None) != None)
        self.assertEqual(feature['dataproduct_id'], 'test_dataset')
        self.assertEqual(feature['id_field_name'], 'test_dataset_id')
        self.assertEqual(feature['bbox'], [-180,-90,180,90])
        self.assertEqual(feature['srid'], 'EPSG:4326')

        dataproducts = list(filter(lambda result: result.get("dataproduct", None), data["results"]))
        self.assertEqual(len(dataproducts), 1)
        dataproduct = dataproducts[0]["dataproduct"]
        self.assertEqual(dataproduct['display'], 'searchstring')
        self.assertEqual(dataproduct['dataproduct_id'], 'test_dataproduct')
        self.assertEqual(dataproduct['dset_info'], True)

        # Test no result returned for no matching filter
        status_code, json_data = self.get(
            '/fts/?filter=other_dataset&searchtext=searchstring')
        data = json.loads(json_data)
        self.assertEqual(200, status_code, "Status code is not OK")
        self.assertEqual(data["feature_result_count"], 0)
        self.assertEqual(len(data["results"]), 0)

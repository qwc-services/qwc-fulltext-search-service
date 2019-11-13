from flask import Flask, Request as RequestBase, request
from flask_restplus import Api, Resource, fields, reqparse
from flask_jwt_extended import JWTManager, jwt_optional, get_jwt_identity
from werkzeug.exceptions import BadRequest
import os

from qwc_services_core.api import create_model, CaseInsensitiveArgument
from qwc_services_core.jwt import jwt_manager
from search_service import SolrClient  # noqa: E402


# Flask application
app = Flask(__name__)

solr_client = SolrClient(app.logger)

DEFAULT_SEARCH_LIMIT = os.getenv("SEARCH_RESULT_LIMIT", "50")

api = Api(app, version='1.0', title='Fulltext Search service API',
          description="""API for QWC Fulltext Search service.

Faceted fulltext search API.

**Structure of search service response:**

    {
      "results": [                             /* Ordered list of result items */
        {
          "feature": {                         /* Feature result item */
            "dataproduct_id": "<string>",      /* Dataproduct identifier, e.g. ch.so.agi.grundbuchplan */
            "id_field_name": "<string>",       /* Feature ID field name */
            "id_field_type": <bool>,           /* True: String type, False: Non-String type */
            "feature_id": "<string>",          /* Value of feature ID column, e.g. 13275442 */
            "display": "<string>",             /* Text to display in search result list */
            "bbox": "<string>"                 /* Bounding box of feature geomtry. e.g. [2600000,1200000,2600100,1200100] */
          }
        },
        {
          "dataproduct": {                     /* Dataproduct result item */
            "type": "<dataproduct_type>",      /* Type of result item: "datasetview", "layergroup", "facadelayer" */
            "stacktype"': "<stacktype>",       /* "foreground" or "background"
            "dataproduct_id": "<string>",      /* Dataproduct identifier, e.g. ch.so.agi.grundbuchplan */
            "display": "<string>",             /* Text to display in search result list */
            "dset_info": "<bool>",             /* Layer description available */
            "sublayers": [                     /* Optional: children of layergroup */
              {
                "dataproduct_id": "<string>",  /* Dataproduct identifier, e.g. ch.so.agi.grundbuchplan */
                "display": "<string>"          /* Display name of layer */
                "dset_info": "<bool>",         /* Layer description available */
              }
            ]
          }
        },
        {...}
      ],
      "result_counts": [
        {
          "dataproduct_id": "<string>",         /* Dataproduct identifier, e.g. ch.so.agi.grundbuchplan */
          "filterword": "<string>",             /* Filter prefix keyword */
          "count": <int>                        /* Number of features */
        },
        {
          "dataproduct_id": "dataproduct",      /* Special key for dataproducts (layers) */
          "filterword": "<string>",             /* Filter prefix keyword */
          "count": <int>                        /* Number of features */
        },
        {...}
      ]
    }
          """,
          default_label='Search operations', doc='/api/'
          )
app.config.SWAGGER_UI_DOC_EXPANSION = 'list'
# disable verbose 404 error message
app.config['ERROR_404_HELP'] = False

# Setup the Flask-JWT-Extended extension
jwt = jwt_manager(app, api)


# routes
@api.route('/search')
class SearchResult(Resource):
    @api.doc('search')
    @api.param('searchtext', 'Search string with optional filter prefix')
    @api.param('filter', 'Comma separated list of dataproduct identifiers and keyword "dataproduct"')
    @api.param('limit', 'Max number of results')
    @jwt_optional
    def get(self):
        """Search for searchtext and return the results
        """
        searchtext = request.args.get('searchtext', None)
        filter_param = request.args.get('filter', "")
        limit = request.args.get('limit', DEFAULT_SEARCH_LIMIT)
        try:
            if limit:
                limit = int(limit)
                if limit <= 0:
                    limit = None
        except ValueError:
            limit = None

        # split filter and trim whitespace
        filter = [s.strip() for s in filter_param.split(',')]
        # remove empty strings
        filter = [s for s in filter if len(s) > 0]

        result = solr_client.search(get_jwt_identity(), searchtext, filter, limit)

        return result


# local webserver
if __name__ == '__main__':
    print("Starting Search service...")
    app.run(host='localhost', port=5011, debug=True)

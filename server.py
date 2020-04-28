from flask import Flask, Request as RequestBase, request, jsonify
from flask_restplus import Api, Resource, fields, reqparse
from flask_jwt_extended import JWTManager, jwt_optional, get_jwt_identity
from werkzeug.exceptions import BadRequest

from qwc_services_core.api import create_model, CaseInsensitiveArgument
from qwc_services_core.jwt import jwt_manager
from qwc_services_core.tenant_handler import TenantHandler
from search_service import SolrClient  # noqa: E402
from search_geom_service import SearchGeomService  # noqa: E402

# Flask application
app = Flask(__name__)

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

tenant_handler = TenantHandler(app.logger)


def search_handler():
    tenant = tenant_handler.tenant()
    handler = tenant_handler.handler('search', 'fts', tenant)
    if handler is None:
        handler = tenant_handler.register_handler(
            'fts', tenant, SolrClient(tenant, app.logger))
    return handler


def search_geom_handler():
    tenant = tenant_handler.tenant()
    handler = tenant_handler.handler('search', 'geom', tenant)
    if handler is None:
        handler = tenant_handler.register_handler(
            'geom', tenant, SearchGeomService(tenant, app.logger))
    return handler


# base route (should be '/', but doesn't work with flask_restplus)
@api.route('/fts/')
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
        limit = request.args.get('limit', None)
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

        handler = search_handler()
        result = handler.search(get_jwt_identity(), searchtext, filter, limit)

        return result


@api.route('/geom/<dataset>/')
@api.response(400, 'Bad request')
@api.response(404, 'Dataset not found or permission error')
@api.param('dataset', 'Identifier of dataset. Example: `"ne_10m_admin_0_countries"`')
class GeomResult(Resource):
    @api.doc('geom')
    @api.param('filter', 'JSON serialized array of filter expressions: `[["attr", "op", "value"], "and/or", ["attr", "op", "value"]]`')
    @jwt_optional
    def get(self, dataset):
        """Get dataset geometries

        Return dataset geometries with where clause filters.

        The matching features are returned as GeoJSON FeatureCollection.
        """
        filterexpr = request.args.get('filter')
        handler = search_geom_handler()
        result = handler.query(
          get_jwt_identity(), dataset, filterexpr)
        if 'error' not in result:
            return result['feature_collection']
        else:
            error_code = result.get('error_code') or 404
            api.abort(error_code, result['error'])


""" readyness probe endpoint """
@app.route("/ready", methods=['GET'])
def ready():
    return jsonify({"status": "OK"})


""" liveness probe endpoint """
@app.route("/healthz", methods=['GET'])
def healthz():
    return jsonify({"status": "OK"})


# local webserver
if __name__ == '__main__':
    print("Starting Search service...")
    app.run(host='localhost', port=5011, debug=True)

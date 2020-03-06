QWC Fulltext Search Service
===========================

Faceted fulltext search and geometry retrieval for search results.


Dependencies
------------

* Solr search service
* Config service (`CONFIG_SERVICE_URL`)


Configuration
-------------

The static config and permission files are stored as JSON files in `$CONFIG_PATH` with subdirectories for each tenant, 
e.g. `$CONFIG_PATH/default/*.json`. The default tenant name is `default`.

### Search Service config

* [JSON schema](schemas/qwc-search-service.json)
* File location: `$CONFIG_PATH/<tenant>/searchConfig.json`

Example:
```json
{
  "$schema": "https://raw.githubusercontent.com/qwc-services/qwc-fulltext-search-service/master/schemas/qwc-search-service.json",
  "service": "search",
  "config": {
    "solr_service_url": "http://localhost:8983/solr/gdi/select",
    "search_id_col": "id_in_class",
    "word_split_re": "[\\s,.:;\"]+",
    "search_result_limit": 50,
    "geodb_url": "postgresql:///?service=qwc_geodb",
    "search_view_name": "qwc_geodb.search_v",
    "geometry_column": "geom",
    "search_geom_srid": 3857
  },
  "resources": {
    "facets": [
      {
        "name": "background",
        "filter_word": "Background"
      },
      {
        "name": "foreground",
        "filter_word": "Map"
      },
      {
        "name": "ne_10m_admin_0_countries",
        "filter_word": "Country"
      }
    ]
  }
}
```

### Permissions

* File location: `$CONFIG_PATH/<tenant>/permissions.json`

Example:
```json
{
  "users": [
    {
      "name": "demo",
      "groups": ["demo"],
      "roles": []
    }
  ],
  "groups": [
    {
      "name": "demo",
      "roles": ["demo"]
    }
  ],
  "roles": [
    {
      "role": "public",
      "permissions": {
        "dataproducts": [
          "qwc_demo"
        ],
        "solr_facets": [
          "foreground",
          "ne_10m_admin_0_countries"
        ]
      }
    },
    {
      "role": "demo",
      "permissions": {
        "dataproducts": [],
        "solr_facets": []
      }
    }
  ]
}
```

### Environment variables

Config options in the config file can be overridden by equivalent uppercase environment variables.

| Variable                | Description                                 | Default value                           |
|-------------------------|---------------------------------------------|-----------------------------------------|
| SOLR_SERVICE_URL        | SOLR service URL                            | `http://localhost:8983/solr/gdi/select` |
| SEARCH_ID_COL           | ID column name of search view               | `id_in_class`                           |
| WORD_SPLIT_RE           | Word split Regex                            | `[\s,.:;"]+`                            |
| SEARCH_RESULT_LIMIT     | Result count limit per search               | `50`                                    |
| GEODB_URL               | DB connection for search geometries view    |                                         |
| SEARCH_VIEW_NAME        | View for search geometries                  | `search_v`                              |
| GEOMETRY_COLUMN         | Geometry column for search geometries view  | `geom`                                  |
| SEARCH_GEOM_SRID        | SRID for search geometries view             |                                         |


Solr Setup
----------

Solr Administration User Interface: http://localhost:8983/solr/

Core overview: http://localhost:8983/solr/#/gdi/core-overview

Solr Ref guide: https://lucene.apache.org/solr/guide/8_0/
Indexing: https://lucene.apache.org/solr/guide/8_0/uploading-structured-data-store-data-with-the-data-import-handler.html#dataimporthandler-commands

`solr-precreate` creates core in `/var/solr/data/gdi`.
After a configuration change remove the content of `/var/solr/data`
e.g. with `sudo rm -rf volumes/solr/data/*`

    curl 'http://localhost:8983/solr/gdi/dih_geodata?command=full-import'
    curl 'http://localhost:8983/solr/gdi/dih_geodata?command=status'
    curl 'http://localhost:8983/solr/gdi/select?q=search_1_stem:austr*'

    curl 'http://localhost:8983/solr/gdi/dih_metadata?command=full-import&clean=false'
    curl 'http://localhost:8983/solr/gdi/dih_metadata?command=status'
    curl 'http://localhost:8983/solr/gdi/select?q=search_1_stem:qwc_demo'

Usage/Development
-----------------

Set the `CONFIG_PATH` environment variable to the path containing the service config and permission files when starting this service (default: `config`).

Configure environment:

    echo FLASK_ENV=development >.flaskenv

Start service:

    SEARCH_ID_COL=id_in_class python server.py

Search base URL:

    http://localhost:5011/

Search API:

    http://localhost:5011/api/

Examples:

    curl 'http://localhost:5011/fts/?filter=foreground,ne_10m_admin_0_countries&searchtext=austr'
    curl 'http://localhost:5011/fts/?filter=foreground,ne_10m_admin_0_countries&searchtext=qwc'

    curl -g 'http://localhost:5011/geom/ne_10m_admin_0_countries/?filter=[["id_in_class","=",90]]'


Testing
-------

Run all tests:

    python test.py

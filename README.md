[![Actions](https://github.com/qwc-services/qwc-fulltext-search-service/workflows/build/badge.svg)](https://github.com/qwc-services/qwc-fulltext-search-service/actions)
[![docker](https://img.shields.io/docker/v/sourcepole/qwc-fulltext-search-service?label=Docker%20image&sort=semver)](https://hub.docker.com/r/sourcepole/qwc-fulltext-search-service)

QWC Fulltext Search Service
===========================

Faceted fulltext search and geometry retrieval for search results, with two backend options:

- Apache Solr
- Postgresql with Trigram extension

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
    "search_backend": "solr",
    "solr_service_url": "http://localhost:8983/solr/gdi/select",
    "solr_service_auth": {
      "username": "solr",
      "password": "SolrRocks"
    },
    "search_result_sort": "score desc, sort asc",
    "word_split_re": "[\\s,.:;\"]+",
    "search_result_limit": 50,
    "db_url": "postgresql:///?service=qwc_geodb"
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
        "filter_word": "Country",
        "table_name": "qwc_geodb.ne_10m_admin_0_countries",
        "geometry_column": "geom",
        "facet_column": "subclass"
      }
    ]
  }
}
```

### Environment variables

Config options in the config file can be overridden by equivalent uppercase environment variables.

In addition, the following environment variables are supported:

| Name                 | Default       | Description                                                   |
|----------------------|---------------|---------------------------------------------------------------|
| `FILTERWORD_CHARS  ` | `\w.`         | Characters which should be captured in the filter word regex. |

### Permissions

* [JSON schema](https://github.com/qwc-services/qwc-services-core/blob/master/schemas/qwc-services-permissions.json)
* File location: `$CONFIG_PATH/<tenant>/permissions.json`

Example:
```json
{
  "$schema": "https://raw.githubusercontent.com/qwc-services/qwc-services-core/master/schemas/qwc-services-permissions.json",
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

### Solr backend

You can choose the solr backend by setting

    "search_backend": "solr"

in the search service config.

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

If you encounter permission problems with the solr service then try the following command:

    chown 8983:8983 volumes/solr/data

### Postgres backend

You can choose the pg backend by setting

    "search_backend": "pg"

and setting the `pg_feature_query`, `pg_layer_query` variables. See also the [Search chapter in the qwc-services documentation](https://qwc-services.github.io/master/topics/Search/#configuring-the-fulltext-search-service).

Run locally
-----------

Install dependencies and run:

    export CONFIG_PATH=<CONFIG_PATH>
    export SOLR_SERVICE_URL=http://localhost:8983/solr/gdi/select
    uv run src/server.py

To use configs from a `qwc-docker` setup, set `CONFIG_PATH=<...>/qwc-docker/volumes/config`.

Set `FLASK_DEBUG=1` for additional debug output.

Set `FLASK_RUN_PORT=<port>` to change the default port (default: `5000`).

API documentation:

    http://localhost:5000/api/

Examples:

    curl 'http://localhost:5000/?filter=foreground,ne_10m_admin_0_countries&searchtext=austr'
    curl 'http://localhost:5000/?searchtext=Country:austr'
    curl 'http://localhost:5000/?filter=foreground,ne_10m_admin_0_countries&searchtext=qwc'
    curl 'http://localhost:5000/geom/ne_10m_admin_0_countries/?filter=[["ogc_fid","=",90]]'

Docker usage
------------

The Docker image is published on [Dockerhub](https://hub.docker.com/r/sourcepole/qwc-fulltext-search-service).

See sample [docker-compose.yml](https://github.com/qwc-services/qwc-docker/blob/master/docker-compose-example.yml) of [qwc-docker](https://github.com/qwc-services/qwc-docker).

Testing
-------

Run all tests:

    PYTHONPATH=$PWD/src uv run test.py

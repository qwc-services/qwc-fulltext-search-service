QWC Fulltext Search Service
===========================

Faceted fulltext search and geometry retrieval for search results.


Dependencies
------------

* Solr search service
* Config service (`CONFIG_SERVICE_URL`)


Configuration
-------------

### Environment variables


| Variable                | Description                   | Default value                         |
|-------------------------|-------------------------------|---------------------------------------|
| SOLR_SERVICE_URL        | SOLR service URL              | http://localhost:8983/solr/gdi/select |
| SEARCH_RESULT_LIMIT     | Result count limit per search | 50                                    |
| SEARCH_ID_COL           | ID column name of search view |                                       |
| WORD_SPLIT_RE           | Word split Regexp             | [\s,.:;"]+                            |


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

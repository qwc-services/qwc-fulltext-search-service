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
| WORD_SPLIT_RE           | Word split Regexp             | [\s,.:;"]+                            |


Usage/Development
-----------------

Configure environment:

    echo FLASK_ENV=development >.flaskenv

Start service:

    python server.py

Search base URL:

    http://localhost:5011/

Search API:

    http://localhost:5011/api/

Examples:

    curl 'http://localhost:5011/?filter=dataproduct,ch.so.agi.gemeindegrenzen&searchtext=olten'
    curl 'http://localhost:5011/?filter=dataproduct,ch.so.afu.fliessgewaesser.netz&searchtext=boden'


Testing
-------

Run all tests:

    python test.py

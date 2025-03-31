from collections import OrderedDict
import os
import re
from flask import json
from uuid import UUID
from sqlalchemy.sql import text as sql_text
from qwc_services_core.permissions_reader import PermissionsReader
from qwc_services_core.runtime_config import RuntimeConfig
from qwc_services_core.database import DatabaseEngine


class SearchGeomService():
    """SearchGeomService class

    Subset of Data Service for getting feature geometries.
    """

    def __init__(self, tenant, logger):
        """Constructor

        :param Logger logger: Application logger
        """
        self.logger = logger

        config_handler = RuntimeConfig("search", logger)
        config = config_handler.tenant_config(tenant)
        self.resources = self._load_resources(config)
        self.permissions_handler = PermissionsReader(tenant, logger)

        self.db_engine = DatabaseEngine()
        self.dbs = {}   # db connections with db_url as key
        self.default_db_url = config.get('db_url')

    def _get_db(self, cfg):
        db_url = cfg.get('db_url', self.default_db_url)
        if db_url not in self.dbs:
            self.dbs[db_url] = self.db_engine.db_engine(db_url)
        return self.dbs[db_url]

    def query(self, identity, dataset, filterexpr):
        """Find dataset features inside bounding box.

        :param str identity: User name or Identity dict
        :param str dataset: Dataset ID
        :param str filterexpr: JSON serialized array of filter expressions: [["<attr>", "=", "<value>"]]
        """
        resource_cfg = self._search_permissions(identity).get(dataset)
        if resource_cfg is not None and len(resource_cfg) == 1 \
                and filterexpr is not None:
            # Column for feature ID. If unset, field from filterexpr is used
            self.primary_key = resource_cfg[0].get('search_id_col')
            # parse and validate input filter
            filterexpr = self._parse_filter(filterexpr)
            if filterexpr[0] is None:
                return {
                    'error': "Invalid filter expression: " + filterexpr[1],
                    'error_code': 400
                }
            facet_column = resource_cfg[0].get('facet_column')
            # Append dataset where clause for search view
            if facet_column:
                sql = " AND ".join([filterexpr[0], '"%s"=:vs' % facet_column])
                filterexpr[1]["vs"] = dataset
                filterexpr = (sql, filterexpr[1])

            feature_collection = self._index(filterexpr, resource_cfg[0])
            return {'feature_collection': feature_collection}
        else:
            return {'error': "Dataset not found or permission error"}

    def _search_permissions(self, identity):
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
            if facet in permitted_facets or '*' in permitted_facets:
                facets[facet] = self.resources['facets'][facet]

        return facets

    def _index(self, filterexpr, cfg):
        """Find features by filter query.

        :param (sql, params) filterexpr: A filter expression as a tuple (sql_expr, bind_params)
        """
        db = self._get_db(cfg)
        table_name = cfg.get('table_name', 'search_v')
        geometry_column = cfg.get('geometry_column', 'geom')

        # build query SQL

        # select id
        columns = ', '.join(['"%s"' % self.primary_key])
        quoted_table = '.'.join(
            map(lambda s: '"%s"' % s, table_name.split('.')))

        where_clauses = []
        params = {}

        if filterexpr is not None:
            where_clauses.append(filterexpr[0])
            params.update(filterexpr[1])

        where_clause = "WHERE " + " AND ".join(
            where_clauses) if where_clauses else ""

        sql = sql_text("""
            SELECT {columns},
                ST_AsGeoJSON(ST_CurveToLine("{geom}")) AS json_geom,
                ST_Srid("{geom}") AS srid,
                ST_Extent("{geom}") OVER () AS bbox_
            FROM {table}
            {where_clause}
        """.format(columns=columns, geom=geometry_column,
                   table=quoted_table, where_clause=where_clause))

        # connect to database and start transaction (for read-only access)
        conn = db.connect()
        trans = conn.begin()

        # execute query
        features = []
        result = conn.execute(sql, params).mappings()

        srid = 4326
        bbox = None
        for row in result:
            # NOTE: feature CRS removed by marshalling
            features.append(self._feature_from_query(row))
            srid = row['srid']
            bbox = row['bbox_']

        if bbox:
            m = BBOX_RE.match(bbox)
            # xmin, ymin, xmax, ymax
            bbox = [float(m.group(1)), float(m.group(3)),
                    float(m.group(5)), float(m.group(7))]

        # roll back transaction and close database connection
        trans.rollback()
        conn.close()

        return {
            'type': 'FeatureCollection',
            'crs': {
                'type': 'name',
                'properties': {
                    # NOTE: return CRS name as EPSG:xxxx and not as OGC URN
                    #       to work with QWC2 dataset search
                    'name': 'EPSG:%d' % srid
                    # 'name': 'urn:ogc:def:crs:EPSG::%d' % srid
                }
            },
            'features': features,
            'bbox': bbox
        }

    def _parse_filter(self, filterstr):
        """Parse and validate a filter expression and return a tuple (sql_expr, bind_params).

        :param str filterstr: JSON serialized array of filter expressions: [["<attr>", "=", "<value>"]]
        """
        filterarray = json.loads(filterstr)

        sql = []
        params = {}
        if not type(filterarray) is list or len(filterarray) != 1:
            return (None, "Invalid filter expression")
        i = 0
        expr = filterarray[i]
        if not type(expr) is list or len(expr) != 3:
            # Filter expr must have exactly three parts
            return (None, "Incorrect number of entries in filter expression")
        column_name = expr[0]
        if type(column_name) is not str:
            return (None, "Invalid column name")
        if self.primary_key is None:
            self.primary_key = column_name

        op = expr[1].upper().strip()
        if type(expr[1]) is not str or not op in ["="]:
            return (None, "Invalid operator")

        value = expr[2]
        if not type(value) in [int, float, str]:
            return (None, "Invalid value")

        sql.append('"%s" %s :v%d' % (column_name, op, i))

        params["v%d" % i] = value

        if not sql:
            return (None, "Empty expression")
        else:
            return ("(%s)" % " ".join(sql), params)

    def _feature_from_query(self, row):
        """Build GeoJSON Feature from query result row.

        :param obj row: Row result from query
        """
        pk = row[self.primary_key]
        # Ensure UUID primary key is JSON serializable
        if isinstance(pk, UUID):
            pk = str(pk)

        return {
            'type': 'Feature',
            'id': pk,
            'geometry': json.loads(row['json_geom'] or 'null'),
            'properties': {}
        }

    def _load_resources(self, config):
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


# Extract coords from bbox string like
# BOX(2644230.6300308 1246806.79350726,2644465.86084414 1246867.82022007)
BBOX_RE = re.compile(r'^BOX\((-?\d+(\.\d+)?) (-?\d+(\.\d+)?),(-?\d+(\.\d+)?) (-?\d+(\.\d+)?)\)$')

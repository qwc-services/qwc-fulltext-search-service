from collections import OrderedDict
import os
import re
from flask import json
from sqlalchemy.sql import text as sql_text
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

        self.db_engine = DatabaseEngine()
        self.db = self.db_engine.db_engine(config.get('geodb_url'))

        self.table_name = config.get('search_view_name', 'search_v')
        self.primary_key = config.get('search_id_col', 'id_in_class')
        self.attributes = []
        self.geometry_column = config.get('geometry_column', 'geom')

    def query(self, identity, dataset, filterexpr):
        """Find dataset features inside bounding box.

        :param str identity: User name or Identity dict
        :param str dataset: Dataset ID
        :param str filterexpr: JSON serialized array of filter expressions: [["<attr>", "=", "<value>"]]
        """
        if filterexpr is not None:
            # parse and validate input filter
            filterexpr = self.parse_filter(filterexpr)
            if filterexpr[0] is None:
                return {
                    'error': "Invalid filter expression: " + filterexpr[1],
                    'error_code': 400
                }
            # Append dataset where clause
            sql = " AND ".join([filterexpr[0], "subclass=:vs"])
            filterexpr[1]["vs"] = dataset
            filterexpr = (sql, filterexpr[1])

            feature_collection = self.index(filterexpr)
            return {'feature_collection': feature_collection}
        else:
            return {'error': "Dataset not found or permission error"}

    def index(self, filterexpr):
        """Find features by filter query.

        :param (sql, params) filterexpr: A filter expression as a tuple (sql_expr, bind_params)
        """
        # build query SQL

        # select id and permitted attributes
        columns = (', ').join([self.primary_key] + self.attributes)

        where_clauses = []
        params = {}

        if filterexpr is not None:
            where_clauses.append(filterexpr[0])
            params.update(filterexpr[1])

        where_clause = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        sql = sql_text("""
            SELECT {columns},
                ST_AsGeoJSON({geom}) AS json_geom,
                ST_Srid({geom}) AS srid,
                ST_Extent({geom}) OVER () AS bbox_
            FROM {table}
            {where_clause};
        """.format(columns=columns, geom=self.geometry_column,
                   table=self.table_name, where_clause=where_clause))

        # connect to database and start transaction (for read-only access)
        conn = self.db.connect()
        trans = conn.begin()

        # execute query
        features = []
        result = conn.execute(sql, **params)

        srid = 4326
        bbox = None
        for row in result:
            # NOTE: feature CRS removed by marshalling
            features.append(self.feature_from_query(row))
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
                    'name': 'urn:ogc:def:crs:EPSG::%d' % srid
                }
            },
            'features': features,
            'bbox': bbox
        }

    def parse_filter(self, filterstr):
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

        op = expr[1].upper().strip()
        if type(expr[1]) is not str or not op in ["="]:
            return (None, "Invalid operator")

        value = expr[2]
        if not type(value) in [int, float, str]:
            return (None, "Invalid value")

        sql.append("%s %s :v%d" % (column_name, op, i))

        params["v%d" % i] = value

        if not sql:
            return (None, "Empty expression")
        else:
            return ("(%s)" % " ".join(sql), params)

    def feature_from_query(self, row):
        """Build GeoJSON Feature from query result row.

        :param obj row: Row result from query
        """
        props = OrderedDict()
        for attr in self.attributes:
            props[attr] = row[attr]

        return {
            'type': 'Feature',
            'id': row[self.primary_key],
            'geometry': json.loads(row['json_geom'] or 'null'),
            'properties': props
        }


# Extract coords from bbox string like
# BOX(2644230.6300308 1246806.79350726,2644465.86084414 1246867.82022007)
BBOX_RE = re.compile("^BOX\((\d+(\.\d+)?) (\d+(\.\d+)?),(\d+(\.\d+)?) (\d+(\.\d+)?)\)$")

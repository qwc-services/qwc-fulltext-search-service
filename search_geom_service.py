from collections import OrderedDict
import os
import re
from flask import json
from sqlalchemy.sql import text as sql_text
from qwc_services_core.database import DatabaseEngine


class SearchGeomService():
    """SearchGeomService class

    Subset of Data Service for getting feature geometries.
    """

    def __init__(self, logger):
        """Constructor

        :param Logger logger: Application logger
        """
        self.logger = logger
        self.db_engine = DatabaseEngine()
        self.db = self.db_engine.geo_db()
        self.table_name = os.environ.get(
            'SEARCH_VIEW_NAME', 'search_v'
        )
        self.primary_key = os.environ.get(
            'SEARCH_ID_COL', 'id_in_class'
        )
        self.attributes = []
        self.geometry_column = 'geom'
        self.srid = int(os.environ.get(
            'SEARCH_GEOM_SRID', '2056'
        ))

    def query(self, identity, dataset, filterexpr):
        """Find dataset features inside bounding box.

        :param str identity: User name or Identity dict
        :param str dataset: Dataset ID
        :param str filterexpr: JSON serialized array of filter expressions: [["<attr>", "<op>", "<value>"], "and/or", ["<attr>", "<op>", "<value>"]]
        """
        bbox = None
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

            feature_collection = self.index(
                bbox, filterexpr)
            return {'feature_collection': feature_collection}
        else:
            return {'error': "Dataset not found or permission error"}

    # vvvv Excerpt from  data service vvvvv
    def index(self, bbox, filterexpr):
        """Find features inside bounding box.

        :param list[float] bbox: Bounding box as [<minx>,<miny>,<maxx>,<maxy>]
                                 or None for no bounding box
        :param (sql, params) filterexpr: A filter expression as a tuple (sql_expr, bind_params)
        """
        # build query SQL

        # select id and permitted attributes
        columns = (', ').join([self.primary_key] + self.attributes)

        where_clauses = []
        params = {}

        if bbox is not None:
            # bbox filter
            where_clauses.append("""
                ST_Intersects({geom},
                    ST_SetSRID('BOX3D(:minx :miny, :maxx :maxy)'::box3d, {srid})
                )
            """.format(geom=self.geometry_column, srid=self.srid))
            params.update({"minx": bbox[0], "miny": bbox[1], "maxx": bbox[2], "maxy": bbox[3]})

        if filterexpr is not None:
            where_clauses.append(filterexpr[0])
            params.update(filterexpr[1])

        where_clause = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        sql = sql_text("""
            SELECT {columns},
                ST_AsGeoJSON({geom}) AS json_geom,
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

        bbox = None
        for row in result:
            # NOTE: feature CRS removed by marshalling
            features.append(self.feature_from_query(row))
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
                    'name': 'urn:ogc:def:crs:EPSG::%d' % self.srid
                }
            },
            'features': features,
            'bbox': bbox
        }

    def parse_filter(self, filterstr):
        """Parse and validate a filter expression and return a tuple (sql_expr, bind_params).

        :param str filterstr: JSON serialized array of filter expressions: [["<attr>", "<op>", "<value>"], "and/or", ["<attr>", "<op>", "<value>"]]
        """
        filterarray = json.loads(filterstr)

        sql = []
        params = {}
        i = 0
        for entry in filterarray:
            if type(entry) is str:
                entry = entry.upper()
                if i%2 != 1 or i == len(filterarray) - 1 or not entry in ["AND", "OR"]:
                    # Filter concatenation operators must be at odd-numbered positions in the array and cannot appear last
                    return (None, "Incorrect filter expression concatenation")
                sql.append(entry)
            elif type(entry) is list:
                if len(entry) != 3:
                    # Filter entry must have exactly three parts
                    return (None, "Incorrect number of entries in filter expression")

                column_name = entry[0]
                if type(column_name) is not str:
                    # Invalid column name
                    return (None, "Invalid column name")

                op = entry[1].upper().strip()
                if type(entry[1]) is not str or not op in ["=", "!=", "<>", "<", ">", "<=", ">=", "LIKE", "ILIKE", "IS", "IS NOT"]:
                    # Invalid operator
                    return (None, "Invalid operator")

                value = entry[2]
                if not type(value) in [int,float,str,type(None)]:
                    # Invalid value
                    return (None, "Invalid value")

                if value is None:
                    if op == "=":
                        op = "IS"
                    elif op == "!=":
                        op = "IS NOT"

                sql.append("%s %s :v%d" % (column_name, op, i))

                params["v%d" % i] = value
            else:
                # Invalid entry
                return (None, "Invalid filter expression")
            i += 1

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
        # 'crs': {
        #     'type': 'name',
        #     'properties': {
        #         'name': 'urn:ogc:def:crs:EPSG::%d' % self.srid
        #     }
        # }

# Extract coords from bbox string like
# BOX(2644230.6300308 1246806.79350726,2644465.86084414 1246867.82022007)
BBOX_RE = re.compile("^BOX\((\d+(\.\d+)?) (\d+(\.\d+)?),(\d+(\.\d+)?) (\d+(\.\d+)?)\)$")

from qwc_services_core.runtime_config import RuntimeConfig


class SearchResources:
    """
    Shared resources for search services.
    """

    def __init__(self, config, permissions):
        self.resources = self._load_resources(config)
        self.permissions = permissions

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

    def solr_facets(self, identity):
        """Return permitted search facets.

        :param str identity: User identity
        """
        # get permitted facets
        permitted_facets = self.permissions.resource_permissions(
            'solr_facets', identity
        )
        all_facets_permitted = '*' in permitted_facets

        facets = {}

        for facet, config in self.resources['facets'].items():
            if all_facets_permitted or facet in permitted_facets:
                facets[facet] = config

        return facets

    def dataproducts(self, identity):
        """Return permitted dataproducts.

        :param str identity: User identity
        """
        # get permitted dataproducts
        permitted_dataproducts = self.permissions.resource_permissions(
            'dataproducts', identity
        )

        # return unique sorted dataproducts
        return sorted(list(set(permitted_dataproducts)))

# Copyright 2016 CloudByte Inc
# See LICENSE file for details.

"""CloudByte Plugin for Flocker."""

from cloudbyte_flocker_driver import cloudbyte
from flocker import node


DRIVER_NAME = u"cloudbyte_flocker_driver"


def api_factory(cluster_id, **kwargs):
    return cloudbyte.cloudbyte_from_configuration(
        cluster_id,
        **kwargs)

FLOCKER_BACKEND = node.BackendDescription(
    name=DRIVER_NAME,
    needs_reactor=False,
    needs_cluster_id=True,
    api_factory=api_factory,
    deployer_type=node.DeployerType.block)

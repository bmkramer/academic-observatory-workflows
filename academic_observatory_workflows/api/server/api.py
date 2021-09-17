# Copyright 2021 Curtin University
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Author: Aniek Roelofs

import logging
import os
from typing import Any, Tuple

import connexion
from observatory.api.server.openapi_renderer import OpenApiRenderer

from academic_observatory_workflows.api.server.elastic import (
    get_pit_id,
    query_elasticsearch
)

Response = Tuple[Any, int]
session_ = None  # Global session


def pit_id_agg(agg: str):
    return get_pit_id(agg=agg, subagg=None)


def pit_id_subagg(agg: str, subagg: str):
    return get_pit_id(agg=agg, subagg=subagg)


def query_agg(agg: str):
    return query_elasticsearch(agg=agg, subagg=None)


def query_subagg(agg: str, subagg: str):
    return query_elasticsearch(agg=agg, subagg=subagg)


def create_app() -> connexion.App:
    """Create a Connexion App.

    :return: the Connexion App.
    """

    logging.info("Creating app")

    # Create the application instance and don't sort JSON output alphabetically
    conn_app = connexion.App(__name__)
    conn_app.app.config["JSON_SORT_KEYS"] = False

    # Add the OpenAPI specification
    specification_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "openapi.yaml.jinja2")
    builder = OpenApiRenderer(specification_path, cloud_endpoints=False)
    specification = builder.to_dict()
    conn_app.add_api(specification)

    return conn_app

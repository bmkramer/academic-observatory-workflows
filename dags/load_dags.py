# Copyright 2023 Curtin University
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

# The keywords airflow and DAG are required to load the DAGs from this file, see bullet 2 in the Apache Airflow FAQ:
# https://airflow.apache.org/docs/stable/faq.html


import logging
from typing import List

from observatory.platform.airflow import fetch_workflows, make_workflow
from observatory.platform.observatory_config import Workflow

# TODO: put into re-usable function
# Load DAGs
workflows: List[Workflow] = fetch_workflows()
for workflow in workflows:
    dag_id = workflow.dag_id
    logging.info(f"Making Workflow: {workflow.name}, dag_id={dag_id}")
    dag = make_workflow(workflow)

    logging.info(f"Adding DAG: dag_id={dag_id}, dag={dag}")
    globals()[dag_id] = dag

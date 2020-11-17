################################################################################
# Copyright (c) 2020, National Research Foundation (SARAO)
#
# Licensed under the BSD 3-Clause License (the "License"); you may not use
# this file except in compliance with the License. You may obtain a copy
# of the License at
#
#   https://opensource.org/licenses/BSD-3-Clause
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
################################################################################
"""This module contains the SDP workflow setup classes.

The ProductControllerWorkflow allows users to set up a PoC workflow.
"""


class WorkflowStep:
    def __init__(self):
        """Super class of the individual processes"""
        self.name = (None,)
        self.template_name = None
        self.dependencies = None
        self.resources = None
        self.image = None
        self.command = None
        self.arguments = []
        self.daemon = False
        self.when = None

    def get_step(self):
        """get the step's specification

        :return: dict of the step specification
        """
        step = {"name": self.name, "template": self.template_name}
        if self.dependencies:
            step["dependencies"] = self.dependencies
        return step

    def get_template(self):
        """get the template for the processing step

        :return: dict of template that the spec uses"""
        template = {"container": {"image": self.image}, "name": self.template_name}
        if self.command:
            template["container"]["command"] = self.command
        if self.arguments:
            template["container"]["args"] = self.command
        if self.daemon:
            template["daemon"] = True
        if self.resources:
            template["container"]["resources"] = self.resources
        if self.when:
            template["when"] = self.when
        return template


class Telstate(WorkflowStep):
    def __init__(self):
        """Telstate step"""
        super().__init__()
        self.name = ("telstate",)
        self.template_name = "telstate-template"
        self.image = "redis"
        self.daemon = True


class Ingest(WorkflowStep):
    def __init__(self, step_id: int = None):
        """Ingest step

        :param step_id: the unique ingest ID to be assigned to this process
        """
        super().__init__()
        self.name = f"ingest{step_id}"
        self.template_name = "ingest-template"
        self.arguments = ["./run", "-u", "{{tasks.telstate.ip}}"]
        self.dependencies = "telstate"
        self.command = "python"
        self.image = "cchristelis/ingest:0.5"


class Calibrator(WorkflowStep):
    def __init__(self, step_id: int = None):
        """Calibrator step

        :param step_id: the unique calibrator ID to be assigned to this process
        """
        super().__init__()
        self.name = f"calibrator{step_id}"
        self.template_name = "calibrator-template"
        self.arguments = ["./run", "-u", "{{tasks.telstate.ip}}"]
        self.dependencies = "telstate"
        self.command = "python"
        self.image = "cchristelis/calibrator:0.1"
        self.resources = {
            "limits": {
                "cpu": "500m",
                "memory": "1Gi",
                "sdp.kat.ac.za/jellybeans": 1,  # Fake resource
            },
            "requests": {"cpu": "500m", "memory": "1Gi", "sdp.kat.ac.za/jellybeans": 1},
        }


class BatchSetup(WorkflowStep):
    def __init__(self):
        """Batch Setup step. This step waits for sufficient inputs from
        The Ingest and Calibartor to specify the number of batch processes
        to start.
        """
        super().__init__()
        self.name = ("batch-setup",)
        self.template_name = "batch-setup-template"
        self.image = "cchristelis/batch_setup:0.4"
        self.dependencies = "telstate"
        self.command = "python"
        self.arguments = ["./run", "-u", "{{tasks.telstate.ip}}"]


class Batch(WorkflowStep):
    def __init__(self, number: int):
        """The Batch step

        :param number:
        """
        super().__init__()
        self.name = f"batch{number}"
        self.template_name = "batch-template"
        self.image = "cchristelis/batch:0.1"
        self.command = "python"
        self.arguments = ["./run.py"]
        self.dependencies = "batch-setup"
        self.when = f"{{tasks.batch-setup.outputs.result}} >= {number}"


class ProductControllerWorkflow:
    def __init__(self, subarray: int, worker_count: int = 10, ttl: int = 600):
        """The Product Controller Workflow bringing together all steps in the
        workflow.

        :param subarray: The subarray id that this is processing for
        :param worker_count: The number of workers to be launched
        :param ttl: The time given before teardown is initatied
        """
        self.api_version = "argoproj.io/v1alpha1"
        self.namespace = f"sdparray{subarray}"
        self.name = "product-controller"
        self.ttl = ttl
        self._setup_tasks(worker_count)

    def _setup_tasks(self, worker_count: int):
        """Setting up the individual tasks based on worker counts.

        :param worker_count: The number of worker processes to start
        """
        ingest_count = worker_count // 5
        calib_count = worker_count // 4
        self.tasks = [Telstate()]
        self.tasks += [Ingest(n + 1) for n in range(ingest_count)]
        self.tasks += [Calibrator(n + 1) for n in range(calib_count)]
        self.tasks += [BatchSetup()]
        self.tasks += [Batch(n + 1) for n in range(worker_count)]

    def _task_containers(self):
        """Make a set of unique tasks container template definitions.

        :return: list of templates.
        """
        task_types = {}
        for task in self.tasks:
            task_types[str(type(task))] = task
        return [task_type.get_template() for task_type in task_types.values()]

    def workflow(self):
        """Generate the Argo workflow for the product controller

        :return: workflow dict.
        """
        return {
            "apiVersion": self.api_version,
            "kind": "Workflow",
            "metadata": {"namespace": self.namespace, "name": self.name},
            "spec": {
                "entrypoint": self.name,
                "serviceAccountName": "workflow",
                "ttlStrategy": {
                    "secondsAfterCompletion": self.ttl,
                    "secondsAfterSuccess": self.ttl,
                    "secondsAfterFailure": self.ttl,
                },
                "templates": [
                    {
                        "dag": {"tasks": [task.get_step() for task in self.tasks]},
                        "name": "product-controller",
                    }
                ]
                + self._task_containers(),
            },
        }

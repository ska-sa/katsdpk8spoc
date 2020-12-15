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

import random


class WorkflowStep:
    def __init__(
            self, image=None, name=None, template_name=None, deamon=False,
            dependencies=None, resources=None, command=None, arguments=None,
            when=None):
        """Super class of the individual processes"""
        self.image = image
        self.name = name
        self.template_name = template_name
        self.daemon = deamon
        self.dependencies = dependencies
        self.resources = resources or []
        self.command = command
        self.arguments = arguments or []
        self.when = when

    def append_named_argument(self, name, value, is_input=True):
        self.arguments.append({"name": name, "value": value, "input": is_input})

    def append_argument(self, value):
        rndm = random.randint(10000, 100000)
        name = "{}-{}-{}".format(self.name, len(self.arguments), rndm)
        self.append_named_argument(name, value, is_input=False)

    def get_step(self):
        """get the step's specification

        :return: dict of the step specification
        """
        step = {"name": self.name, "template": self.template_name}
        if self.dependencies:
            step["dependencies"] = self.dependencies
        if self.arguments:
            params = []
            for arg in self.arguments:
                params.append({"name": arg["name"], "value": arg["value"]})
            step["arguments"] = {"parameters": params}
        return step

    def get_template(self):
        """get the template for the processing step

        :return: dict of template that the spec uses"""
        template = {"container": {"image": self.image}, "name": self.template_name}
        if self.command:
            template["container"]["command"] = self.command
        if self.arguments:
            params = []
            for arg in self.arguments:
                if arg.get("is_input"):
                    params.append({"name": arg["name"]})
            template["inputs"] = {"parameters": params}
        if self.daemon:
            template["daemon"] = True
        if self.resources:
            template["container"]["resources"] = self.resources
        if self.when:
            template["when"] = self.when
        return template


class Telstate(WorkflowStep):
    def __init__(self, image="harbor.sdp.kat.ac.za:443/infra/redis:latest"):
        """Telstate step"""
        super().__init__(
            image=image,
            name="telstate",
            template_name="telstate-template",
            daemon=True
        )


class Ingest(WorkflowStep):
    def __init__(
            self, step_id: int = None,
            image: str="harbor.sdp.kat.ac.za:443/infra/pocingest:0.5"):
        """Ingest step

        :param step_id: the unique ingest ID to be assigned to this process
        :param image: the docker image to be used
        """
        super().__init__(
            name=f"ingest{step_id}",
            template_name="ingest-template",
            dependencies=["telstate"],
            command=["python"],
            image=image
        )
        self.append_argument("./run.sh")
        self.append_argument("-u")
        self.append_named_argument("tasks-telstate-ip", "{{tasks.telstate.ip}}")


class Calibrator(WorkflowStep):
    def __init__(
            self, step_id: int = None, resources: dict = None,
            image: str = "harbor.sdp.kat.ac.za:443/infra/poccalibrator:0.1"):
        """Calibrator step

        :param step_id: the unique calibrator ID to be assigned to this process
        :param image: the docker image to be used
        """
        super().__init__(
            name=f"calibrator{step_id}",
            template_name="calibrator-template",
            dependencies=["telstate"],
            command=["python"],
            image=image,
            resources=resources or {
                "limits": {
                    "cpu": "500m",
                    "memory": "1Gi",
                    "sdp.kat.ac.za/jellybeans": 1,  # Fake resource
                },
                "requests": {"cpu": "500m", "memory": "1Gi",
                             "sdp.kat.ac.za/jellybeans": 1},
            }
        )
        self.append_argument("./run.sh")
        self.append_argument("-u")
        self.append_named_argument("tasks-telstate-ip", "{{tasks.telstate.ip}}")


class BatchSetup(WorkflowStep):
    def __init__(
            self, image: str="harbor.sdp.kat.ac.za:443/infra/pocbatch_setup:0.4"):
        """Batch Setup step. This step waits for sufficient inputs from
        The Ingest and Calibartor to specify the number of batch processes
        to start.
        """
        super().__init__(
            name="batch-setup",
            template_name="batch-setup-template",
            image=image,
            dependencies=["telstate"],
            command=["python"]
        )
        self.append_argument("./run.sh")
        self.append_argument("-u")
        self.append_named_argument("tasks-telstate-ip", "{{tasks.telstate.ip}}")


class Batch(WorkflowStep):
    def __init__(
            self, number: int, image: str="harbor.sdp.kat.ac.za:443/infra/pocbatch:0.1"):
        """The Batch step

        :param number: The batch process number. This number is compared to the
            total desired runs. And skipped if larger.
        :param image: The docker image to be used
        """
        super().__init__(
            name=f"batch{number}",
            template_name="batch-template",
            image=image,
            command=["python"],
            dependencies=["batch-setup"],
            when=f"{{tasks.batch-setup.outputs.result}} >= {number}"
        )
        self.append_argument("./run.sh")


class ProductControllerWorkflow:
    def __init__(
            self, namespace: int, config: dict, worker_count:
            int = 10, ttl: int = 600):
        """The Product Controller Workflow bringing together all steps in the
        workflow.

        :param subarray: The subarray id that this is processing for
        :param worker_count: The number of workers to be launched
        :param ttl: The time given before teardown is initatied
        """
        self.api_version = "argoproj.io/v1alpha1"
        self.namespace = namespace
        self.name = f"product-controller-{namespace}"
        self.ttl = ttl
        self.config = config
        self._setup_tasks(worker_count)

    def _setup_tasks(self, worker_count: int):
        """Setting up the individual tasks based on worker counts.

        :param worker_count: The number of worker processes to start
        """
        ingest_count = worker_count // 5
        calib_count = worker_count // 4
        components = self.config["components"]
        telstate_image = components["telstate"]["docker_image"]
        calibrator_image = components["calibrator"]["docker_image"]
        calibrator_resources = components["calibrator"]["resources"]
        ingest_image = components["ingest"]["docker_image"]
        self.tasks = [Telstate(image=telstate_image)]
        self.tasks += [Ingest(n + 1, image=ingest_image) for n in range(ingest_count)]
        self.tasks += [
            Calibrator(
                n + 1,
                image=calibrator_image,
                resources=calibrator_resources
            ) for n in range(calib_count)]

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
                        "name": self.name,
                    }
                ]
                + self._task_containers(),
            },
        }

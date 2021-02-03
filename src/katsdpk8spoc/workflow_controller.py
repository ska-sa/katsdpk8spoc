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
            self, image=None, name=None, template_name=None, daemon=False,
            dependencies=None, resources=None, command=None, arguments=None,
            args=None,
            hostnetwork=False,
            when=None):
        """Super class of the individual processes"""
        self.image = image
        self.name = name
        self.template_name = template_name
        self.daemon = daemon
        self.hostnetwork = hostnetwork
        self.dependencies = dependencies
        self.resources = resources or []
        self.command = command
        self.arguments = arguments or []
        self.args = args or [] # Container args. Template arguments are translated to args that gets appended to command.
        self.when = when

    def append_named_argument(self, name, value, is_input=True):
        self.arguments.append({"name": name, "value": value, "is_input": is_input})

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
        step['hostNetwork'] = self.hostnetwork
        return step

    def get_template(self):
        """get the template for the processing step

        :return: dict of template that the spec uses"""
        template = {"container": {"image": self.image}, "name": self.template_name}
        if self.command:
            template["container"]["command"] = self.command
            template["container"]["args"] = self.args
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
        template['hostNetwork'] = bool(self.hostnetwork)
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

class Head(WorkflowStep):
    def __init__(
            self, step_id: int = None,
            image: str="harbor.sdp.kat.ac.za:443/infra/pocingest:0.5",
            resources: dict = None,
            dependencies=[]):
        """Ingest step

        :param step_id: the unique ingest ID to be assigned to this process
        :param image: the docker image to be used
        """
        super().__init__(
            name=f"realtimehead",
            template_name="head-template",
            dependencies=dependencies,
            command=["sleep", '120'],
            image=image,
            resources=resources
        )
        #self.append_argument("sleep")
        #self.append_argument("120")
        #self.append_argument("./run.sh")
        #self.append_argument("-u")
        #self.append_named_argument("tasks-telstate-ip", "{{tasks.telstate.ip}}")


class Ingest(WorkflowStep):
    def __init__(
            self, step_id: int = None,
            image: str = None,
            resources: dict = None):
        """Ingest step

        :param step_id: the unique ingest ID to be assigned to this process
        :param image: the docker image to be used
        """
        super().__init__(
            name=f"ingest{step_id}",
            template_name="ingest-template",
            dependencies=["telstate"],
            # command=["tail", "-f"],
            command=["spead2_send.py"],
            args=["{{ inputs.parameters.mcast-addr }}"],
            image=image,
            resources=resources,
            daemon=True,
            hostnetwork=True
        )
        self.append_named_argument("mcast-addr", "239.23.9.{}:6789".format(step_id))
        #self.append_argument("tail")
        #self.append_argument("-f")
        #self.append_argument("./run.sh")
        #self.append_argument("-u")
        #self.append_named_argument("tasks-telstate-ip", "{{tasks.telstate.ip}}")


class Calibrator(WorkflowStep):
    def __init__(
            self, step_id: int = None,
            image: str = None,
            resources: dict = None):
        """Calibrator step

        :param step_id: the unique calibrator ID to be assigned to this process
        :param image: the docker image to be used
        """
        super().__init__(
            name=f"calibrator{step_id}",
            template_name="calibrator-template",
            dependencies=["telstate"],
            command=["spead2_recv.py"],
            args=["{{ inputs.parameters.mcast-addr }}"],
            image=image,
            resources=resources,
            daemon=True,
            hostnetwork=True
        )
        self.append_named_argument("mcast-addr", "239.23.9.{}:6789".format(step_id))
        #self.append_argument("-f")
        #self.append_argument("./run.sh")
        #self.append_argument("-u")
        #self.append_named_argument("tasks-telstate-ip", "{{tasks.telstate.ip}}")


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
            int):
        """The Product Controller Workflow bringing together all steps in the
        workflow.

        :param subarray: The subarray id that this is processing for
        :param worker_count: The number of workers to be launched
        :param ttl: The time given before teardown is initatied
        """
        self.api_version = "argoproj.io/v1alpha1"
        self.namespace = namespace
        self.name = f"product-controller-{namespace}"
        self.config = config
        self.ttl = config["components"]["ttl"]
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
        calibrator_resources = self._get_resources("calibrator")
        ingest_image = components["ingest"]["docker_image"]
        ingest_resources = self._get_resources("ingest")
        self.tasks = [Telstate(image=telstate_image)]
        realtime_head_dependencies = []
        for n in range(ingest_count):
            task = Ingest(
                    n + 1,
                    image=ingest_image,
                    resources=ingest_resources
                ) 
            self.tasks.append(task)
            realtime_head_dependencies.append(task.name)
        for n in range(calib_count):
            task = Calibrator(
                n + 1,
                image=calibrator_image,
                resources=calibrator_resources
            ) 
            self.tasks.append(task)
            realtime_head_dependencies.append(task.name)
        print(realtime_head_dependencies)
        task = Head(0, image=components["head"]["docker_image"],
                resources=self._get_resources("head"),
                dependencies=realtime_head_dependencies)
        self.tasks.append(task)

    def _get_resources(self, component: str):
        """Get the specified component's configured resources or None.
        If the resource doesn't have requests, then make requests == limit."""
        components = self.config["components"]
        resources = components[component].get("resources")
        if not resources:
            return None
        if not resources.get("requests"):
            resources["requests"] = resources["limits"]
        return resources

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
                "hostNetwork": True,
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

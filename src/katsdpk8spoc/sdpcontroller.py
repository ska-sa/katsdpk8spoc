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

"""This module contains the SDP Product Controller webserver.
"""
import argparse
import asyncio
import logging
import pprint

import aiohttp
import yaml
from aiohttp import web
from aiohttp_swagger3 import SwaggerDocs, SwaggerUiSettings
import jinja2
import aiohttp_jinja2

from workflow_controller import ProductControllerWorkflow


class ProductController:
    def __init__(self, name, config):
        self.name = name
        self.config = config
        self.namespace = self.config["subarrays"][self.name]["namespace"]

    async def start(self, *args, **kwargs):
        """Start a subarray with a given number as well as number of receptors

        :param receptors: Receptor number
        :return: status of the created workflow
        """
        namespace = self.namespace
        wf = ProductControllerWorkflow(
            namespace,
            self.config,
            worker_count=self.calculate_batch_limit()
        )
        workflow_dict = {
            "serverDryRun": False,
            "namespace": self.namespace,
            "workflow": wf.workflow(),
        }
        argo_url = self.config["argo_url"]
        url = f"{argo_url}/api/v1/workflows/{namespace}"
        try:
            status = await self.argo_post(url, data=workflow_dict)
        except aiohttp.client_exceptions.ClientConnectorError:
            status = "Error Server unreachable"
        return {"status": status, "workflow": workflow_dict}

    async def _stop_workflow(self, workflow_name: str):
        """Stop a subarray with

        :param subarray: subarray name
        :param workflow_name: workflow name
        :return: status of the stop request
        """
        _headers = {"content-type": "application/json"}
        url = "{}/api/v1/workflows/{}/{}/terminate".format(
            self.config["argo_url"], self.namespace, workflow_name
        )
        data = {
            "name": workflow_name,
            "namespace": self.namespace,
        }
        async with aiohttp.ClientSession() as session:
            resp = await session.put(url, json=data, headers=_headers)
            # assert resp.status == 200
            data = await resp.json()
        return data

    async def stop(self):
        status = await self.status()
        items = status.get("items")
        info = []
        if items:
            for wf in items:
                res = await self._stop_workflow(wf["metadata"]["name"])
                info.append(res)
        return True

    async def status(self):
        argo_base_url = self.config["argo_url"]
        subarray = self.name
        url = f"{argo_base_url}/api/v1/workflows/{subarray}"
        headers = {}
        if self.config.get("argo_token"):
            headers = {"Authorization": self.config.get("argo_token")}
        try:
            status = await self.argo_get(url, headers)
        except aiohttp.client_exceptions.ClientConnectorError:
            status = "Error Server unreachable"
        return status

    def calculate_batch_limit(self):
        """This is the batch job size limit. For now we are returning 10,
        but later on we might have a better number.
        The exact number of batch jobs depends on the, for now, "random" number
        obtained in the Calibrator and Ingest nodes."""
        return 10

    @staticmethod
    async def argo_get(url, headers=None):
        """Get an ARGO Json to an URL"""
        async with aiohttp.request("GET", url, headers=headers) as resp:
            assert resp.status == 200
            data = await resp.json()
        return data

    @staticmethod
    async def argo_post(url, headers=None, data=None):
        """Post an ARGO JSON to an URL"""
        headers = headers or {}
        headers["content-type"] = "application/json"
        logging.debug(data)
        async with aiohttp.ClientSession() as session:
            resp = await session.post(url, json=data, headers=headers)
            data = await resp.json()
        return data


class SDPController:
    def __init__(self, config):
        self.config = config
        self.subarrays = {}
        for subarray in config.get("subarrays", {}).keys():
            self.subarrays[subarray] = ProductController(subarray, config)

    def get_subarray(self, subarray):
        return self.subarray[subarray]

    async def start(self, subarray, *args, **kwargs):
        return await self.subarrays[subarray].start(*args, **kwargs)

    async def stop(self, subarray):
        return await self.subarrays[subarray].stop()

    async def status(self, subarray):
        return await self.subarrays[subarray].status()

    async def check(self):
        pass

    def get_antennas(self):
        """Get antennas/receptors that this controller is configured with."""
        return self.config.get("antennas", [])

    def get_subarrays(self):
        """Get subarrays that this controller is configured with."""
        return self.config.get("subarrays", [])


def dict2html(data: dict):
    html = "<pre>" + pprint.pformat(data) + "</pre>"
    return html


def html_page(name: str, subarray: str, body: str = "", data: dict = None):
    html = "<html><body>"
    if subarray:
        html += "<h1>{} {}</h1>".format(name.title(), subarray)
    else:
        html += "<h1>{}</h1>".format(name.title())
    html += "<form action='/'><input type='submit' value='Home'></form>"
    if name != "status" and subarray:
        html += "<form action='/status'>"
        html += "<input type='hidden' name='subarray' value='{}'>".format(subarray)
        html += "<input type='submit' value='Status'></form>"
    if body:
        html += "</br><div>"
        html += body
        html += "</div></br>"
    if data:
        html += "</br><div>"
        html += dict2html(data)
        html += "</div></br>"
    html += "</body></html>"
    return html


async def product_configure(request):
    """
    ---
    description: start a subarray

    responses:
        "200":
            $ref: '#/components/responses/Reply200Ack'
        "405":
            $ref: '#/components/responses/HTTPMethodNotAllowed'
        "421":
            $ref: '#/components/responses/HTTPMisdirectedRequest'
        "422":
            $ref: '#/components/responses/HTTPUnprocessableEntity'
    """
    post = await request.post()
    logging.debug(post)
    subarray = post.get('subarray', [])
    receptors = post.getall('receptors[]', [])
    controller = request.app["controller"]
    response = await controller.start(subarray, receptors=receptors)
    buf = html_page("start", subarray, data=response)
    return web.Response(body=buf, content_type="text/html")


async def stop_handle(request):
    """
    ---
    description: stop a subarray
    parameters:
       - in: query
         name: subarray
         schema:
           type: string
         required: true
         description: The subarray ID.
    responses:
        "200":
            $ref: '#/components/responses/Reply200Ack'
        "405":
            $ref: '#/components/responses/HTTPMethodNotAllowed'
        "421":
            $ref: '#/components/responses/HTTPMisdirectedRequest'
        "422":
            $ref: '#/components/responses/HTTPUnprocessableEntity'
    """
    controller = request.app["controller"]
    subarray = request.query["subarray"]
    response = await controller.stop(subarray)
    buf = html_page("stop", request.query["subarray"], data=response)
    return web.Response(body=buf, content_type="text/html")


async def status_handle(request):
    """
    ---
    description: status a subarray
    parameters:
       - in: query
         name: subarray
         schema:
           type: string
         required: true
         description: The subarray ID.
    responses:
        "200":
            $ref: '#/components/responses/Reply200Ack'
        "405":
            $ref: '#/components/responses/HTTPMethodNotAllowed'
        "421":
            $ref: '#/components/responses/HTTPMisdirectedRequest'
        "422":
            $ref: '#/components/responses/HTTPUnprocessableEntity'
    """
    controller = request.app["controller"]
    subarray = request.query["subarray"]
    response = await controller.status(subarray)
    buf = html_page("status", request.query["subarray"], data=response)
    return web.Response(body=buf, content_type="text/html")


async def config_handle(request):
    """
    ---
    description: display system config
    responses:
        "200":
            $ref: '#/components/responses/Reply200Ack'
        "405":
            $ref: '#/components/responses/HTTPMethodNotAllowed'
        "421":
            $ref: '#/components/responses/HTTPMisdirectedRequest'
        "422":
            $ref: '#/components/responses/HTTPUnprocessableEntity'
    """
    controller = request.app["controller"]
    conf = dict(controller.config)
    conf["argo_token"] = "*" * 20 if conf.get("argo_token") else "undefined"
    buf = html_page("config", 0, data=conf)
    return web.Response(body=buf, content_type="text/html")


async def home_page(request):
    controller = request.app["controller"]
    antennas = controller.get_antennas()
    subarrays = controller.get_subarrays()
    context = {
        "receptors": antennas,
        "subarrays": subarrays
    }
    response = aiohttp_jinja2.render_template(
        "index.html", request, context=context)
    return response


async def status_runner(app):

    controller = app["controller"]
    while True:
        await asyncio.sleep(10)
        await controller.check()


async def start_background_tasks(app):
    app["status_runner"] = asyncio.Task(status_runner(app))


def get_config():
    """Read command line args for config file."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "configfile",
        help="Configuration file in YAML format.",
        type=argparse.FileType("r"),
    )
    parser.add_argument(
        "-v",
        action="store_true",
        default=False,
        dest="verbose",
        help="Make logging more verbose",
    )
    parser.add_argument(
        "-d",
        action="store_true",
        default=False,
        dest="debug",
        help="Debug logging, very verbose",
    )
    parser.add_argument(
        "-q", action="store_true", default=False, dest="quiet", help="Quiet, less logs"
    )
    args = parser.parse_args()
    config = yaml.load(args.configfile, Loader=yaml.SafeLoader)

    # Set the correct log level.
    logger = logging.getLogger()
    if args.debug:
        config["logging"] = "debug"
        logger.setLevel(logging.DEBUG)
    elif args.verbose:
        config["logging"] = "info"
        logger.setLevel(logging.INFO)
    elif args.quiet:
        config["logging"] = "error"
        logger.setLevel(logging.ERROR)
    else:
        config["logging"] = "warning"
        logger.setLevel(logging.WARNING)

    # Read the token if it has been supplied.
    if config.get("argo_token_file"):
        with open(config.get("argo_token_file")) as fileh:
            config["argo_token"] = fileh.read().strip()

    logging.debug("config=%s", config)
    logging.debug("---END CONFIGURE---")
    return config


def main():
    config = get_config()
    app = web.Application()
    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader("/src/templates")
    )
    app["controller"] = SDPController(config)
    app.on_startup.append(start_background_tasks)

    swagger = SwaggerDocs(
        app,
        swagger_ui_settings=SwaggerUiSettings(path="/api/doc"),
        title="Product controller PoC",
        version="1.0.0",
        # components="swagger.yaml",
    )
    swagger.add_routes(
        [
            web.get("/", home_page),
            web.post("/product-configure", product_configure),
            web.get("/stop", stop_handle),
            web.get("/status", status_handle),
            web.get("/config", config_handle),
        ]
    )
    web.run_app(app)


if __name__ == "__main__":
    main()

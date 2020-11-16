ARG KATSDPDOCKERBASE_REGISTRY=quay.io/ska-sa

FROM $KATSDPDOCKERBASE_REGISTRY/docker-base-build as build

# Switch to Python 3 environment
ENV PATH="$PATH_PYTHON3" VIRTUAL_ENV="$VIRTUAL_ENV_PYTHON3"

# Install dependencies
COPY --chown=kat:kat requirements.txt /tmp/install/requirements.txt
RUN install-requirements.py -d ~/docker-base/base-requirements.txt -r /tmp/install/requirements.txt

# Install the current package
COPY --chown=kat:kat . /tmp/install/katsdpk8spoc
WORKDIR /tmp/install/katsdpk8spoc
RUN python ./setup.py clean
RUN pip install --no-deps .
RUN pip check

#######################################################################

FROM $KATSDPDOCKERBASE_REGISTRY/docker-base-runtime
LABEL maintainer="sdpdev+katsdpk8spoc@ska.ac.za"

COPY --from=build --chown=kat:kat /home/kat/ve3 /home/kat/ve3
ENV PATH="$PATH_PYTHON3" VIRTUAL_ENV="$VIRTUAL_ENV_PYTHON3"

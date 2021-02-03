
all: devrun

# Create the vertial env
venv:
	python3 -m venv .venv

install:
	./.venv/bin/pip install -U .

devinstall:
	./.venv/bin/pip install -U --no-deps .

run:
	./.venv/bin/sdpk8sctrl test/example-config.yml

devrun: devinstall run

setup: venv install

activate:
	@echo source ./.venv/bin/activate

build:
	docker build -t harbor.sdp.kat.ac.za/science/katsdpk8spoc:martin .

push:
	docker push harbor.sdp.kat.ac.za/science/katsdpk8spoc:martin


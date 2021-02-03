#FROM ubuntu:20.04
FROM python:3.8
RUN mkdir /src
COPY . /src/.
WORKDIR /src
RUN pip install -r requirements.txt .

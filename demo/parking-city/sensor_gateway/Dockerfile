FROM python:3.12-slim
WORKDIR /srv
COPY common_py /srv/common_py
RUN pip install --no-cache-dir /srv/common_py
COPY sensor_gateway/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY proto /srv/proto
RUN python -m grpc_tools.protoc -I proto --python_out=. --grpc_python_out=. proto/occupancy.proto
COPY sensor_gateway/app /srv/app
CMD ["python", "-m", "app.main"]

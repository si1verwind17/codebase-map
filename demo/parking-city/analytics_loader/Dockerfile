FROM python:3.12-slim
WORKDIR /srv
COPY common_py /srv/common_py
RUN pip install --no-cache-dir /srv/common_py
COPY analytics_loader/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY analytics_loader/app /srv/app
CMD ["python", "-m", "app.main"]

FROM python:3.12-slim
WORKDIR /srv
COPY common_py /srv/common_py
RUN pip install --no-cache-dir /srv/common_py
COPY city_dashboard/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt
COPY city_dashboard/app /srv/app
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]

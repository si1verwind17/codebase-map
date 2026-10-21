"""Application code shared by two Airflow projects.

Both the `features` and the `forecast` registration sync this package into
the DAG bucket (see deploy/register.sh), so two services deploy the same code.
"""

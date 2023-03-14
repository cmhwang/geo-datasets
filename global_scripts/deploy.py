"""
This script is intended to build and deploy a Prefect flow using settings/parameters defined in an
accompany config.ini for the dataset.

---------------------------------------

Roughly equivalent actions via cli
#
# *** the below commands are just a general starting point, and not meant to run as is. note that there
#     are no parameters specified or storage block creation

# to deploy:
prefect deployment build flow.py:flow_function_name -n "deployment_name" -sb github/existing_storage_block_name -q work_queue_name --apply

# to not immediately deploy remove `--apply` from the above line, then use the build yaml to run the following:
# prefect deployment apply build-deployment.yaml

# to run the deployment
prefect deployment run flow_function_name/deployment_name

# start workqueue
prefect agent start -q 'work_queue_name'

"""

import os
import sys
from configparser import ConfigParser

import click
from prefect.filesystems import GitHub
from prefect.deployments import Deployment
from prefect.infrastructure.kubernetes import KubernetesJob

def flow_import(module_name, flow_name):
    module = __import__(module_name)
    import_flow = getattr(module, flow_name)
    return import_flow


@click.command()
@click.argument("dataset")
@click.option("--kubernetes-job-block", default=None, help="Name of Kubernetes Job block to use")
def deploy(dataset, kubernetes_job_block):
    # find dataset directory
    dataset_dir = dataset.strip("/")
    if dataset_dir not in os.listdir(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))):
        raise Exception("dataset directory provided not found in current directory")
    else:
        click.echo(f"Found dataset {dataset}")

    # find and import the get_config_dict function for the dataset
    click.echo("Finding get_config_dict function for dataset...")
    sys.path.insert(1, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), dataset_dir))
    from main import get_config_dict

    # find and parse dataset config file
    click.echo("Finding config.ini file for dataset...")
    config_file = dataset_dir + "/config.ini"
    config = ConfigParser()
    config.read(config_file)

    click.echo("Finding flow to deploy...")
    module_name = config["deploy"]["flow_file_name"]
    flow_name = config["deploy"]["flow_name"]

    # create and load storage block
    click.echo("Loading storage block configuration...")
    block_name = config["deploy"]["storage_block"]
    block_repo = config["github"]["repo"]
    block_reference = config["github"]["branch"] # branch or tag
    block_repo_dir = config["github"]["directory"]

    click.echo("Saving GitHub storage block to Prefect...")
    block = GitHub(
        repository=block_repo,
        reference=block_reference,
        #access_token=<my_access_token> # only required for private repos
    )
    # block.get_directory(block_repo_dir)
    block.save(block_name, overwrite=True)

    click.echo("Retrieving block from Prefect")
    storage = GitHub.load(block_name)

    # import flow from dataset folder
    click.echo("Loading flow...")
    flow = flow_import(module_name, flow_name)

    """
    # add CPU and RAM request and limit amounts
    infra_overrides = {
        "customizations": [
            {
                "op": "replace",
                "path": "/spec/template/spec/containers/0/resources",
                "value": {
                    "limits": {
                        "cpu": str(cpu_limit),
                        "memory": str(memory_limit) + "Gi",
                    },
                    "requests": {
                        "cpu": str(cpu_request),
                        "memory": str(memory_request) + "Gi",
                    },
                },
            }
        ]
    }
    """

    click.echo("Deciding deployment options...")
    deployment_options = {
        "flow": flow,
        "name": config["deploy"]["deployment_name"],
        "version": config["deploy"]["version"],
        # "work_queue_name": "geo-datasets",
        "work_queue_name": config["deploy"]["work_queue"],
        "storage": storage,
        "path": block_repo_dir,
        # "skip_upload": True,
        "parameters": get_config_dict(config_file),
        "apply": True,
    }

    # find Kubernetes Job Block, if one was specified
    if kubernetes_job_block is None:
        click.echo("No Kubernetes Job Block will be used.")
    else:
        click.echo(f"Using Kubernetes Job Block: {kubernetes_job_block}")
        deployment_options["infrastructure"] = KubernetesJob.load(kubernetes_job_block)

    # build deployment
    click.echo("Deploying...")
    deployment = Deployment.build_from_flow(**deployment_options)

    click.echo("Done!")


if __name__ == "__main__":
    deploy()

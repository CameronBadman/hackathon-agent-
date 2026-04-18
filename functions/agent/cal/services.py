from google.cloud import secretmanager

from .config import CONFIG

SM_CLIENT = secretmanager.SecretManagerServiceClient()


def access_secret(secret_name: str) -> str:
    resource = f"projects/{CONFIG.project_id}/secrets/{secret_name}/versions/latest"
    response = SM_CLIENT.access_secret_version(request={"name": resource})
    return response.payload.data.decode("utf-8").strip()

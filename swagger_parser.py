from pydantic import BaseModel
from typing import Dict, Any, List
import yaml
import json


class MockEndpoint(BaseModel):
    path: str
    method: str
    response_body: Dict[str, Any]
    response_headers: Dict[str, str]


def parse_swagger(file_content: str) -> Dict[str, Any]:
    # Парсинг JSON/YAML
    if file_content.lstrip().startswith('{'):
        return json.loads(file_content)
    return yaml.safe_load(file_content)


def generate_mock_endpoints(swagger_data: Dict) -> List[MockEndpoint]:
    endpoints = []
    #is_swagger_2 = swagger_data.get('swagger', '').startswith('2.0')
    definitions = swagger_data.get('definitions', {})

    for path, methods in swagger_data.get('paths', {}).items():
        for method, details in methods.items():
            method = method.lower()
            if method not in {'get', 'post', 'put', 'delete', 'patch'}:
                continue

            endpoint = MockEndpoint(
                path=path,
                method=method,
                response_body={"message": "Default response"},
                response_headers={"Content-Type": "application/json"}
            )

            # Обработка Swagger 2.0
            response_200 = details.get('responses', {}).get('200', {})
            if response_200:
                schema = response_200.get('schema')
                if schema:
                    endpoint.response_body = resolve_schema(
                        schema, definitions)

                 # Бинарные ответы
                produces = details.get('produces', [])
                if any('image/' in ct for ct in produces):
                    endpoint.response_body = {
                        "message": "Binary content placeholder"}
                    endpoint.response_headers = {"Content-Type": "image/png"}

            endpoints.append(endpoint)

    return endpoints


def resolve_schema(schema: Any, definitions: Dict) -> Any:
    if isinstance(schema, dict):
        if '$ref' in schema:
            ref_name = schema['$ref'].split('/')[-1]
            return resolve_schema(definitions[ref_name], definitions)

        if schema.get('type') == 'array':
            return [resolve_schema(schema.get('items', {}), definitions)]

        if schema.get('type') == 'object':
            return {
                prop: resolve_schema(config, definitions)
                for prop, config in schema.get('properties', {}).items()
            }

        return {"example": f"{schema.get('type')}_value"}

    return {}

from fastapi import FastAPI, UploadFile, Form, Request, Depends, HTTPException, APIRouter
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
import json
import os
import uvicorn

from database import engine, SessionLocal
import models
import swagger_parser

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

models.Base.metadata.create_all(bind=engine)

# Dependency


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
async def root(request: Request, db: Session = Depends(get_db)):
    mocks = db.query(models.MockDeployment).all()
    return templates.TemplateResponse("upload.html", {"request": request, "mocks": mocks})


def mount_mock_app(base_path: str, mock_id: int):
    router = APIRouter()

    async def handler_wrapper(endpoint_path: str, endpoint_method: str):
        async def route_handler(request: Request):
            db = SessionLocal()
            try:
                endpoint = db.query(models.EndpointResponse).filter(
                    models.EndpointResponse.mock_id == mock_id,
                    models.EndpointResponse.path == endpoint_path,
                    models.EndpointResponse.method == endpoint_method.lower()
                ).first()

                if not endpoint:
                    return JSONResponse({"error": "Not found"}, 404)

                headers = json.loads(
                    endpoint.response_headers) if endpoint.response_headers else None

                # Check parameter matches
                path_params = request.path_params
                for param in endpoint.parameters:
                    if param.param_name in path_params and path_params.get(param.param_name) == param.param_value:
                        return JSONResponse(
                            content=json.loads(param.response_body),
                            headers=headers,
                            status_code=200
                        )

                # Return default response if no matches
                body = json.loads(
                    endpoint.default_response) if endpoint.default_response else json.loads(
                    endpoint.response_body)

                return JSONResponse(
                    content=body,
                    headers=headers,
                    status_code=200
                )
            finally:
                db.close()
        return route_handler

    db = SessionLocal()
    try:
        endpoints = db.query(models.EndpointResponse).filter_by(
            mock_id=mock_id).all()

        for endpoint in endpoints:
            # Create a closure to capture the current endpoint path and method
            # Create a route handler that accepts request parameters
            def create_route_handler(ep_path=endpoint.path, ep_method=endpoint.method):
                return handler_wrapper(ep_path, ep_method)

            router.add_api_route(
                endpoint.path,
                create_route_handler(),
                methods=[endpoint.method.upper()]
            )
    finally:
        db.close()

    sub_app = FastAPI()
    sub_app.include_router(router)
    app.mount(f"/{base_path}", sub_app)


@app.post("/upload-swagger/")
async def upload_swagger(
    request: Request,
    file: UploadFile,
    mock_name: str = Form(...),
    db: Session = Depends(get_db)
):
    # Check if mock name already exists
    existing_mock = db.query(models.MockDeployment).filter(
        models.MockDeployment.name == mock_name).first()
    if existing_mock:
        raise HTTPException(
            status_code=400, detail="Mock API with this name already exists")

    # Read and parse swagger file
    content = await file.read()
    file_content = content.decode("utf-8")

    try:
        swagger_data = swagger_parser.parse_swagger(file_content)
        endpoint_list = swagger_parser.generate_mock_endpoints(swagger_data)

        # Generate unique base path
        base_path = f"mock-{mock_name.lower().replace(' ', '-')}"
        # Check base path uniqueness
        counter = 1
        original_name = base_path
        while db.query(models.MockDeployment).filter(models.MockDeployment.base_path == base_path).first():
            base_path = f"{original_name}-{counter}"
            counter += 1

        # Save to database
        mock_deployment = models.MockDeployment(
            name=mock_name,
            base_path=base_path,
            swagger_content=file_content,
            endpoints=""  # We'll store endpoints in a separate table now
        )
        db.add(mock_deployment)
        db.flush()  # Get the ID without committing

        # Save endpoints to the new table
        for endpoint in endpoint_list:
            db_endpoint = models.EndpointResponse(
                mock_id=mock_deployment.id,
                path=endpoint.path,
                method=endpoint.method,
                response_body=json.dumps(
                    endpoint.response_body, ensure_ascii=False),
                response_headers=json.dumps(
                    endpoint.response_headers, ensure_ascii=False)
            )
            db.add(db_endpoint)

        db.commit()

        # Mount the mock app
        mount_mock_app(base_path, mock_deployment.id)

        # Return success response
        mocks = db.query(models.MockDeployment).all()
        return templates.TemplateResponse(
            "upload.html",
            {
                "request": request,
                "mocks": mocks,
                "message": f"Mock API '{mock_name}' created successfully at path /{base_path}"
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Error processing swagger file: {str(e)}")

# Add routes for managing endpoints


@app.get("/manage/{mock_base_path}")
async def manage_mock(
    request: Request,
    mock_base_path: str,
    db: Session = Depends(get_db)
):
    mock = db.query(models.MockDeployment).filter_by(
        base_path=mock_base_path).first()
    if not mock:
        raise HTTPException(404, "Mock not found")

    endpoints = db.query(models.EndpointResponse).filter_by(
        mock_id=mock.id).all()
    return templates.TemplateResponse(
        "manage_mock.html",
        {"request": request, "mock": mock, "endpoints": endpoints}
    )


@app.get("/edit-endpoint/{endpoint_id}")
async def edit_endpoint_form(
    request: Request,
    endpoint_id: int,
    db: Session = Depends(get_db)
):
    endpoint = db.query(models.EndpointResponse).get(endpoint_id)
    if not endpoint:
        raise HTTPException(404, "Endpoint not found")

    return templates.TemplateResponse(
        "edit_endpoint.html",
        {
            "request": request,
            "endpoint": endpoint,
            "headers": json.dumps(json.loads(endpoint.response_headers), indent=2),
            "body": json.dumps(json.loads(endpoint.response_body), indent=2),
            "default_response": json.dumps(json.loads(endpoint.default_response), indent=2) if endpoint.default_response else json.dumps(json.loads(endpoint.response_body), indent=2)
        }
    )


@app.post("/edit-endpoint/{endpoint_id}")
async def update_endpoint(
    request: Request,
    endpoint_id: int,
    response_body: str = Form(...),
    response_headers: str = Form(...),
    default_response: str = Form(...),
    param_name: list[str] = Form([]),
    param_value: list[str] = Form([]),
    param_response: list[str] = Form([]),
    db: Session = Depends(get_db)
):
    try:
        json.loads(response_body)
        json.loads(response_headers)
        json.loads(default_response)
        for resp in param_response:
            if resp:
                json.loads(resp)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON format")

    endpoint = db.query(models.EndpointResponse).get(endpoint_id)
    if not endpoint:
        raise HTTPException(404, "Endpoint not found")

    mock = db.query(models.MockDeployment).get(endpoint.mock_id)

    endpoint.response_body = response_body
    endpoint.response_headers = response_headers
    endpoint.default_response = default_response
    
    # Clear existing parameters
    db.query(models.EndpointParameter).filter_by(endpoint_id=endpoint_id).delete()
    
    # Add new parameters
    for name, value, response in zip(param_name, param_value, param_response):
        if name and value and response:
            db.add(models.EndpointParameter(
                endpoint_id=endpoint_id,
                param_name=name,
                param_value=value,
                response_body=response,
                response_headers=endpoint.response_headers
            ))
    
    db.commit()

    return RedirectResponse(
        f"/manage/{mock.base_path}",
        status_code=303
    )

# Load existing mocks on startup


@app.on_event("startup")
async def load_existing_mocks():
    db = SessionLocal()
    try:
        mocks = db.query(models.MockDeployment).all()
        for mock in mocks:
            mount_mock_app(mock.base_path, mock.id)
    finally:
        db.close()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

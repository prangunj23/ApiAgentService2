from functools import lru_cache
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from consumer.config import OPERATION_BASE_URL
from operation import OperationClient

app = FastAPI(title="consumer", version="0.1.0")


class ComputeRequest(BaseModel):
    a: float
    b: float


class ComputeResponse(BaseModel):
    result: float
    source: str


@lru_cache
def get_operation_client() -> OperationClient:
    return OperationClient(OPERATION_BASE_URL)


OperationDep = Annotated[OperationClient, Depends(get_operation_client)]


@app.post("/compute", response_model=ComputeResponse)
def compute(request: ComputeRequest, operation: OperationDep) -> ComputeResponse:
    try:
        response = operation.numeric_op(request.a, request.b)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"operation service returned {exc.response.status_code}",
        ) from exc
    except httpx.TransportError as exc:
        raise HTTPException(status_code=503, detail="operation service unavailable") from exc
    return ComputeResponse(result=response.result, source="operation")


@app.get("/health")
def health(operation: OperationDep) -> dict[str, str]:
    return {"status": "ok", "operation": "ok" if operation.health() else "unreachable"}

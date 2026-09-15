"""This repo's copy of the operation service's HTTP contract.

ApiAgentService2 deploys on its own, so it does not install ApiAgentService1 as a package.
The models and client here mirror the `/v1/operation` contract that ApiAgentService1 publishes.
When that contract changes upstream, this file has to change with it.
"""

import httpx
from pydantic import BaseModel


class NumericOpRequest(BaseModel):
    a: float
    b: float


class NumericOpResponse(BaseModel):
    result: float


class OperationClient:
    """Typed HTTP client for the operation service.

    Raises httpx.HTTPStatusError for non-2xx responses and httpx.TransportError
    (e.g. ConnectError, TimeoutException) when the service can't be reached.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def numeric_op(self, a: float, b: float) -> NumericOpResponse:
        response = self._http.post(
            "/v1/operation/numeric_op", json=NumericOpRequest(a=a, b=b).model_dump()
        )
        response.raise_for_status()
        return NumericOpResponse.model_validate(response.json())

    def health(self) -> bool:
        try:
            response = self._http.get("/health")
        except httpx.TransportError:
            return False
        return response.is_success

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OperationClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

# consumer (ApiAgentService2)

A downstream service that calls the `operation` service (ApiAgentService1). It uses the typed client `operation.OperationClient`, which it installs from `../ApiAgentService1` as an editable path dependency.

## Run

Start ApiAgentService1 on port 8001 first. Then run:

```sh
uv sync
uv run uvicorn consumer.app:app --port 8002 --reload
```

The upstream URL comes from `OPERATION_BASE_URL` (default `http://localhost:8001`).

## API

| Method | Path       | Body               | Response                                  |
|--------|------------|--------------------|-------------------------------------------|
| POST   | `/compute` | `{"a": 2, "b": 3}` | `{"result": 5.0, "source": "operation"}`  |
| GET    | `/health`  |                    | `{"status": "ok", "operation": "ok"}`     |

Errors: `422` for bad input, `502` if operation returns an error, and `503` if operation can't be reached.

```sh
curl -X POST localhost:8002/compute -H 'content-type: application/json' -d '{"a":2,"b":3}'
```

## Test

```sh
uv run pytest
```

The tests mock the upstream service with `httpx.MockTransport`, so ApiAgentService1 doesn't need to be running.

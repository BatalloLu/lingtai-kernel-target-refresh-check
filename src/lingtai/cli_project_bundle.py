"""Recipe bundle composition root: installed resources plus bound native I/O."""
from __future__ import annotations

import json
import sys

from lingtai.adapters.project_bundle import PackagedRecipeBundleAdapter
from lingtai.adapters.project_bundle_exchange import (
    BundleExchangeStopped, JsonRecipeBundleAdapter, read_bundle_request,
)
from lingtai.kernel.project.bundle import RecipeBundleUseCase


def handle_bundle_command() -> None:
    code = "invalid_bundle_request"
    try:
        request, binding = read_bundle_request(sys.stdin)
        code = "bundle_driver_failed"
        exchange = JsonRecipeBundleAdapter(binding, sys.stdin, sys.stdout)
        result = RecipeBundleUseCase(exchange, PackagedRecipeBundleAdapter()).materialize(request)
        payload = exchange.terminal(result)
    except BundleExchangeStopped:
        code = "invalid_bundle_exchange"
        payload = None
    except Exception:
        payload = None
    if payload is None:
        # Earlier native writes can survive any abnormal exchange/resource read.
        # No exception/input text or normal terminal can disguise that uncertainty.
        sys.stderr.write(json.dumps({"status": "error", "code": code,
                                    "error": "Recipe bundle exchange did not complete"}, sort_keys=True) + "\n")
        sys.stderr.flush()
        raise SystemExit(1)
    # Exit zero means accepted domain result, NOT successful copy. Known native
    # refusal/failure is carried by code/failure and mapped from retained Go errors.
    sys.stdout.write(json.dumps(payload, sort_keys=True, ensure_ascii=True) + "\n")
    sys.stdout.flush()

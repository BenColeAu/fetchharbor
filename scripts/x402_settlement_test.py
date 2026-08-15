"""Perform an opt-in, real Base Sepolia x402 settlement test."""

import asyncio
import os

import httpx
from eth_account import Account
from x402 import x402Client
from x402.http import x402HTTPClient
from x402.http.clients import x402HttpxClient
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact.register import register_exact_evm_client


async def main() -> None:
    private_key = os.environ.get("EVM_PRIVATE_KEY")
    if not private_key:
        raise RuntimeError("EVM_PRIVATE_KEY is required")
    endpoint = os.environ.get(
        "FETCHHARBOR_TEST_URL", "http://127.0.0.1:8080/html-to-md"
    )
    account = Account.from_key(private_key)

    async with httpx.AsyncClient(trust_env=False) as unpaid_client:
        unpaid = await unpaid_client.get(endpoint, params={"html": "<h1>Paid</h1>"})
    if unpaid.status_code != 402 or "payment-required" not in unpaid.headers:
        raise RuntimeError(
            f"expected an x402 challenge, received HTTP {unpaid.status_code}"
        )

    client = x402Client()
    register_exact_evm_client(client, EthAccountSigner(account))
    response_parser = x402HTTPClient(client)
    async with x402HttpxClient(client) as paid_client:
        paid = await paid_client.get(endpoint, params={"html": "<h1>Paid</h1>"})
        await paid.aread()

    if not paid.is_success:
        raise RuntimeError(
            f"paid request failed with HTTP {paid.status_code}: {paid.text}"
        )
    settlement = response_parser.get_payment_settle_response(paid.headers.get)
    if settlement is None or not settlement.success:
        raise RuntimeError(
            "paid response did not contain a successful settlement receipt"
        )
    if paid.json().get("markdown") != "# Paid":
        raise RuntimeError("paid endpoint returned an unexpected response")

    print(
        "x402 Base Sepolia settlement succeeded",
        {"transaction": settlement.transaction, "network": settlement.network},
    )


if __name__ == "__main__":
    asyncio.run(main())

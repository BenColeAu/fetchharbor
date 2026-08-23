from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter

Handler = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class ServiceDefinition:
    name: str
    path: str
    description: str
    price_usdc: str
    router: APIRouter
    methods: tuple[str, ...] = ("GET", "POST")
    input_schema: dict[str, Any] = field(default_factory=dict)
    input_example: dict[str, Any] = field(default_factory=dict)
    method_input_schemas: dict[str, dict[str, Any]] = field(default_factory=dict)
    method_input_examples: dict[str, dict[str, Any]] = field(default_factory=dict)
    body_types: dict[str, str] = field(default_factory=dict)
    output_example: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)

    def input_schema_for(self, method: str) -> dict[str, Any]:
        return self.method_input_schemas.get(method.upper(), self.input_schema)

    def input_example_for(self, method: str) -> dict[str, Any]:
        return self.method_input_examples.get(method.upper(), self.input_example)


class ServiceRegistry:
    def __init__(self) -> None:
        self._services: dict[str, ServiceDefinition] = {}

    def register(self, service: ServiceDefinition) -> None:
        if service.name in self._services:
            raise ValueError(f"Service already registered: {service.name}")
        self._services[service.name] = service

    @property
    def services(self) -> tuple[ServiceDefinition, ...]:
        return tuple(self._services.values())

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "name": s.name,
                "path": s.path,
                "methods": s.methods,
                "price_usdc": s.price_usdc,
                "description": s.description,
            }
            for s in self.services
        ]

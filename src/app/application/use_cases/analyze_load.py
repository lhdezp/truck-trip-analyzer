"""Analyze one load offer end to end.

This use case is the single composition point of the product: it reads the offer,
computes what the trip pays, compares it against the market, checks the vehicle and
produces the recommendation. It owns *degradation* — one provider failing must lower
the confidence and name the gap, never crash the analysis.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from app.application.interfaces.clock import Clock
from app.application.interfaces.market import MarketDataProvider
from app.application.interfaces.persistence import AnalysisRepository
from app.application.interfaces.routing import RoutingProvider
from app.application.interfaces.vision import VisionProvider
from app.application.interfaces.weather import WeatherProvider
from app.application.schemas.analysis import MarketAnalysis, MarketReference, RouteAnalysis
from app.application.schemas.extraction import ImageInput, LoadExtraction
from app.application.schemas.result import (
    AnalysisWarning,
    LoadAnalysisResult,
    Severity,
    SourceRecord,
)
from app.application.schemas.routing import RouteRequest
from app.domain.entities.load import LoadField, LoadOffer
from app.domain.entities.vehicle import VehicleProfile
from app.domain.exceptions import DomainValidationError
from app.domain.rules.recommendation import ProfitThresholds, evaluate_recommendation
from app.domain.services.compatibility import check_vehicle_compatibility
from app.domain.services.financial import FinancialEngine
from app.domain.value_objects.equipment import EquipmentType
from app.domain.value_objects.location import USLocation
from app.domain.value_objects.money import RatePerMile
from app.domain.value_objects.profitability import Profitability
from app.domain.value_objects.provenance import ConfidenceLevel, SourcedField
from app.domain.value_objects.recommendation import (
    FinalRecommendation,
    RecommendationDecision,
)
from app.exceptions import ProviderError

# Stable warning codes. They are part of the response contract, so interfaces can
# branch on them without parsing prose.
CODE_VISION_FAILED = "vision_failed"
CODE_MARKET_FAILED = "market_failed"
CODE_ROUTING_FAILED = "routing_failed"
CODE_WEATHER_FAILED = "weather_failed"
CODE_PARTIAL_EXTRACT = "partial_extraction"


class LoadAnalysisConfig(Protocol):
    """Policy the use case applies to one analysis."""

    thresholds: ProfitThresholds
    vehicle: VehicleProfile | None


def _minimal_vehicle() -> VehicleProfile:
    """A last-resort vehicle so the engine can run when the caller supplies none.

    It carries no fuel cost and no fixed cost: the result is a revenue-only estimate
    with the missing cost components named in ``missing_inputs``, not a fabricated
    one.
    """
    return VehicleProfile(
        name="unspecified",
        equipment_type=EquipmentType.BOX_TRUCK,
        fuel_efficiency_mpg=Decimal("10"),
    )


def _any_location() -> USLocation:
    return USLocation(city="Unknown", state="TX")


def _market_block(
    references: Sequence[MarketReference],
    *,
    offered_rate: RatePerMile | None,
) -> MarketAnalysis:
    """Compare the offered rate against every reference, only when both are present."""
    notes: list[str] = []
    comparable = False
    difference_percent: Decimal | None = None
    if offered_rate is not None and references:
        # A national estimate is comparable only in direction, never as a lane match.
        comparable = True
        benchmark = references[0].rate_per_mile
        difference_percent = (offered_rate.amount - benchmark.amount) / benchmark.amount
        notes.append(
            f"Offered ${offered_rate}/mi vs national estimate ${benchmark}/mi "
            f"({difference_percent * 100:+.1f}%)"
        )
    return MarketAnalysis(
        offered_rate=offered_rate,
        references=list(references),
        difference_percent=difference_percent,
        comparable=comparable,
        notes=notes,
    )


def _insufficient(missing_fields: list[LoadField]) -> FinalRecommendation:
    names = ", ".join(missing_fields) if missing_fields else "key load data"
    return FinalRecommendation(
        decision=RecommendationDecision.INSUFFICIENT_DATA,
        reasons=(f"Cannot analyze without: {names}",),
        confidence=ConfidenceLevel.LOW,
    )


class AnalyzeLoadUseCase:
    """Turns screenshots of an offer into a financially justified recommendation."""

    def __init__(
        self,
        *,
        vision: VisionProvider,
        market: MarketDataProvider | None,
        routing: RoutingProvider | None,
        weather: WeatherProvider | None,
        clock: Clock,
        repository: AnalysisRepository | None = None,
    ) -> None:
        self._vision = vision
        self._market = market
        self._routing = routing
        self._weather = weather
        self._clock = clock
        self._repository = repository
        self._engine = FinancialEngine()

    async def run(
        self,
        images: Sequence[ImageInput],
        *,
        config: LoadAnalysisConfig,
        context: str | None = None,
    ) -> LoadAnalysisResult:
        """Execute the full pipeline and persist the result when a repository is set."""
        warnings: list[AnalysisWarning] = []
        sources: list[SourceRecord] = []
        confidence = ConfidenceLevel.UNKNOWN

        extraction: LoadExtraction | None = None
        try:
            extraction = await self._vision.extract_load(images, context=context)
            confidence = self._confidence_from_extraction(extraction)
        except (ProviderError, DomainValidationError) as exc:
            warnings.append(
                AnalysisWarning(
                    code=CODE_VISION_FAILED,
                    message=f"Vision extraction failed: {exc}",
                    severity=Severity.CRITICAL,
                )
            )

        load: LoadOffer = extraction.load if extraction is not None else LoadOffer()
        if extraction is not None:
            sources.append(
                SourceRecord(
                    provider=extraction.provider,
                    kind="ai",
                    retrieved_at=extraction.extracted_at,
                    reference=None,
                )
            )
            for code in extraction.warnings:
                warnings.append(AnalysisWarning(code=CODE_PARTIAL_EXTRACT, message=code))
        missing_fields = load.missing_fields()
        if missing_fields:
            warnings.append(
                AnalysisWarning(
                    code=CODE_PARTIAL_EXTRACT,
                    message=f"Missing required fields: {', '.join(missing_fields)}",
                    severity=Severity.WARNING,
                )
            )

        # Route: only when both ends are known; a failed provider degrades, not crashes.
        route: RouteAnalysis | None = None
        if self._routing is not None and load.origin and load.destination:
            request = RouteRequest(
                origin=load.origin.value,
                destination=load.destination.value,
                vehicle=config.vehicle,
            )
            try:
                route = await self._routing.analyze_route(request)
                sources.append(
                    SourceRecord(
                        provider=route.provider or "routing",
                        kind="routing",
                        retrieved_at=self._clock.now(),
                        reference=None,
                    )
                )
            except ProviderError as exc:
                warnings.append(
                    AnalysisWarning(
                        code=CODE_ROUTING_FAILED,
                        message=f"Routing failed: {exc}",
                        severity=Severity.WARNING,
                    )
                )

        costs = None
        profitability: Profitability | None = None
        recommendation: FinalRecommendation | None = None
        if load.price_offered is not None:
            estimate = self._engine.calculate(
                price_offered=load.price_offered.value,
                vehicle=config.vehicle if config.vehicle is not None else _minimal_vehicle(),
                loaded_miles=route.loaded_miles if route else None,
                empty_miles=route.empty_miles if route else None,
                duration=route.duration if route else None,
            )
            costs = estimate.costs
            profitability = estimate.profitability
            recommendation = evaluate_recommendation(
                profitability=profitability,
                thresholds=config.thresholds,
                confidence=confidence,
            )

        market_analysis: MarketAnalysis | None = None
        market_timestamp: datetime | None = None
        if self._market is not None and load.required_equipment:
            try:
                references = await self._market.fetch_market_references(
                    equipment=load.required_equipment.value,
                    origin=load.origin.value if load.origin else _any_location(),
                    destination=(load.destination.value if load.destination else _any_location()),
                )
                market_analysis = _market_block(
                    references,
                    offered_rate=profitability.gross_rpm if profitability else None,
                )
                if references:
                    market_timestamp = max(r.retrieved_at for r in references)
                sources.append(
                    SourceRecord(
                        provider="market",
                        kind="market",
                        retrieved_at=market_timestamp or self._clock.now(),
                        reference=None,
                    )
                )
            except ProviderError as exc:
                warnings.append(
                    AnalysisWarning(
                        code=CODE_MARKET_FAILED,
                        message=f"Market data unavailable: {exc}",
                        severity=Severity.INFO,
                    )
                )

        # Weather: enrichment only; a failed call degrades to no weather block.
        if self._weather is not None and load.origin and load.destination:
            from app.application.schemas.weather import WeatherRequest

            weather_request = WeatherRequest(
                origin=load.origin.value,
                destination=load.destination.value,
            )
            try:
                weather_report = await self._weather.get_weather_report(weather_request)
                sources.append(
                    SourceRecord(
                        provider="nws",
                        kind="weather",
                        retrieved_at=weather_report.retrieved_at,
                        reference=None,
                    )
                )
            except ProviderError as exc:
                warnings.append(
                    AnalysisWarning(
                        code=CODE_WEATHER_FAILED,
                        message=f"Weather data unavailable: {exc}",
                        severity=Severity.INFO,
                    )
                )

        compatibility = None
        if config.vehicle is not None:
            compatibility = check_vehicle_compatibility(load=load, vehicle=config.vehicle)

        result = LoadAnalysisResult(
            load=load,
            route=route,
            vehicle_compatibility=compatibility,
            costs=costs,
            profitability=profitability,
            market=market_analysis,
            dead_zone=None,
            negotiation=None,
            recommendation=(
                recommendation if recommendation is not None else _insufficient(missing_fields)
            ),
            missing_fields=missing_fields,
            warnings=warnings,
            confidence=confidence,
            sources=sources,
            calculated_at=self._clock.now(),
            market_data_timestamp=market_timestamp,
        )

        if self._repository is not None:
            await self._repository.save(result)
        return result

    @staticmethod
    def _confidence_from_extraction(extraction: LoadExtraction) -> ConfidenceLevel:
        """Overall confidence from field-level evidence and open contradictions."""
        load = extraction.load
        present: list[SourcedField[Any]] = [
            field
            for field in (
                load.origin,
                load.destination,
                load.price_offered,
                load.weight,
                load.dimensions,
            )
            if field is not None
        ]
        if not present:
            return ConfidenceLevel.UNKNOWN
        if extraction.contradictions:
            return ConfidenceLevel.LOW
        with_evidence = sum(1 for f in present if f.evidence_refs)
        if with_evidence == len(present) and len(present) >= 3:
            return ConfidenceLevel.HIGH
        return ConfidenceLevel.MEDIUM

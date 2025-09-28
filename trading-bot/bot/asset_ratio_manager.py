"""
Asset Ratio Management System

Manages the target 1:1 USDM:ADA value ratio and provides dynamic
spread/liquidity adjustments based on asset imbalances.
"""

from dataclasses import dataclass
import time

import structlog

from .config import settings

logger = structlog.get_logger()


@dataclass
class AssetBalance:
    """Asset balance information"""

    asset: str
    quantity: float
    value_usd: float  # USD equivalent value
    timestamp: float


@dataclass
class RatioAdjustment:
    """Adjustment factors based on asset ratio imbalance"""

    bid_spread_multiplier: float
    ask_spread_multiplier: float
    bid_liquidity_multiplier: float
    ask_liquidity_multiplier: float
    imbalance_ratio: float  # current_ratio / target_ratio


class AssetRatioManager:
    """
    Manages asset ratio balancing and calculates adjustment factors
    for spread and liquidity based on USDM:ADA ratio deviations.
    """

    def __init__(self):
        self.balances: dict[str, AssetBalance] = {}
        self.last_adjustment_time = 0.0

    async def update_balance(self, asset: str, quantity: float, price_usd: float):
        """Update asset balance information"""
        current_time = time.time()
        value_usd = quantity * price_usd

        self.balances[asset] = AssetBalance(
            asset=asset, quantity=quantity, value_usd=value_usd, timestamp=current_time
        )

        logger.debug(
            "Updated asset balance",
            asset=asset,
            quantity=quantity,
            value_usd=value_usd,
            price_usd=price_usd,
        )

    def get_current_ratio(self) -> float | None:
        """
        Calculate current USDM:ADA value ratio

        Returns:
            current_ratio = usdm_value / ada_value, or None if data unavailable
        """
        usdm_balance = self.balances.get("USDM")
        ada_balance = self.balances.get("ADA")

        if not usdm_balance or not ada_balance:
            return None

        if ada_balance.value_usd == 0:
            return None

        return usdm_balance.value_usd / ada_balance.value_usd

    def is_ratio_within_tolerance(self) -> tuple[bool, float | None]:
        """
        Check if current ratio is within acceptable tolerance

        Returns:
            (is_within_tolerance, current_ratio)
        """
        current_ratio = self.get_current_ratio()
        if current_ratio is None:
            return False, None

        target_ratio = settings.trading.target_asset_ratio
        tolerance = settings.trading.ratio_tolerance

        deviation = abs(current_ratio - target_ratio) / target_ratio
        is_within = deviation <= tolerance

        return is_within, current_ratio

    def get_ratio_adjustment(self) -> RatioAdjustment:
        """
        Calculate spread and liquidity adjustments based on asset ratio imbalance

        Returns:
            RatioAdjustment with multipliers for spreads and liquidity
        """
        current_ratio = self.get_current_ratio()
        if current_ratio is None:
            # No data available, return neutral adjustments
            return RatioAdjustment(
                bid_spread_multiplier=1.0,
                ask_spread_multiplier=1.0,
                bid_liquidity_multiplier=1.0,
                ask_liquidity_multiplier=1.0,
                imbalance_ratio=1.0,
            )

        target_ratio = settings.trading.target_asset_ratio
        imbalance_ratio = current_ratio / target_ratio

        # Calculate adjustment factors
        spread_factor = settings.trading.spread_adjustment_factor
        liquidity_factor = settings.trading.liquidity_adjustment_factor

        if imbalance_ratio > 1.0:
            # Excess USDM scenario (USDM > ADA)
            # Need to buy more ADA, sell less ADA
            excess_factor = imbalance_ratio - 1.0

            # Bid orders (buying ADA): tighter spreads, more liquidity
            bid_spread_multiplier = max(0.1, 1.0 - excess_factor * spread_factor)
            bid_liquidity_multiplier = 1.0 + excess_factor * liquidity_factor

            # Ask orders (selling ADA): wider spreads, less liquidity
            ask_spread_multiplier = 1.0 + excess_factor * spread_factor
            ask_liquidity_multiplier = max(0.1, 1.0 - excess_factor * liquidity_factor)

        else:
            # Excess ADA scenario (ADA > USDM)
            # Need to sell more ADA, buy less ADA
            deficit_factor = 1.0 - imbalance_ratio

            # Ask orders (selling ADA): tighter spreads, more liquidity
            ask_spread_multiplier = max(0.1, 1.0 - deficit_factor * spread_factor)
            ask_liquidity_multiplier = 1.0 + deficit_factor * liquidity_factor

            # Bid orders (buying ADA): wider spreads, less liquidity
            bid_spread_multiplier = 1.0 + deficit_factor * spread_factor
            bid_liquidity_multiplier = max(0.1, 1.0 - deficit_factor * liquidity_factor)

        adjustment = RatioAdjustment(
            bid_spread_multiplier=bid_spread_multiplier,
            ask_spread_multiplier=ask_spread_multiplier,
            bid_liquidity_multiplier=bid_liquidity_multiplier,
            ask_liquidity_multiplier=ask_liquidity_multiplier,
            imbalance_ratio=imbalance_ratio,
        )

        # Log the adjustment if it's significant
        if abs(imbalance_ratio - 1.0) > settings.trading.ratio_tolerance:
            logger.info(
                "Asset ratio imbalance detected",
                current_ratio=current_ratio,
                target_ratio=target_ratio,
                imbalance_ratio=imbalance_ratio,
                bid_spread_mult=bid_spread_multiplier,
                ask_spread_mult=ask_spread_multiplier,
                bid_liquidity_mult=bid_liquidity_multiplier,
                ask_liquidity_mult=ask_liquidity_multiplier,
            )

        return adjustment

    def get_capital_allocation(self) -> tuple[float, float]:
        """
        Calculate bid/ask capital allocation percentages based on asset ratio

        Returns:
            (bid_allocation_pct, ask_allocation_pct) - should sum to 1.0
        """
        current_ratio = self.get_current_ratio()
        if current_ratio is None:
            return 0.5, 0.5  # Equal allocation if no data

        target_ratio = settings.trading.target_asset_ratio
        imbalance_ratio = current_ratio / target_ratio

        if imbalance_ratio > 1.0:
            # Excess USDM - allocate more to bid orders (buying ADA)
            excess_factor = min(imbalance_ratio - 1.0, 1.0)  # Cap at 1.0
            bid_allocation = 0.5 + (excess_factor * 0.3)  # Up to 80% for bids
            ask_allocation = 1.0 - bid_allocation
        else:
            # Excess ADA - allocate more to ask orders (selling ADA)
            deficit_factor = min(1.0 - imbalance_ratio, 1.0)  # Cap at 1.0
            ask_allocation = 0.5 + (deficit_factor * 0.3)  # Up to 80% for asks
            bid_allocation = 1.0 - ask_allocation

        return bid_allocation, ask_allocation

    def get_status(self) -> dict[str, any]:
        """Get current asset ratio manager status"""
        current_ratio = self.get_current_ratio()
        is_within_tolerance, _ = self.is_ratio_within_tolerance()
        adjustment = self.get_ratio_adjustment()
        bid_alloc, ask_alloc = self.get_capital_allocation()

        return {
            "balances": {
                asset: {
                    "quantity": balance.quantity,
                    "value_usd": balance.value_usd,
                    "age_ms": (time.time() - balance.timestamp) * 1000,
                }
                for asset, balance in self.balances.items()
            },
            "current_ratio": current_ratio,
            "target_ratio": settings.trading.target_asset_ratio,
            "is_within_tolerance": is_within_tolerance,
            "imbalance_ratio": adjustment.imbalance_ratio,
            "adjustments": {
                "bid_spread_multiplier": adjustment.bid_spread_multiplier,
                "ask_spread_multiplier": adjustment.ask_spread_multiplier,
                "bid_liquidity_multiplier": adjustment.bid_liquidity_multiplier,
                "ask_liquidity_multiplier": adjustment.ask_liquidity_multiplier,
            },
            "capital_allocation": {
                "bid_percentage": bid_alloc,
                "ask_percentage": ask_alloc,
            },
        }

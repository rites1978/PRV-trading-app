"""
🏛️ PRV CAPITAL | STRONG TYPE & UNIT MODEL FOR MONEY
Eliminates raw-number currency ambiguity across all brokers, engines, and reports.
Enforces:
1. Strict currency awareness (GBP, GBX, USD, EUR)
2. Unit distinction (MAJOR vs MINOR, e.g. pence vs pounds)
3. Provenance tracking (source and UTC timestamp)
4. Illegal arithmetic protection (USD + GBP prohibited)
5. Authoritative market value calculation:
   market_value_gbp = quantity * native_price * currency_conversion * unit_conversion
"""
from enum import Enum
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Union


class CurrencyMismatchError(TypeError):
    """Raised when arithmetic is attempted between mismatched currencies or units."""
    pass


class Currency(str, Enum):
    GBP = "GBP"
    GBX = "GBX"  # Pence sterling (LSE standard quote currency)
    USD = "USD"
    EUR = "EUR"


class CurrencyUnit(str, Enum):
    MAJOR = "MAJOR"  # e.g., Pounds, Dollars
    MINOR = "MINOR"  # e.g., Pence, Cents


class Money:
    """
    Immutable value object representing a monetary quantity in a specific currency and unit.
    """
    __slots__ = ("_amount", "_currency", "_unit", "_source", "_timestamp")

    def __init__(
        self,
        amount: Union[float, int],
        currency: Union[str, Currency],
        unit: Optional[Union[str, CurrencyUnit]] = None,
        source: str = "INTERNAL",
        timestamp: Optional[str] = None
    ):
        amt = float(amount)
        curr_str = str(currency).upper()
        if curr_str.startswith("CURRENCY."):
            curr_str = curr_str.split(".")[-1]

        if curr_str not in ("GBP", "GBX", "USD", "EUR"):
            raise ValueError(f"Unsupported currency: {currency}")

        if unit is None:
            unit_val = CurrencyUnit.MINOR if curr_str == "GBX" else CurrencyUnit.MAJOR
        else:
            unit_str = str(unit).upper()
            if unit_str.startswith("CURRENCYUNIT."):
                unit_str = unit_str.split(".")[-1]
            unit_val = CurrencyUnit(unit_str)

        self._amount: float = round(amt, 6)
        self._currency: Currency = Currency(curr_str)
        self._unit: CurrencyUnit = unit_val
        self._source: str = source
        self._timestamp: str = timestamp or datetime.now(timezone.utc).isoformat()

    @property
    def amount(self) -> float:
        return self._amount

    @property
    def currency(self) -> Currency:
        return self._currency

    @property
    def unit(self) -> CurrencyUnit:
        return self._unit

    @property
    def source(self) -> str:
        return self._source

    @property
    def timestamp(self) -> str:
        return self._timestamp

    def to_major(self) -> "Money":
        """Normalize minor units to major units (e.g. 1545.2 GBX -> 15.452 GBP)."""
        if self._unit == CurrencyUnit.MINOR:
            if self._currency == Currency.GBX:
                return Money(
                    amount=self._amount / 100.0,
                    currency=Currency.GBP,
                    unit=CurrencyUnit.MAJOR,
                    source=f"{self._source}_NORMALIZED_TO_MAJOR",
                    timestamp=self._timestamp
                )
            return Money(
                amount=self._amount / 100.0,
                currency=self._currency,
                unit=CurrencyUnit.MAJOR,
                source=f"{self._source}_NORMALIZED_TO_MAJOR",
                timestamp=self._timestamp
            )
        return self

    def to_minor(self) -> "Money":
        """Convert major units to minor units (e.g. 15.452 GBP -> 1545.2 GBX)."""
        if self._unit == CurrencyUnit.MAJOR:
            if self._currency == Currency.GBP:
                return Money(
                    amount=self._amount * 100.0,
                    currency=Currency.GBX,
                    unit=CurrencyUnit.MINOR,
                    source=f"{self._source}_CONVERTED_TO_MINOR",
                    timestamp=self._timestamp
                )
            return Money(
                amount=self._amount * 100.0,
                currency=self._currency,
                unit=CurrencyUnit.MINOR,
                source=f"{self._source}_CONVERTED_TO_MINOR",
                timestamp=self._timestamp
            )
        return self

    def to_gbp(self, fx_rate_usd_to_gbp: Optional[float] = None) -> "Money":
        """
        Convert any money object to normalized GBP in major units.
        - GBP (MAJOR): identity.
        - GBX (MINOR): divided by 100.0.
        - USD (MAJOR): multiplied by fx_rate_usd_to_gbp (e.g. 1.0 / 1.35 = 0.7407).
        """
        if self._currency == Currency.GBP:
            return self.to_major()
        
        if self._currency == Currency.GBX:
            return self.to_major()

        if self._currency == Currency.USD:
            if fx_rate_usd_to_gbp is None or fx_rate_usd_to_gbp <= 0:
                raise ValueError("Valid fx_rate_usd_to_gbp is required to convert USD to GBP")
            return Money(
                amount=self._amount * fx_rate_usd_to_gbp,
                currency=Currency.GBP,
                unit=CurrencyUnit.MAJOR,
                source=f"{self._source}_FX_TO_GBP",
                timestamp=self._timestamp
            )

        raise ValueError(f"Conversion from {self._currency} to GBP not configured")

    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            raise TypeError(f"Cannot add Money and non-Money type {type(other)}")
        if self._currency != other._currency or self._unit != other._unit:
            raise CurrencyMismatchError(
                f"Cannot add {self._currency.value} ({self._unit.value}) and {other._currency.value} ({other._unit.value}). "
                f"Normalize to matching currency and unit first."
            )
        return Money(
            amount=self._amount + other._amount,
            currency=self._currency,
            unit=self._unit,
            source="CALCULATED_ADD",
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    def __sub__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            raise TypeError(f"Cannot subtract non-Money type {type(other)} from Money")
        if self._currency != other._currency or self._unit != other._unit:
            raise CurrencyMismatchError(
                f"Cannot subtract {other._currency.value} ({other._unit.value}) from {self._currency.value} ({self._unit.value}). "
                f"Normalize to matching currency and unit first."
            )
        return Money(
            amount=self._amount - other._amount,
            currency=self._currency,
            unit=self._unit,
            source="CALCULATED_SUB",
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    def __mul__(self, scalar: Union[float, int]) -> "Money":
        if isinstance(scalar, Money):
            raise TypeError("Cannot multiply Money by Money")
        return Money(
            amount=self._amount * float(scalar),
            currency=self._currency,
            unit=self._unit,
            source="CALCULATED_MUL",
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    def __rmul__(self, scalar: Union[float, int]) -> "Money":
        return self.__mul__(scalar)

    def __truediv__(self, divisor: Union[float, int, "Money"]) -> Union["Money", float]:
        if isinstance(divisor, Money):
            if self._currency != divisor._currency or self._unit != divisor._unit:
                raise CurrencyMismatchError(
                    f"Cannot divide {self._currency.value} by {divisor._currency.value} without conversion"
                )
            if divisor._amount == 0:
                raise ZeroDivisionError("Division of Money by zero Money")
            return self._amount / divisor._amount

        div_val = float(divisor)
        if div_val == 0:
            raise ZeroDivisionError("Division of Money by zero scalar")
        return Money(
            amount=self._amount / div_val,
            currency=self._currency,
            unit=self._unit,
            source="CALCULATED_DIV",
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    def __neg__(self) -> "Money":
        return Money(
            amount=-self._amount,
            currency=self._currency,
            unit=self._unit,
            source="CALCULATED_NEG",
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    def __abs__(self) -> "Money":
        return Money(
            amount=abs(self._amount),
            currency=self._currency,
            unit=self._unit,
            source="CALCULATED_ABS",
            timestamp=datetime.now(timezone.utc).isoformat()
        )

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Money):
            return False
        return (
            abs(self._amount - other._amount) < 1e-6 and
            self._currency == other._currency and
            self._unit == other._unit
        )

    def __lt__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            raise TypeError(f"Cannot compare Money and {type(other)}")
        if self._currency != other._currency or self._unit != other._unit:
            raise CurrencyMismatchError(
                f"Cannot compare {self._currency.value} ({self._unit.value}) and {other._currency.value} ({other._unit.value})"
            )
        return self._amount < other._amount

    def __le__(self, other: "Money") -> bool:
        return self < other or self == other

    def __gt__(self, other: "Money") -> bool:
        return not self <= other

    def __ge__(self, other: "Money") -> bool:
        return not self < other

    def format(self, decimals: int = 2) -> str:
        """Standardized formatted currency representation with proper symbol and unit."""
        if self._currency == Currency.GBP:
            if self._unit == CurrencyUnit.MINOR:
                return f"{self._amount:,.{decimals}f}p"
            return f"£{self._amount:,.{decimals}f}"
        elif self._currency == Currency.GBX:
            return f"{self._amount:,.{decimals}f} GBX"
        elif self._currency == Currency.USD:
            return f"${self._amount:,.{decimals}f}"
        elif self._currency == Currency.EUR:
            return f"€{self._amount:,.{decimals}f}"
        return f"{self._amount:,.{decimals}f} {self._currency.value}"

    def __repr__(self) -> str:
        return f"Money({self._amount:.4f}, {self._currency.value}, {self._unit.value}, source='{self._source}')"

    def __str__(self) -> str:
        return self.format()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "amount": round(self._amount, 4),
            "currency": self._currency.value,
            "unit": self._unit.value,
            "source": self._source,
            "timestamp": self._timestamp,
            "formatted": self.format()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Money":
        return cls(
            amount=data["amount"],
            currency=data["currency"],
            unit=data.get("unit"),
            source=data.get("source", "DESERIALIZED"),
            timestamp=data.get("timestamp")
        )

    @staticmethod
    def calculate_market_value_gbp(
        quantity: float,
        native_price: "Money",
        fx_rate_usd_to_gbp: Optional[float] = None
    ) -> "Money":
        """
        Authoritative calculation:
        market_value_gbp = quantity * native_price * currency_conversion * unit_conversion
        """
        price_gbp = native_price.to_gbp(fx_rate_usd_to_gbp=fx_rate_usd_to_gbp)
        total_gbp = price_gbp.amount * quantity
        return Money(
            amount=round(total_gbp, 4),
            currency=Currency.GBP,
            unit=CurrencyUnit.MAJOR,
            source="CALCULATE_MARKET_VALUE_GBP"
        )

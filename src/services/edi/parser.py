"""
EDI Parser — X12 835 (ERA) and 837 (Claim) parsing and generation.
Handles ANSI X12 transaction sets for healthcare billing.
"""

import structlog
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from enum import Enum

logger = structlog.get_logger()


# ── Data Models ──────────────────────────────────────────────────

class AdjustmentGroupCode(str, Enum):
    CO = "CO"  # Contractual Obligation
    PR = "PR"  # Patient Responsibility
    OA = "OA"  # Other Adjustment
    PI = "PI"  # Payor Initiated Reduction
    CR = "CR"  # Correction/Reversal


@dataclass
class EDIAdjustment:
    group_code: AdjustmentGroupCode
    reason_code: str        # CARC code
    amount: Decimal
    quantity: int | None = None
    remark_codes: list[str] = field(default_factory=list)

    @property
    def is_denial(self) -> bool:
        """Common denial CARC codes."""
        denial_codes = {
            "4", "5", "6", "9", "10", "11", "15", "16", "18", "19",
            "26", "27", "29", "31", "32", "33", "34", "35", "39",
            "49", "50", "51", "55", "58", "96", "97", "107", "109",
            "119", "148", "149", "150", "151", "152", "167", "170",
            "171", "172", "177", "178", "179", "181", "182", "186",
            "187", "188", "189", "190", "192", "193", "194", "197",
            "198", "199", "200", "201", "202", "203", "204", "205",
            "206", "207", "208", "209", "210", "211", "212", "213",
            "215", "216", "219", "222", "223", "224", "225", "226",
            "227", "228", "229", "231", "232", "233", "234", "235",
            "236", "237", "238", "239", "240", "241", "242", "243",
        }
        return self.reason_code in denial_codes


@dataclass
class EDIServiceLine:
    procedure_code: str
    modifiers: list[str] = field(default_factory=list)
    charge_amount: Decimal = Decimal("0")
    paid_amount: Decimal = Decimal("0")
    allowed_amount: Decimal | None = None
    units: int = 1
    service_date_from: date | None = None
    service_date_to: date | None = None
    adjustments: list[EDIAdjustment] = field(default_factory=list)
    control_number: str = ""
    revenue_code: str = ""
    ndc: str = ""

    @property
    def patient_responsibility(self) -> Decimal:
        return sum(
            adj.amount for adj in self.adjustments
            if adj.group_code == AdjustmentGroupCode.PR
        )

    @property
    def contractual_adjustment(self) -> Decimal:
        return sum(
            adj.amount for adj in self.adjustments
            if adj.group_code == AdjustmentGroupCode.CO
        )

    @property
    def denials(self) -> list[EDIAdjustment]:
        return [adj for adj in self.adjustments if adj.is_denial]


@dataclass
class EDIClaim:
    claim_id: str
    patient_name: str = ""
    patient_id: str = ""
    payer_claim_number: str = ""
    status_code: str = ""
    total_charge: Decimal = Decimal("0")
    total_paid: Decimal = Decimal("0")
    patient_responsibility: Decimal = Decimal("0")
    service_lines: list[EDIServiceLine] = field(default_factory=list)
    claim_adjustments: list[EDIAdjustment] = field(default_factory=list)
    service_date_from: date | None = None
    service_date_to: date | None = None
    rendering_provider_npi: str = ""
    rendering_provider_name: str = ""

    @property
    def has_denials(self) -> bool:
        return any(
            adj.is_denial
            for line in self.service_lines
            for adj in line.adjustments
        ) or any(adj.is_denial for adj in self.claim_adjustments)


@dataclass
class EDIPaymentBatch:
    """Represents a parsed 835 ERA file."""
    payer_name: str = ""
    payer_id: str = ""
    payee_name: str = ""
    payee_npi: str = ""
    check_number: str = ""
    payment_method: str = ""  # CHK, ACH, FWT, etc.
    total_paid: Decimal = Decimal("0")
    production_date: date | None = None
    claims: list[EDIClaim] = field(default_factory=list)

    @property
    def total_claims(self) -> int:
        return len(self.claims)

    @property
    def denial_count(self) -> int:
        return sum(1 for c in self.claims if c.has_denials)


# ── 835 Parser ───────────────────────────────────────────────────

class ERA835Parser:
    """
    Parse X12 835 Electronic Remittance Advice files.
    Extracts payment information, adjustments, and remark codes.
    """

    def parse(self, raw_content: str) -> EDIPaymentBatch:
        """Parse a raw X12 835 string into structured data."""
        # Detect delimiters from ISA segment
        if len(raw_content) < 106:
            raise ValueError("Invalid 835 file: too short for ISA segment")

        element_sep = raw_content[3]     # Usually *
        segment_sep = raw_content[105]   # Usually ~ or \n
        sub_sep = raw_content[104]       # Usually :

        segments = [s.strip() for s in raw_content.split(segment_sep) if s.strip()]

        batch = EDIPaymentBatch()
        current_claim: EDIClaim | None = None
        current_line: EDIServiceLine | None = None

        for segment in segments:
            elements = segment.split(element_sep)
            seg_id = elements[0]

            if seg_id == "N1" and len(elements) > 2:
                # Payer / Payee identification
                if elements[1] == "PR":  # Payer
                    batch.payer_name = elements[2] if len(elements) > 2 else ""
                    batch.payer_id = elements[4] if len(elements) > 4 else ""
                elif elements[1] == "PE":  # Payee
                    batch.payee_name = elements[2] if len(elements) > 2 else ""
                    batch.payee_npi = elements[4] if len(elements) > 4 else ""

            elif seg_id == "BPR" and len(elements) > 1:
                # Financial information
                batch.total_paid = Decimal(elements[2]) if len(elements) > 2 else Decimal("0")
                batch.payment_method = elements[4] if len(elements) > 4 else ""

            elif seg_id == "TRN" and len(elements) > 2:
                batch.check_number = elements[2]

            elif seg_id == "DTM" and len(elements) > 2:
                if elements[1] == "405":  # Production date
                    batch.production_date = self._parse_date(elements[2])

            elif seg_id == "CLP" and len(elements) > 1:
                # Claim level - start new claim
                if current_claim:
                    batch.claims.append(current_claim)
                current_claim = EDIClaim(
                    claim_id=elements[1],
                    status_code=elements[2] if len(elements) > 2 else "",
                    total_charge=Decimal(elements[3]) if len(elements) > 3 else Decimal("0"),
                    total_paid=Decimal(elements[4]) if len(elements) > 4 else Decimal("0"),
                    patient_responsibility=Decimal(elements[5]) if len(elements) > 5 else Decimal("0"),
                    payer_claim_number=elements[7] if len(elements) > 7 else "",
                )
                current_line = None

            elif seg_id == "CAS" and len(elements) > 3:
                # Adjustment information
                adj = self._parse_cas_segment(elements, sub_sep)
                if current_line:
                    current_line.adjustments.extend(adj)
                elif current_claim:
                    current_claim.claim_adjustments.extend(adj)

            elif seg_id == "SVC" and current_claim and len(elements) > 1:
                # Service line
                proc_info = elements[1].split(sub_sep)
                current_line = EDIServiceLine(
                    procedure_code=proc_info[1] if len(proc_info) > 1 else proc_info[0],
                    charge_amount=Decimal(elements[2]) if len(elements) > 2 else Decimal("0"),
                    paid_amount=Decimal(elements[3]) if len(elements) > 3 else Decimal("0"),
                    units=int(elements[5]) if len(elements) > 5 and elements[5] else 1,
                )
                current_claim.service_lines.append(current_line)

            elif seg_id == "AMT" and len(elements) > 2:
                if elements[1] == "B6" and current_line:  # Allowed amount
                    current_line.allowed_amount = Decimal(elements[2])

            elif seg_id == "LQ" and len(elements) > 2:
                # Remark codes
                if current_line and current_line.adjustments:
                    current_line.adjustments[-1].remark_codes.append(elements[2])

        # Add last claim
        if current_claim:
            batch.claims.append(current_claim)

        logger.info(
            "era_parsed",
            payer=batch.payer_name,
            total_paid=str(batch.total_paid),
            claim_count=batch.total_claims,
            denial_count=batch.denial_count,
        )

        return batch

    def _parse_cas_segment(self, elements: list[str], sub_sep: str) -> list[EDIAdjustment]:
        """Parse a CAS (adjustment) segment which can contain multiple adjustments."""
        adjustments = []
        group_code = elements[1]

        # CAS segments contain groups of 3: reason_code, amount, quantity
        i = 2
        while i < len(elements) and elements[i]:
            reason_code = elements[i]
            amount = Decimal(elements[i + 1]) if i + 1 < len(elements) and elements[i + 1] else Decimal("0")
            quantity = int(elements[i + 2]) if i + 2 < len(elements) and elements[i + 2] else None

            try:
                gc = AdjustmentGroupCode(group_code)
            except ValueError:
                gc = AdjustmentGroupCode.OA

            adjustments.append(EDIAdjustment(
                group_code=gc,
                reason_code=reason_code,
                amount=amount,
                quantity=quantity,
            ))
            i += 3

        return adjustments

    @staticmethod
    def _parse_date(date_str: str) -> date | None:
        """Parse CCYYMMDD date format."""
        try:
            return datetime.strptime(date_str, "%Y%m%d").date()
        except (ValueError, TypeError):
            return None


# ── 837 Generator ────────────────────────────────────────────────

class Claim837Generator:
    """
    Generate X12 837P (Professional) or 837I (Institutional) claim files.
    """

    def __init__(self, sender_id: str, receiver_id: str):
        self.sender_id = sender_id.ljust(15)
        self.receiver_id = receiver_id.ljust(15)
        self.element_sep = "*"
        self.segment_sep = "~\n"
        self.sub_sep = ":"

    def generate_837p(self, claims: list[dict]) -> str:
        """Generate an 837P (Professional) transaction set."""
        segments: list[str] = []

        # ISA - Interchange Control Header
        segments.append(self._isa_segment())
        # GS - Functional Group Header
        segments.append(self._gs_segment("HC"))
        # ST - Transaction Set Header
        segments.append(self._st_segment("837"))
        # BHT - Beginning of Hierarchical Transaction
        segments.append(self._bht_segment())

        for claim_data in claims:
            segments.extend(self._claim_segments(claim_data))

        # SE, GE, IEA trailers
        seg_count = len(segments) + 1  # +1 for SE itself
        segments.append(f"SE{self.element_sep}{seg_count}{self.element_sep}0001")
        segments.append(f"GE{self.element_sep}1{self.element_sep}1")
        segments.append(f"IEA{self.element_sep}1{self.element_sep}000000001")

        return self.segment_sep.join(segments) + self.segment_sep

    def _isa_segment(self) -> str:
        """ISA interchange control header."""
        now = datetime.now()
        return (
            f"ISA{self.element_sep}00{self.element_sep}          "
            f"{self.element_sep}00{self.element_sep}          "
            f"{self.element_sep}ZZ{self.element_sep}{self.sender_id}"
            f"{self.element_sep}ZZ{self.element_sep}{self.receiver_id}"
            f"{self.element_sep}{now.strftime('%y%m%d')}"
            f"{self.element_sep}{now.strftime('%H%M')}"
            f"{self.element_sep}^{self.element_sep}00501"
            f"{self.element_sep}000000001{self.element_sep}0"
            f"{self.element_sep}P{self.element_sep}{self.sub_sep}"
        )

    def _gs_segment(self, func_id: str) -> str:
        now = datetime.now()
        return (
            f"GS{self.element_sep}{func_id}{self.element_sep}{self.sender_id.strip()}"
            f"{self.element_sep}{self.receiver_id.strip()}"
            f"{self.element_sep}{now.strftime('%Y%m%d')}"
            f"{self.element_sep}{now.strftime('%H%M')}"
            f"{self.element_sep}1{self.element_sep}X{self.element_sep}005010X222A1"
        )

    def _st_segment(self, txn_type: str) -> str:
        return f"ST{self.element_sep}{txn_type}{self.element_sep}0001{self.element_sep}005010X222A1"

    def _bht_segment(self) -> str:
        now = datetime.now()
        return (
            f"BHT{self.element_sep}0019{self.element_sep}00"
            f"{self.element_sep}{now.strftime('%Y%m%d%H%M%S')}"
            f"{self.element_sep}{now.strftime('%Y%m%d')}"
            f"{self.element_sep}{now.strftime('%H%M')}{self.element_sep}CH"
        )

    def _claim_segments(self, claim: dict) -> list[str]:
        """Generate segments for a single claim. Placeholder — expand per X12 spec."""
        segments = []
        # TODO: Full 837P implementation with:
        # - 2000A Billing Provider HL
        # - 2010AA Billing Provider Name/Address
        # - 2000B Subscriber HL
        # - 2010BA Subscriber Name
        # - 2010BB Payer Name
        # - 2300 Claim Information (CLM segment)
        # - 2400 Service Lines (SV1 segments for 837P)
        # Each with proper qualifiers, loops, and validation
        logger.info("claim_837_generated", claim_id=claim.get("claim_number"))
        return segments

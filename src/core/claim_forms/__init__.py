"""Claim form assembly + enrichment (CMS-1500 professional, UB-04 institutional).

Turns a coded Claim into the full set of fields on the actual paper claim forms,
auto-enriching provider identifiers from NPPES and payers from the CMS/payer map.
"""
from .assembler import assemble_claim_form  # noqa: F401

"""
Research Confidence & Epistemic Evidence Ledger Service
"""
from typing import List, Dict, Any
from src.database.db import db

class EvidenceLedgerService:
    def get_all_claims(self) -> List[Dict[str, Any]]:
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT claim_id, claim_statement, epistemic_grade, empirical_evidence_summary,
                       sample_size_evaluated, verified_by, last_audit_timestamp
                FROM evidence_registry
                ORDER BY id ASC
            """)
            rows = cursor.fetchall()
            return [
                {
                    "claim_id": r["claim_id"],
                    "claim_statement": r["claim_statement"],
                    "epistemic_grade": r["epistemic_grade"],
                    "empirical_evidence_summary": r["empirical_evidence_summary"],
                    "sample_size_evaluated": r["sample_size_evaluated"],
                    "verified_by": r["verified_by"],
                    "last_audit_timestamp": r["last_audit_timestamp"]
                }
                for r in rows
            ]

    def register_claim(self, claim_id: str, statement: str, grade: str, evidence: str, sample_size: int, verifier: str):
        with db.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO evidence_registry (
                    claim_id, claim_statement, epistemic_grade, empirical_evidence_summary,
                    sample_size_evaluated, verified_by
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (claim_id, statement, grade, evidence, sample_size, verifier))

evidence_ledger = EvidenceLedgerService()

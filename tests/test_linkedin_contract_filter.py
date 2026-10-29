import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from contract_filter import classify_contract_job
from parser import parse_job_detail


def job(title="Software Engineer", description=""):
    return {"title": title, "description": description, "contractType": "Contract"}


class LinkedInContractFilterTests(unittest.TestCase):
    def test_live_sample_phrases(self):
        cases = (
            (job("Java Developer | W2 ONLY", "Not available C2C or 1099"), "skip"),
            (job(description="Pay rate: $80/hr on W2. We are not able to consider C2C or third-party submissions."), "skip"),
            (job(description="Contract Type: W2. Duration: 6 months."), "skip"),
            (job(description="Engagement: 6+ Months (C2C)"), "keep"),
            (job(description="Open to CTC as well as W2 candidates"), "review"),
            (job(description="It is a contract to hire role"), "review"),
            (job(), "review"),
        )
        for listing, expected in cases:
            with self.subTest(listing=listing):
                self.assertEqual(classify_contract_job(listing).status, expected)

    def test_mixed_w2_and_c2c_is_saved(self):
        for description in ("Contract - C2C / W2", "Corp-to-Corp candidates accepted. W2 also available."):
            with self.subTest(description=description):
                self.assertEqual(classify_contract_job(job(description=description)).status, "keep")

    def test_1099_and_independent_contracts_are_saved(self):
        for description in ("Contract (1099)", "Independent Contractor position"):
            with self.subTest(description=description):
                self.assertEqual(classify_contract_job(job(description=description)).status, "keep")

    def test_agency_rejection_overrides_1099(self):
        listing = job(description="1099 contract role. NO AGENCIES OR THIRD PARTIES PLEASE.")
        self.assertEqual(classify_contract_job(listing).status, "skip")

    def test_negated_c2c_is_not_an_offer(self):
        for description in (
            "No C2C or 1099. W2 only.",
            "C2C or 1099 not accepted.",
            "C2C not accepted.",
            "Can't do Corp to Corp or 1099.",
        ):
            with self.subTest(description=description):
                self.assertEqual(classify_contract_job(job(description=description)).status, "skip")

    def test_explicit_1099_survives_no_c2c(self):
        listing = job(description="No C2C, but 1099 independent contractors are accepted.")
        self.assertEqual(classify_contract_job(listing).status, "keep")

    def test_third_party_rejection_without_w2_is_skipped(self):
        listing = job(description="We are not able to consider third-party submissions.")
        self.assertEqual(classify_contract_job(listing).status, "skip")

    def test_conflicting_w2_only_and_c2c_goes_to_review(self):
        listing = job(title="Engineer - W2 only", description="C2C candidates accepted.")
        self.assertEqual(classify_contract_job(listing).status, "review")

    def test_generic_benefits_and_independent_work_are_not_payment_terms(self):
        listing = job(description="Work independently. W2 employees are eligible for benefits.")
        self.assertEqual(classify_contract_job(listing).status, "review")

    def test_parser_output_can_be_classified(self):
        html = '''
            <div class="show-more-less-html__markup">Contract Type: W2. No C2C.</div>
            <ul class="description__job-criteria-list">
              <li class="description__job-criteria-item">
                <h3 class="description__job-criteria-subheader">Employment type</h3>
                <span class="description__job-criteria-text">Contract</span>
              </li>
            </ul>
        '''
        listing = parse_job_detail(html, job())
        self.assertEqual(listing["contractType"], "Contract")
        self.assertEqual(classify_contract_job(listing).status, "skip")


if __name__ == "__main__":
    unittest.main()

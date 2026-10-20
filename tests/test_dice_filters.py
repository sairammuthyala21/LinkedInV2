import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dice_parser import expected_contract_label, matches_selected_job_type, parse_job_detail


def detail_job(*badges, title="Data Engineer", description="", employment_type="CONTRACTOR"):
    badge_html = "".join(
        f'<div class="SeuiInfoBadge"><div>{label}</div></div>'
        for label in badges
    )
    html = f'''
        <script type="application/ld+json">
          {{"@type":"JobPosting","title":"{title}",
            "employmentType":"{employment_type}","description":"{description}"}}
        </script>
        <div data-testid="job-detail-header-card">{badge_html}</div>
    '''
    return parse_job_detail(html, {"jobId": "sample", "contractType": "Contract"})


class DiceJobTypeFilterTests(unittest.TestCase):
    def test_input_codes_resolve_to_labels(self):
        self.assertEqual(expected_contract_label("C"), "Contract")
        self.assertEqual(expected_contract_label("F"), "Full-time")
        self.assertEqual(expected_contract_label(""), "")

    def test_corp_to_corp_badge_qualifies_with_other_badges(self):
        job = detail_job(
            "Contract Corp To Corp", "Contract Independent", "Contract W2",
            "6 Months", "On-site",
        )
        self.assertEqual(job["contractType"], "Contract")
        self.assertIn("Contract Corp To Corp", job["_diceDetailBadges"])
        self.assertTrue(matches_selected_job_type("Contract", job))

    def test_corp_to_corp_badge_decides_even_if_description_says_w2_only(self):
        job = detail_job("Contract Corp To Corp", "Contract W2",
                         description="W2 only")
        self.assertTrue(matches_selected_job_type("Contract", job))

    def test_w2_badge_without_corp_to_corp_is_excluded(self):
        job = detail_job("Contract W2", description="W2 only. No C2C.")
        self.assertFalse(matches_selected_job_type("Contract", job))

    def test_independent_badge_without_corp_to_corp_is_excluded(self):
        job = detail_job("Contract Independent", "Contract W2")
        self.assertFalse(matches_selected_job_type("Contract", job))

    def test_c2c_title_qualifies_without_corp_to_corp_badge(self):
        job = detail_job("Contract W2", title="Oracle ADF Developer - C2C")
        self.assertTrue(matches_selected_job_type("Contract", job))

    def test_c2c_description_qualifies_without_corp_to_corp_badge(self):
        job = detail_job("Contract W2", description="Corp-to-Corp candidates accepted")
        self.assertTrue(matches_selected_job_type("Contract", job))

    def test_negated_c2c_mentions_do_not_qualify(self):
        cases = (
            {"title": "Java Lead Engineer - No C2C", "description": "W2 only"},
            {"title": "Data Engineer", "description": "No C2C or 1099"},
            {"title": "Data Engineer", "description": "C2C not accepted"},
            {"title": "Software Developer", "description": "Can't do Corp to Corp or 1099"},
            {"title": "Assembler", "description": "NO H-1B or Corp to Corp"},
        )
        for case in cases:
            with self.subTest(case=case):
                job = detail_job("Contract W2", **case)
                self.assertFalse(matches_selected_job_type("Contract", job))

    def test_no_c2c_evidence_is_excluded(self):
        job = detail_job("Contract W2", title="Data Engineer", description="W2 contract")
        self.assertFalse(matches_selected_job_type("Contract", job))

    def test_other_job_types_still_use_normalized_employment_type(self):
        job = detail_job("Full-time", employment_type="FULL_TIME")
        self.assertTrue(matches_selected_job_type("Full-time", job))
        self.assertFalse(matches_selected_job_type("Contract", job))
        self.assertTrue(matches_selected_job_type("", job))


if __name__ == "__main__":
    unittest.main()

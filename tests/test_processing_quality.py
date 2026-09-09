import unittest

import pandas as pd

from services.processing_service import ProcessingService


class ProcessingQualityTests(unittest.TestCase):
    def test_quality_report_detects_invalid_academic_values(self):
        frame = pd.DataFrame([
            {"student_id": "S-1", "course_id": "C-1", "score": 82},
            {"student_id": "", "course_id": "C-1", "score": 120},
            {"student_id": "S-3", "course_id": "C-1", "score": 70},
            {"student_id": "S-3", "course_id": "C-1", "score": 70},
        ])

        report = ProcessingService.quality_report(frame)

        self.assertEqual(report["records_input"], 4)
        self.assertEqual(report["records_invalid"], 1)
        self.assertEqual(report["duplicates_removed"], 1)
        self.assertEqual(report["quality_status"], "INVALID")
        self.assertLess(report["data_quality_score"], 100)


if __name__ == "__main__":
    unittest.main()

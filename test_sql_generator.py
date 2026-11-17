import unittest

from sql_generator import build_select_query, is_lr_multi_field, lr_multi_index


class SqlGeneratorTests(unittest.TestCase):
    def test_build_select_query_for_account(self):
        sql = build_select_query(
            application="ACCOUNT",
            table_name="T24MD.ACCOUNT#HIS@AMLCRT",
            alias="ACC",
        )

        self.assertIn("SELECT", sql)
        self.assertIn("EXTRACTVALUE(ACC.XMLRECORD", sql)
        self.assertIn("AS ACCOUNT_TITLE_1", sql)
        self.assertIn("FROM", sql)
        self.assertIn("T24MD.ACCOUNT#HIS@AMLCRT ACC", sql)

    def test_build_select_query_for_single_field(self):
        sql = build_select_query(
            application="ACCOUNT",
            table_name="T24MD.ACCOUNT#HIS@AMLCRT",
            alias="ACC",
            field_name="CUSTOMER",
        )

        self.assertIn("AS CUSTOMER", sql)
        self.assertNotIn("AS CONTRACT_DATE", sql)
        self.assertNotIn("AS ACCOUNT_TITLE_1", sql)

    def test_formula_fields_are_filtered_out(self):
        sql = build_select_query(
            application="ACCOUNT",
            table_name="T24MD.ACCOUNT#HIS@AMLCRT",
            alias="ACC",
        )

        self.assertNotIn("SUBR(", sql)
        self.assertNotIn("LOWER(", sql)
        self.assertNotIn("IF ", sql)

    def test_lr_multi_field_uses_m_attribute(self):
        row = {
            "APPLICATION": "ACCOUNT",
            "ORDRE_CHAMPS": "",
            "CHAMP": "AUTRE.MOTIF.OUV",
            "REGLE": "LR",
            "TYPE_INPUT": "5",
            "CHAMP_MUTIPLE": "M",
        }

        self.assertTrue(is_lr_multi_field(row))
        self.assertEqual(lr_multi_index(row), "5")
        self.assertEqual(build_select_query(
            application="ACCOUNT",
            table_name="T24MD.ACCOUNT#HIS@AMLCRT",
            alias="ACC",
            field_name="AUTRE.MOTIF.OUV",
        ).split("AS ")[-1].splitlines()[0].strip().split(",")[0], "AUTRE_MOTIF_OUV")


if __name__ == "__main__":
    unittest.main()

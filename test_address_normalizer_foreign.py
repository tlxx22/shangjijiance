import unittest

from src.address_normalizer import AddressGroup, _infer_country_from_places, _validate_group


class TestAddressNormalizerForeign(unittest.TestCase):
	def test_infer_country_from_city_hints(self):
		inferred = _infer_country_from_places(
			detail="P.PaternoStreet,Brgy,Biñan,Laguna",
			province="",
			city="",
			district="",
		)
		self.assertEqual(inferred, "菲律宾")

	def test_foreign_city_allows_diacritics(self):
		ok, reason = _validate_group(
			AddressGroup(country="菲律宾", province="Laguna", city="Biñan", district="")
		)
		self.assertTrue(ok)
		self.assertEqual(reason, "ok_non_cn")


if __name__ == "__main__":
	unittest.main()


"""The shared hash list carries the private-list hashes removed in v1.13.1 (hashes only, no terms)."""

import unittest

from support import ROOT, load

HASHES = (
    "dd221319b058fd80bf9028981e5d9e892d6102c48eec8b71b97863739a176874",
    "136c67657614311f32238751044a0a3c0294f2a521e573afa8e496992d3786ba",
    "1b1dc5931c24740a57e2acf197908c069bbabfb8892a9e70db8df0a4249e75ed",
    "f17d83c39a9b891877308161cb1213d4b8810e360d946f10f0a904ad84090a1f",
    "3f40462915a3e6026a4d790127b95ded4d870f6ab18d9af2fcbc454168255237",
    "c33f07e69989bd1ab0bac709a19487d6fe05aba4828ac61ca4915aab6dc9d852",
    "f24fd3749c1368328e2b149bec149cb6795619f244c5b584e844961215dadd16",
    "3828b2c6c467659709457d56ce8c9776d15109e8119165cc8e1c02eb7b6ae4c1",
    "dc8dc03d4332f493adb0e2a3f876a5dfbd944a728be07c04d4ca43a06fabc5f3",
    "8a809f06a2e185a350ce7a2e1292c457eda513c63143626234a2f2800477ad97",
    "b5738c169b693bee89e1b74ebd48e0dfa53a34e8571790b7727721a0bfadc470",
    "3b94c85afc66d7aeb7c5d590eb34df9b530ee119aaaa9b6b8f13b3e009f51d5b",
)


class PrivateListHashes(unittest.TestCase):
    def test_hashes_are_in_the_shared_list(self):
        san = load("check_sanitised", "checks/check-sanitised.py")
        listed = san.shared_hashes()
        self.assertEqual([h for h in HASHES if h not in listed], [])

    def test_list_file_holds_only_hashes_and_comments(self):
        for ln in (ROOT / "checks/denylist.sha256").read_text().splitlines():
            if ln.strip() and not ln.startswith("#"):
                self.assertRegex(ln.strip(), r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()

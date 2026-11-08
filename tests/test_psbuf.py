import unittest

from bcmsoftap.psbuf import PsBuffer

A, B = b"\xaa" * 6, b"\xbb" * 6


class PsBufferTest(unittest.TestCase):
    """Frames for a phone that said it sleeps (PM bit) wait until it says it's awake.
    iOS flips PM many times a second while it scans other channels right after
    joining; frames sent meanwhile were lost and it left (box log 2026-11-08)."""

    def setUp(self):
        self.sent = []
        self.b = PsBuffer(lambda sta, frame: self.sent.append((sta, frame)), limit=3)

    def test_awake_phone_gets_frames_at_once(self):
        self.b.send(A, "f1")
        self.assertEqual(self.sent, [(A, "f1")])

    def test_sleeping_phone_gets_them_when_it_wakes(self):
        self.b.power(A, sleeping=True)
        self.b.send(A, "f1")
        self.b.send(A, "f2")
        self.assertEqual(self.sent, [])
        self.b.power(A, sleeping=False)
        self.assertEqual(self.sent, [(A, "f1"), (A, "f2")])
        self.b.power(A, sleeping=False)  # no second flush
        self.assertEqual(len(self.sent), 2)

    def test_other_phones_are_not_held(self):
        self.b.power(A, sleeping=True)
        self.b.send(B, "f1")
        self.assertEqual(self.sent, [(B, "f1")])

    def test_ps_poll_releases_one_frame(self):
        self.b.power(A, sleeping=True)
        self.b.send(A, "f1")
        self.b.send(A, "f2")
        self.b.ps_poll(A)
        self.assertEqual(self.sent, [(A, "f1")])

    def test_queue_drops_oldest_beyond_limit(self):
        self.b.power(A, sleeping=True)
        for i in range(5):
            self.b.send(A, f"f{i}")
        self.b.power(A, sleeping=False)
        self.assertEqual([f for _, f in self.sent], ["f2", "f3", "f4"])

    def test_forget_drops_held_frames(self):
        self.b.power(A, sleeping=True)
        self.b.send(A, "f1")
        self.b.forget(A)
        self.b.send(A, "f2")  # a re-joined phone starts awake
        self.assertEqual(self.sent, [(A, "f2")])


if __name__ == "__main__":
    unittest.main()

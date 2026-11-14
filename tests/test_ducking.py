"""Приглушение: музыка тише, пока с Chloe говорят и пока она отвечает; свой голос не трогается; громкость,
которую пользователь сам поменял, не возвращается назад."""
import json
import os
import unittest
from unittest import mock

from chloe import ducking as D


def stream(idx, pct, pid):
    return {"index": idx, "volume": {"front-left": {"value_percent": "%d%%" % pct}, "front-right": {"value_percent": "%d%%" % pct}},
            "properties": {"application.process.id": str(pid), "application.name": "app%s" % pid}}


class Ducking(unittest.TestCase):
    def setUp(self):
        D._saved.clear()
        D._apps.clear()
        self.vol = {1: 100, 2: 80, 3: 100}
        self.pids = {1: 999, 2: 998, 3: os.getpid()}       # 3 — голос самой Chloe

        def run(cmd, **kw):
            if cmd[:3] == ["pactl", "-f", "json"]:
                return mock.Mock(stdout=json.dumps([stream(i, v, self.pids[i]) for i, v in self.vol.items()]), returncode=0)
            if cmd[1] == "set-sink-input-volume":
                self.vol[int(cmd[2])] = int(cmd[3].rstrip("%"))
            return mock.Mock(stdout="", returncode=0)
        p = [mock.patch.object(D.subprocess, "run", side_effect=run), mock.patch.object(D, "LEVEL", 20),
             mock.patch.object(D.shutil, "which", return_value="/usr/bin/pactl")]
        for x in p:
            x.start()
            self.addCleanup(x.stop)
        self.addCleanup(D.release)

    def test_duck_and_restore(self):
        D.duck()
        self.assertEqual(self.vol, {1: 20, 2: 16, 3: 100})            # своё не тронуто
        D.duck()                                                       # повтор не приглушает ещё сильнее
        self.assertEqual(self.vol[1], 20)
        D.release()
        self.assertEqual(self.vol, {1: 100, 2: 80, 3: 100})

    def test_user_changed_volume_is_kept(self):
        D.duck()
        self.vol[1] = 55                                               # пользователь сам сделал громче
        D.release()
        self.assertEqual(self.vol[1], 55)
        self.assertEqual(self.vol[2], 80)

    def test_new_stream_ducked_on_repeat(self):
        D.duck()
        self.vol[4], self.pids[4] = 100, 997                           # Chloe включила видео во время ответа
        D.duck()
        self.assertEqual(self.vol[4], 20)
        D.release()
        self.assertEqual(self.vol[4], 100)

    def test_new_stream_inherits_ducked_volume_and_is_restored(self):
        D.duck()                                                       # Firefox (pid 999) 100 → 20
        self.vol[5], self.pids[5] = 20, 999                            # новое видео в Firefox: PipeWire дал ему 20
        D.release()
        self.assertEqual(self.vol[5], 100)                             # вернулось вместе с остальными
        self.assertEqual(self.vol[1], 100)

    def test_listing_failure_keeps_saved_volume(self):
        D.duck()
        with mock.patch.object(D, "_streams", return_value=None):
            D.release()                                                # pactl не ответил — не забываем
        self.assertTrue(D.ducked())
        D.release()
        self.assertEqual(self.vol[1], 100)

    def test_off(self):
        with mock.patch.object(D, "LEVEL", 0):
            D.duck()
        self.assertEqual(self.vol[1], 100)


if __name__ == "__main__":
    unittest.main()

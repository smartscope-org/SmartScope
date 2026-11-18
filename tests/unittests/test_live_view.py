import os
import tempfile
from pathlib import Path
from unittest import TestCase, mock

from Smartscope.core import live_view


class FakeCache(dict):
    def set(self, key, value, timeout=None):
        self[key] = value


class TestLiveView(TestCase):

    def setUp(self):
        self.scope_path = tempfile.mkdtemp()
        self.frames = live_view.frames_directory(self.scope_path)
        self.frames.mkdir(parents=True)
        cache = mock.patch.object(live_view, 'cache', FakeCache())
        cache.start()
        self.addCleanup(cache.stop)

    def write(self, name, content, mtime):
        path = self.frames / name
        path.write_text(content)
        os.utime(path, (mtime, mtime))

    def read_at(self, now):
        with mock.patch.object(live_view.time, 'time', return_value=now):
            return live_view.read_frames('scope', self.scope_path)

    def test_no_watcher(self):
        self.assertIsNone(live_view.read_frames('scope', self.scope_path))

    def test_index_is_parsed_and_bad_lines_skipped(self):
        self.write('heartbeat.txt', '', 1000)
        self.write('index.txt', '\n'.join([
            '7 frame_7.jpg 720 511 1440 1022 63.12',
            '8 ../secret.jpg 720 511 1440 1022 63.12',
            '9 frame_9.jpg 720 511 wide 1022 63.12',
            '10 frame_10.jpg 1024 728 5760 4092 0',
            'truncated',
        ]), 1000)
        frames = live_view.read_frames('scope', self.scope_path)['frames']
        self.assertEqual([f['file'] for f in frames], ['frame_7.jpg', 'frame_10.jpg'])
        self.assertAlmostEqual(frames[0]['field_of_view_um'], 9.089, places=3)
        self.assertIsNone(frames[1]['pixel_size_A'])

    def test_age_survives_an_unsynchronised_clock(self):
        # The SerialEM computer is an hour ahead of this server.
        ahead = 3600
        self.write('index.txt', '1 frame_1.jpg 10 10 10 10 1', 5000 + ahead)
        self.write('heartbeat.txt', '', 5000 + ahead)
        first = self.read_at(5001)
        self.assertIsNone(first['age'])
        self.assertIsNone(first['running'])
        self.write('heartbeat.txt', '', 5005 + ahead)
        live = self.read_at(5006)
        self.assertTrue(live['running'])
        self.assertLess(live['age'], 10)
        self.write('heartbeat.txt', '', 5125 + ahead)
        idle = self.read_at(5126)
        self.assertTrue(idle['running'])
        self.assertAlmostEqual(idle['age'], 125, delta=2)
        stopped = self.read_at(5300)
        self.assertFalse(stopped['running'])

    def test_frame_names_cannot_leave_the_folder(self):
        self.write('frame_12.jpg', 'x', 1000)
        (Path(self.scope_path) / 'secret.jpg').write_text('x')
        self.assertEqual(live_view.frame_file(self.scope_path, 'frame_12.jpg'), self.frames / 'frame_12.jpg')
        for name in ['../secret.jpg', 'frame_12.jpg/../../secret.jpg', 'index.txt', 'frame_13.jpg', 'frame_.jpg']:
            self.assertIsNone(live_view.frame_file(self.scope_path, name))

    def test_install_watcher(self):
        launcher = live_view.install_watcher(
            self.scope_path, 'X:\\\\Data\\SmartScope', ['C:\\SerialEM', '', 'C:\\SerialEM', 'D:\\Sessions'])
        self.assertEqual(launcher, 'X:\\Data\\SmartScope\\live_view\\SmartScopeLiveImage.bat')
        directory = live_view.watcher_directory(self.scope_path)
        self.assertTrue((directory / 'SmartScopeLiveImage.ps1').is_file())
        self.assertTrue((directory / 'SmartScopeLiveImage.bat').is_file())
        self.assertEqual((directory / 'live_sources.txt').read_bytes(), b'C:\\SerialEM\r\nD:\\Sessions\r\n')
